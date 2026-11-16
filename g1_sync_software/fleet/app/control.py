"""Control tab backend.

Two modes, chosen by `control.dry_run` in robots.yaml (default: true):

* dry run: a command is turned into the shell line that WOULD run, logged, and
  the assumed robot state is updated. Nothing is sent.
* live (`dry_run: false`): the same shell line is run on the robot over SSH.
  It only ever does two things there: start SONIC inside a tmux session
  (Initialize) and type single keys into that session (`tmux send-keys`).

In both modes the tmux pane text is read (read-only) so the SONIC console can
be watched.

Key meanings follow the SONIC keyboard tutorial:
https://nvlabs.github.io/GR00T-WholeBodyControl/tutorials/keyboard.html

E-STOP sends `O` (stop control and exit). It is a software stop over Wi-Fi and
SSH, NOT a safety-rated stop. Keep the physical e-stop in reach.
"""
from __future__ import annotations

import asyncio
import shlex
import time
from typing import Any

import asyncssh

# command -> (key, mode the key is valid in or None for any, label)
KEYS: dict[str, tuple[str, str | None, str]] = {
    "policy":        ("]", None,      "Policy"),
    "estop":         ("O", None,      "E-STOP"),
    "reset_heading": ("I", None,      "Reset heading"),
    "play":          ("T", "normal",  "Play"),
    "restart":       ("R", "normal",  "Restart"),
    "turn_left":     ("Q", "normal",  "Turn left"),
    "turn_right":    ("E", "normal",  "Turn right"),
    "forward":       ("W", "planner", "Forward"),
    "backward":      ("S", "planner", "Backward"),
    "veer_left":     ("A", "planner", "Veer left"),
    "veer_right":    ("D", "planner", "Veer right"),
    "strafe_left":   (",", "planner", "Strafe left"),
    "strafe_right":  (".", "planner", "Strafe right"),
    "face_left":     ("Q", "planner", "Face left"),
    "face_right":    ("E", "planner", "Face right"),
    "halt":          ("R", "planner", "Halt"),
    "slower":        ("9", "planner", "Slower"),
    "faster":        ("0", "planner", "Faster"),
    "lower":         ("-", "planner", "Lower"),
    "higher":        ("=", "planner", "Higher"),
}

# Planner movement keys that repeat for as long as the button is held.
HOLDABLE = ("forward", "backward", "veer_left", "veer_right",
            "strafe_left", "strafe_right", "face_left", "face_right")

LOG_MAX = 100
INIT_GRACE_S = 10.0     # after Initialize, how long SONIC may take to show up as a process

# Robot states shown in the UI:
#   not running  no SONIC process
#   initialized  SONIC launched from here, control not started
#   policy       `]` sent from here
#   running      SONIC found already running; whether control is started is unknown
#   stopped      E-STOP sent from here
ALIVE = ("initialized", "policy", "running")


class Control:
    def __init__(self) -> None:
        # State per robot. It follows the buttons pressed here; in live mode it
        # is also corrected by whether a SONIC process actually exists. It is
        # never read from SONIC itself (control on/off, mode, frame).
        self.states: dict[str, dict[str, Any]] = {}
        self.panes: dict[str, dict[str, Any]] = {}
        self.log: list[dict[str, Any]] = []
        self.conns: dict[tuple, asyncssh.SSHClientConnection] = {}
        self.locks: dict[tuple, asyncio.Lock] = {}

    # ---------- config ----------
    @staticmethod
    def cfg(config: dict) -> dict:
        return config.get("control") or {}

    def dry_run(self, config: dict) -> bool:
        return self.cfg(config).get("dry_run", True) is not False

    def session(self, config: dict) -> str:
        return str(self.cfg(config).get("session", "sonic_demo"))

    def process(self, config: dict) -> str:
        return str(self.cfg(config).get("process", "g1_deploy_onnx_ref"))

    @staticmethod
    def launch(config: dict, name: str) -> str:
        launch = ""
        for r in config.get("robots", []) or []:
            if str(r.get("name")) == name and r.get("launch"):
                launch = " ".join(str(r["launch"]).split())
        return launch

    def state(self, name: str) -> dict[str, Any]:
        return self.states.setdefault(
            name, {"state": "not running", "mode": "normal", "last": None, "init_at": 0.0})

    # ---------- SSH ----------
    async def _run(self, robot: Any, key: str, cmd: str, timeout: float) -> asyncssh.SSHCompletedProcess:
        """Run one shell line on a robot over a kept-open SSH connection."""
        ck = (robot.host, robot.user, key)
        lock = self.locks.setdefault(ck, asyncio.Lock())
        for attempt in (0, 1):
            async with lock:
                conn = self.conns.get(ck)
                fresh = conn is None
                if fresh:
                    conn = await asyncssh.connect(robot.host, username=robot.user, client_keys=[key],
                                                  known_hosts=None, connect_timeout=5,
                                                  keepalive_interval=5)
                    self.conns[ck] = conn
            try:
                return await asyncio.wait_for(conn.run(cmd, check=False), timeout)
            except asyncio.TimeoutError:
                self._drop(ck, conn)
                raise                      # never retry: the key may already have been typed
            except (asyncssh.Error, OSError):
                self._drop(ck, conn)
                if fresh or attempt:       # only a stale kept-open connection gets one retry
                    raise
        raise RuntimeError("unreachable")

    def _drop(self, ck: tuple, conn: Any) -> None:
        if self.conns.get(ck) is conn:
            self.conns.pop(ck, None)
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    # ---------- commands ----------
    def _plan(self, config: dict, name: str, cmd: str, arg: Any
              ) -> tuple[str, str | None, str | None, dict[str, Any]]:
        """Return (label, shell line, refusal, state changes to apply once it is done)."""
        st = self.state(name)
        session = shlex.quote(self.session(config))
        alive = st["state"] in ALIVE

        if cmd == "initialize":
            if alive:
                return "Initialize", None, "SONIC already running; E-stop first", {}
            launch = self.launch(config, name)
            if not launch:
                return "Initialize", None, "no launch command for this robot in robots.yaml", {}
            sonic_dir = str(self.cfg(config).get("sonic_dir", "~"))
            typed = shlex.quote(f"cd {sonic_dir} && {launch}")
            line = (f"tmux has-session -t {session} 2>/dev/null || tmux new-session -d -s {session}; "
                    # C-u first: clear anything already typed at the shell prompt
                    # (for example an E-STOP "O" sent while SONIC was not running).
                    f"tmux send-keys -t {session} C-u && "
                    f"tmux send-keys -t {session} -l {typed} && tmux send-keys -t {session} Enter")
            return "Initialize", line, None, {"state": "initialized", "mode": "normal",
                                              "init_at": time.time()}

        if cmd == "mode":
            if arg not in ("normal", "planner"):
                return "Mode", None, "mode must be normal or planner", {}
            label = f"Mode {arg}"
            if not alive:
                return label, None, "SONIC not running", {}
            if st["mode"] == arg:
                return label, None, f"already in {arg} mode", {}
            return label, f"tmux send-keys -t {session} Enter", None, {"mode": arg}

        if cmd not in KEYS:
            return cmd, None, "unknown command", {}
        key, mode, label = KEYS[cmd]
        if cmd == "play" and arg:
            label = f"Play {arg}"
        line = f"tmux send-keys -t {session} -l {shlex.quote(key)}"

        if cmd == "estop":            # never refused
            return label, line, None, {"state": "stopped", "mode": "normal", "init_at": 0.0}
        if cmd == "policy":
            if st["state"] == "policy":
                return label, None, "control already started", {}
            if not alive:
                return label, None, "Initialize first", {}
            return label, line, None, {"state": "policy"}
        if st["state"] not in ("policy", "running"):
            return label, None, "control not started; press Policy first", {}
        if mode and st["mode"] != mode:
            return label, None, f"only valid in {mode} mode", {}
        return label, line, None, {}

    async def _send(self, robot: Any, key: str, line: str, timeout: float = 4.0) -> tuple[bool, str]:
        t0 = time.perf_counter()
        try:
            r = await self._run(robot, key, line, timeout)
        except Exception as e:  # noqa: BLE001
            return False, f"FAILED: {type(e).__name__}: {e}"
        ms = (time.perf_counter() - t0) * 1000
        if r.exit_status != 0:
            err = ((r.stderr or "") + (r.stdout or "")).strip() or f"exit {r.exit_status}"
            return False, f"FAILED: {err}"
        return True, f"sent in {ms:.0f} ms"

    async def command(self, config: dict, robots: dict, keys: dict[str, str], body: dict) -> dict[str, Any]:
        cmd = str(body.get("command", ""))
        targets = [t for t in (body.get("targets") or []) if t in robots]
        if not targets:
            return {"ok": False, "error": "no known target"}
        dry = self.dry_run(config)
        now = time.time()
        plans = {n: self._plan(config, n, cmd, body.get("arg")) for n in targets}

        async def one(name: str) -> tuple[str, str]:
            label, line, refusal, changes = plans[name]
            if refusal:
                return "refused", f"refused: {refusal}"
            if dry:
                self.state(name).update(changes)
                return "dry", "dry run, not sent"
            ok, result = await self._send(robots[name], keys[name], line)
            if ok:
                self.state(name).update(changes)
            return ("sent" if ok else "failed"), result

        done = await asyncio.gather(*(one(n) for n in targets))   # all robots at once
        results = {}
        for name, (kind, result) in zip(targets, done):
            label, line, _, _ = plans[name]
            self.state(name)["last"] = {"time": now, "label": label, "result": result}
            self.log.insert(0, {"time": now, "robot": name, "group": len(targets) > 1,
                                "command": label, "would": line or "", "result": result, "kind": kind})
            results[name] = result
        del self.log[LOG_MAX:]
        return {"ok": True, "dry_run": dry, "results": results}

    async def hold(self, config: dict, robots: dict, keys: dict[str, str], body: dict,
                   alive: Any) -> None:
        """Repeat one movement key while `alive()` is true (button held, browser still there).

        A terminal key held down is a stream of repeated characters; this is
        the same thing. Stops on release, on a missed browser heartbeat, when
        the robot leaves policy/planner state (for example E-STOP), or when a
        send fails.
        """
        cmd = str(body.get("command", ""))
        targets = [t for t in (body.get("targets") or []) if t in robots]
        if cmd not in HOLDABLE or not targets:
            return
        dry = self.dry_run(config)
        period = 1.0 / max(1.0, min(30.0, float(self.cfg(config).get("hold_hz", 10))))
        key, mode, label = KEYS[cmd]
        label = f"Hold {label}"
        line = f"tmux send-keys -t {shlex.quote(self.session(config))} -l {shlex.quote(key)}"
        group, now = len(targets) > 1, time.time()

        active = []
        for n in targets:
            refusal = self._plan(config, n, cmd, None)[2]
            if refusal:
                self._log(now, n, group, label, "", f"refused: {refusal}", "refused")
            else:
                active.append(n)
        counts = {n: 0 for n in active}
        failed: dict[str, str] = {}
        t0 = time.monotonic()
        while active and alive():
            tick = time.monotonic()
            active = [n for n in active
                      if self.state(n)["state"] in ("policy", "running") and self.state(n)["mode"] == mode]
            if not active:
                break
            if dry:
                for n in active:
                    counts[n] += 1
            else:
                got = await asyncio.gather(*(self._send(robots[n], keys[n], line, 1.0) for n in active))
                for n, (ok, result) in zip(list(active), got):
                    if ok:
                        counts[n] += 1
                    else:
                        failed[n] = result
                        active.remove(n)
            await asyncio.sleep(max(0.0, period - (time.monotonic() - tick)))
        held = time.monotonic() - t0
        for n, count in counts.items():
            if n in failed:
                self._log(now, n, group, label, line, f"{failed[n]} after {count} keys", "failed")
            else:
                self._log(now, n, group, label, line,
                          f"held {held:.1f} s, {count} keys" + (" (dry run, not sent)" if dry else ""),
                          "dry" if dry else "sent")

    def _log(self, when: float, robot: str, group: bool, label: str, line: str,
             result: str, kind: str) -> None:
        self.state(robot)["last"] = {"time": when, "label": label, "result": result}
        self.log.insert(0, {"time": when, "robot": robot, "group": group, "command": label,
                            "would": line, "result": result, "kind": kind})
        del self.log[LOG_MAX:]

    # ---------- read-only view of the robot ----------
    async def _capture(self, config: dict, name: str, robot: Any, key: str) -> dict[str, Any]:
        p = self.process(config)
        pattern = shlex.quote(f"[{p[0]}]{p[1:]}")        # [g]1_deploy… so pgrep does not match itself
        cmd = (f"pgrep -f {pattern} >/dev/null && echo @sonic=1 || echo @sonic=0; "
               f"tmux capture-pane -p -t {shlex.quote(self.session(config))} -S -80 2>&1")
        try:
            r = await self._run(robot, key, cmd, 5.0)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "text": "", "error": f"{type(e).__name__}: {e}",
                    "sonic": None, "time": time.time()}
        head, _, text = (r.stdout or "").partition("\n")
        sonic = head.strip() == "@sonic=1"
        text = text.rstrip()
        if r.exit_status != 0:
            return {"ok": False, "text": "", "error": text or "no tmux session",
                    "sonic": sonic, "time": time.time()}
        return {"ok": True, "text": text, "error": None, "sonic": sonic, "time": time.time()}

    def _sync(self, name: str, sonic: bool | None) -> None:
        """Live mode: correct the state from whether a SONIC process exists."""
        if sonic is None:
            return
        st = self.state(name)
        if sonic and st["state"] in ("not running", "stopped"):
            st["state"] = "running"
        elif not sonic and st["state"] in ALIVE:
            if time.time() - st.get("init_at", 0.0) > INIT_GRACE_S:
                st.update(state="not running", mode="normal")

    async def capture_panes(self, config: dict, robots: dict, keys: dict[str, str]) -> None:
        if not self.cfg(config).get("capture_panes", True):
            self.panes = {}
            return
        names = [n for n, s in robots.items() if s.ssh_ok]
        got = await asyncio.gather(*(self._capture(config, n, robots[n], keys[n]) for n in names))
        self.panes = dict(zip(names, got))
        if not self.dry_run(config):
            for n, pane in self.panes.items():
                self._sync(n, pane.get("sonic"))

    def snapshot(self, config: dict, robots: list[str]) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run(config),
            "session": self.session(config),
            "pane_interval_s": float(self.cfg(config).get("pane_interval_s", 1)),
            "motions": self.cfg(config).get("motions") or [],
            "robots": {n: {**self.state(n), "pane": self.panes.get(n)} for n in robots},
            "log": self.log,
        }

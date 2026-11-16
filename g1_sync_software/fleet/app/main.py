"""Fleet dashboard: shows which robots are connected and who they are.

The /control page and /api/command send SONIC keys to the robots only when
`control.dry_run: false` is set in robots.yaml (see control.py). Otherwise they
only log the shell line that would run.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import yaml
from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .probe import RobotState, probe_robot, scan_subnet
from .ntp import check_time_server
from .control import Control

CONFIG_PATH = Path(os.environ.get("ROBOTS_CONFIG", "/config/robots.yaml"))
STATIC_DIR = Path(__file__).parent / "static"

HOLD_DEADMAN_S = 0.4   # a held movement key stops this long after the last browser ping

app = FastAPI(title="Robot Fleet Monitor")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class Fleet:
    def __init__(self) -> None:
        self.config: dict = {}
        self.robots: dict[str, RobotState] = {}
        self.keys: dict[str, str] = {}
        self.clients: set[WebSocket] = set()
        self.scan: dict = {"running": False, "results": [], "finished_at": None}
        self.time_server: dict = {}
        self.config_mtime: float = 0.0
        self.control = Control()
        self.send_lock = asyncio.Lock()
        self.load_config()

    def load_config(self) -> None:
        mtime = CONFIG_PATH.stat().st_mtime
        if mtime == self.config_mtime:
            return
        self.config_mtime = mtime
        self.config = yaml.safe_load(CONFIG_PATH.read_text()) or {}
        new: dict[str, RobotState] = {}
        for r in self.config.get("robots", []) or []:
            name = str(r["name"])
            prev = self.robots.get(name)
            if prev and prev.host == r["host"] and prev.user == r.get("user", "unitree"):
                prev.role = r.get("role", "")
                new[name] = prev
            else:
                new[name] = RobotState(name=name, host=str(r["host"]),
                                       user=r.get("user", "unitree"), role=r.get("role", ""))
            self.keys[name] = r.get("key", "/keys/id_rsa")
        self.robots = new

    @property
    def poll_interval(self) -> float:
        return float(self.config.get("poll_interval_s", 5))

    def snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "time": time.time(),
            "poll_interval_s": self.poll_interval,
            "robots": [s.to_dict() for s in self.robots.values()],
            "scan": self.scan,
            "time_server": self.time_server,
            "timesync": self.config.get("timesync") or {},
            "control": self.control.snapshot(self.config, list(self.robots)),
        }

    async def broadcast(self) -> None:
        if not self.clients:
            return
        # One broadcast at a time, over a copy: browsers connect and disconnect
        # while we are awaiting a send.
        async with self.send_lock:
            msg = json.dumps(self.snapshot())
            for ws in list(self.clients):
                try:
                    await ws.send_text(msg)
                except Exception:  # noqa: BLE001
                    self.clients.discard(ws)

    async def poll_forever(self) -> None:
        while True:
            try:
                self.load_config()
            except Exception as e:  # noqa: BLE001
                print(f"[config] reload failed: {e}")
            ts = (self.config.get("timesync") or {}).get("pc_ip")
            await asyncio.gather(*(probe_robot(s, self.keys[n], ts) for n, s in self.robots.items()),
                                 return_exceptions=True)
            self.time_server = await check_time_server((self.config.get("timesync") or {}).get("ntp_host", "chrony"))
            await self.broadcast()
            await asyncio.sleep(self.poll_interval)

    async def pane_loop(self) -> None:
        """Faster loop for the Control tab: SONIC console text + process check."""
        while True:
            try:
                await self.control.capture_panes(self.config, self.robots, self.keys)
                await self.broadcast()
            except Exception as e:  # noqa: BLE001
                print(f"[control] pane capture failed: {e}")
            await asyncio.sleep(float((self.config.get("control") or {}).get("pane_interval_s", 1)))

    async def run_scan(self) -> None:
        if self.scan["running"]:
            return
        d = self.config.get("discovery") or {}
        if not d.get("subnet"):
            self.scan = {"running": False, "results": [], "finished_at": time.time(),
                         "error": "no discovery.subnet in robots.yaml"}
            await self.broadcast()
            return
        self.scan = {"running": True, "results": [], "finished_at": None, "subnet": d["subnet"]}
        await self.broadcast()
        try:
            results = await scan_subnet(d["subnet"], d.get("scan_user", "unitree"),
                                        d.get("scan_key", "/keys/id_rsa"),
                                        {s.host for s in self.robots.values()})
            self.scan = {"running": False, "results": results, "finished_at": time.time(),
                         "subnet": d["subnet"]}
        except Exception as e:  # noqa: BLE001
            self.scan = {"running": False, "results": [], "finished_at": time.time(),
                         "subnet": d["subnet"], "error": str(e)}
        await self.broadcast()


fleet = Fleet()


@app.on_event("startup")
async def _start() -> None:
    asyncio.create_task(fleet.poll_forever())
    asyncio.create_task(fleet.pane_loop())


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/robots")
async def api_robots() -> JSONResponse:
    return JSONResponse(fleet.snapshot())


@app.get("/control")
async def control_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "control.html")


@app.post("/api/command")
async def api_command(body: dict = Body(...)) -> JSONResponse:
    """Sends to the robots only when control.dry_run is false in robots.yaml."""
    result = await fleet.control.command(fleet.config, fleet.robots, fleet.keys, body)
    await fleet.broadcast()
    return JSONResponse(result)


@app.post("/api/scan")
async def api_scan() -> JSONResponse:
    asyncio.create_task(fleet.run_scan())
    return JSONResponse({"started": True})


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    fleet.clients.add(websocket)
    # Hold-to-move: the browser sends "hold" on press, "ping" while held, and
    # "release". The key repeats only while pings keep arriving (dead-man).
    hold: dict = {"token": None, "last": 0.0}

    async def run_hold(body: dict, token: object) -> None:
        try:
            await fleet.control.hold(
                fleet.config, fleet.robots, fleet.keys, body,
                lambda: hold["token"] is token and time.monotonic() - hold["last"] < HOLD_DEADMAN_S)
        finally:
            await fleet.broadcast()

    try:
        await websocket.send_text(json.dumps(fleet.snapshot()))
        while True:
            raw = await websocket.receive_text()
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            kind = m.get("type") if isinstance(m, dict) else None
            if kind == "hold":
                hold["token"], hold["last"] = object(), time.monotonic()
                asyncio.create_task(run_hold(m, hold["token"]))
            elif kind == "ping":
                hold["last"] = time.monotonic()
            elif kind == "release":
                hold["token"] = None
    except WebSocketDisconnect:
        pass
    finally:
        hold["token"] = None
        fleet.clients.discard(websocket)

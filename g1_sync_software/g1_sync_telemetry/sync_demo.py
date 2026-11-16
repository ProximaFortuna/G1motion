#!/usr/bin/env python3
"""G1 coordination prototype with optional tmux keyboard T trigger for SONIC.

Experimental. Local operator approval is required before arming.
"""
import argparse
import subprocess
import csv
import hashlib
import json
import os
from pathlib import Path
import secrets
import select
import socket
import threading
import time

VERSION = 1
FPS = 50.0
HB_INTERVAL = 0.1
HB_TIMEOUT = 0.6  # experimental; NOT a validated safety threshold
MAX_PACKET = 8192


def digest_dir(directory):
    root = Path(directory).resolve()
    if not root.is_dir():
        raise ValueError(f"Motion directory missing: {root}")
    files = sorted((p for p in root.rglob('*') if p.is_file()), key=lambda p: p.relative_to(root).as_posix())
    if not files:
        raise ValueError(f"Motion directory has no files: {root}")
    h = hashlib.sha256()
    for p in files:
        relative = p.relative_to(root).as_posix().encode()
        h.update(len(relative).to_bytes(4, 'big'))
        h.update(relative)
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b''):
                h.update(chunk)
    return h.hexdigest(), len(files)


def send(sock, obj, addr):
    sock.sendto(json.dumps(obj, separators=(',', ':')).encode(), addr)


def recv(sock, timeout):
    ready, _, _ = select.select([sock], [], [], max(0.0, timeout))
    if not ready:
        return None, None
    raw, addr = sock.recvfrom(MAX_PACKET)
    try:
        msg = json.loads(raw)
        if not isinstance(msg, dict) or msg.get('v') != VERSION:
            return None, addr
        return msg, addr
    except (ValueError, UnicodeDecodeError):
        return None, addr


class Agent:
    def __init__(self, name, bind, port, motion, frames, verbose=True, telemetry=None, sonic_session=None):
        self.name, self.bind, self.port, self.motion = name, bind, port, motion
        self.frames, self.verbose = frames, verbose
        self.digest, self.file_count = digest_dir(motion)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((bind, port))
        self.sock.setblocking(False)
        self.state = 'IDLE'
        self.session = None
        self.controller = None
        self.t0_unix = None
        self.start_monotonic = None
        self.last_hb = None
        self.next_report = 0.0
        self.started = False
        self.frame = 0
        self.stop_flag = False
        self.lost_hb_logged = False
        self.seen_commit = False
        self.last_status = None
        self.telemetry_path = telemetry
        self.telemetry_file = None
        self.telemetry_writer = None
        self.next_telemetry = 0.0
        self.sonic_session = sonic_session
        self.triggered = False
        self.ready_marker = Path.home() / ".g1_sync_operator_ready"

    def log(self, *args):
        if self.verbose:
            print(f'[{self.name}]', *args, flush=True)

    def reply(self, req, addr, kind, **extra):
        send(self.sock, dict(v=VERSION, type=kind, session=req.get('session'), robot=self.name,
                             state=self.state, **extra), addr)

    def sonic_ready(self):
        """Require manual authorization plus the actual SONIC process in our tmux pane.

        Do not rely on limited tmux scrollback.  Verify the running process,
        its terminal, and the isolated motion directory passed to SONIC.
        This is NOT a physical balance or actuator-state measurement.
        """
        if not self.sonic_session:
            return True
        try:
            if (not self.ready_marker.is_file() or
                    self.ready_marker.read_text().strip() != f'{self.name} {self.digest}'):
                return False
            pane_tty = subprocess.check_output(
                ['tmux', 'display-message', '-p', '-t', self.sonic_session, '#{pane_tty}'],
                text=True, timeout=1.0).strip()
            if not pane_tty.startswith('/dev/pts/'):
                return False
            pane_device = os.stat(pane_tty).st_rdev
            approved_motion = Path(self.motion).resolve(strict=True)
            if approved_motion.name != 'macarena_001__A545':
                return False
            found = []
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    pid = int(entry.name)
                    argv = (entry / 'cmdline').read_bytes().split(b'\x00')
                    argv = [x.decode('utf-8', errors='replace') for x in argv if x]
                    if len(argv) < 4 or Path(argv[0]).name != 'g1_deploy_onnx_ref':
                        continue
                    if '--input-type' not in argv or argv[argv.index('--input-type') + 1] != 'keyboard':
                        continue
                    cwd = (entry / 'cwd').resolve(strict=True)
                    motion_arg = Path(argv[3])
                    isolated_dir = (motion_arg if motion_arg.is_absolute() else cwd / motion_arg).resolve(strict=True)
                    if not isolated_dir.is_dir():
                        continue
                    motion_folders = [x for x in isolated_dir.iterdir() if x.is_dir()]
                    if len(motion_folders) != 1 or motion_folders[0].resolve(strict=True) != approved_motion:
                        continue
                    # The controlling terminal of this process must be this tmux pane.
                    stat = (entry / 'stat').read_text()
                    after_comm = stat.rsplit(')', 1)[1].split()
                    tty_nr = int(after_comm[4])  # /proc/pid/stat field 7
                    if tty_nr != pane_device:
                        continue
                    found.append(pid)
                except (OSError, ValueError, IndexError, PermissionError):
                    continue
            return len(found) == 1
        except (subprocess.SubprocessError, OSError, ValueError):
            return False

    def trigger_sonic(self):
        if self.triggered or not self.sonic_session:
            return
        # No automatic start of control. This sends ONLY the existing T key.
        subprocess.run(['tmux', 'send-keys', '-t', self.sonic_session,
                        '-l', 'T'], check=True, timeout=1.0)
        self.triggered = True
        self.ready_marker.unlink(missing_ok=True)
        self.log('SENT T to SONIC tmux session', self.sonic_session)

    def handle(self, m, addr):
        kind = m.get('type')
        sid = m.get('session')
        if kind == 'PREPARE':
            if not isinstance(sid, str) or len(sid) < 16:
                return
            if self.state not in ('IDLE', 'FINISHED', 'ABORTED') and sid != self.session:
                self.reply(m, addr, 'REJECT', reason='busy')
                return
            if not self.sonic_ready():
                self.reply(m, addr, 'REJECT', reason='SONIC not operator-authorized and verified ready')
                return
            if sid != self.session:
                self.session, self.controller = sid, addr
                self.state = 'PREPARED'
                self.started = False
                self.triggered = False
                self.frame = 0
                self.t0_unix = self.start_monotonic = self.last_hb = None
                self.seen_commit = False
                self.lost_hb_logged = False
                self.log('PREPARED', sid)
            if addr != self.controller:
                return
            self.reply(m, addr, 'READY', digest=self.digest, files=self.file_count,
                       frames=self.frames, fps=FPS)
            return

        if sid != self.session or addr != self.controller:
            return
        if kind == 'ARM' and self.state in ('PREPARED', 'ARMED'):
            t0 = m.get('t0')
            if not isinstance(t0, (int, float)) or not (2.0 <= t0-time.time() <= 30.0):
                self.reply(m, addr, 'REJECT', reason='start time not 2..30 seconds ahead')
                return
            if self.state == 'PREPARED':
                # Clock conversion only once. No wall-clock changes during playback.
                self.t0_unix = float(t0)
                self.start_monotonic = time.monotonic() + (self.t0_unix-time.time())
                self.state = 'ARMED'
                self.last_hb = time.monotonic()
                self.log('ARMED', f'T0={self.t0_unix:.3f}')
            if abs(float(t0)-self.t0_unix) > 1e-6:
                self.reply(m, addr, 'REJECT', reason='inconsistent T0')
                return
            self.reply(m, addr, 'ARMED_ACK', t0=self.t0_unix)
        elif kind == 'COMMIT' and self.state in ('ARMED', 'COMMITTED'):
            self.state = 'COMMITTED'
            self.seen_commit = True
            self.last_hb = time.monotonic()
            self.reply(m, addr, 'COMMITTED_ACK')
        elif kind == 'HEARTBEAT' and self.state in ('ARMED', 'COMMITTED', 'PLAYING_SYNCED', 'PLAYING_AUTONOMOUS'):
            self.last_hb = time.monotonic()
            self.reply(m, addr, 'STATUS', frame=self.frame)
        elif kind == 'ABORT' and self.state in ('PREPARED', 'ARMED', 'COMMITTED'):
            self.state = 'ABORTED'
            self.log('ABORTED before motion; no motor actions')
            self.reply(m, addr, 'ABORTED_ACK')
        elif kind == 'STATUS':
            self.reply(m, addr, 'STATUS', frame=self.frame, digest=self.digest)

    def tick(self):
        now = time.monotonic()
        if self.state in ('ARMED', 'COMMITTED'):
            # A communications failure BEFORE T0 must not launch the dance.
            if self.last_hb is None or now-self.last_hb > HB_TIMEOUT:
                self.state = 'ABORTED'
                self.log('prestart heartbeat timeout: DISARMED, no playback')
            elif now >= self.start_monotonic:
                if self.state != 'COMMITTED':
                    self.state = 'ABORTED'
                    self.log('no commit: DISARMED, no playback')
                else:
                    if self.sonic_session and not self.sonic_ready():
                        self.state = 'ABORTED'
                        self.log('SONIC readiness lost before start: DISARMED')
                        return
                    try:
                        self.trigger_sonic()
                    except (subprocess.SubprocessError, OSError) as exc:
                        self.state = 'ABORTED'
                        self.log('SONIC trigger failed:', exc)
                        return
                    self.state = 'PLAYING_SYNCED'
                    self.started = True
                    self.log('STARTED ' + ('SONIC keyboard-triggered' if self.sonic_session else 'mock') + ' playback')
        if self.state in ('PLAYING_SYNCED', 'PLAYING_AUTONOMOUS'):
            if (self.state == 'PLAYING_SYNCED' and self.last_hb is not None
                    and now-self.last_hb > HB_TIMEOUT):
                self.state = 'PLAYING_AUTONOMOUS'
                self.log('heartbeat missing: CONTINUING playback on monotonic timeline')
            # No jumps on reconnect: same monotonic timeline in both PLAYING states.
            elapsed = max(0.0, now-self.start_monotonic)
            self.frame = min(self.frames-1, int(elapsed*FPS))
            if self.verbose and now >= self.next_report:
                self.log(self.state, 'mock frame', self.frame)
                self.next_report = now + 1.0
            if self.frame >= self.frames-1:
                self.state = 'FINISHED'
                self.log('FINISHED timeline; SONIC continues independently' if self.sonic_session else 'FINISHED mock playback; no motor behavior implemented')

    def record_telemetry(self, now):
        if self.telemetry_writer is None or now < self.next_telemetry:
            return
        self.next_telemetry = now + 0.1
        # Time fields are sampled back-to-back. Unix time is NTP-disciplined,
        # monotonic elapsed time preserves a smooth local playback phase.
        self.telemetry_writer.writerow([self.name, self.session or '',
            f'{time.time():.9f}', f'{now:.9f}',
            f'{(now-self.start_monotonic):.9f}' if self.start_monotonic is not None else '',
            self.frame, self.state, f'{self.t0_unix:.9f}' if self.t0_unix is not None else ''])
        self.telemetry_file.flush()

    def run(self):
        self.log(f'listening on {self.bind}:{self.port}, motion_sha256={self.digest}, files={self.file_count}')
        if self.telemetry_path:
            self.telemetry_file = open(self.telemetry_path, 'w', newline='', buffering=1)
            self.telemetry_writer = csv.writer(self.telemetry_file)
            self.telemetry_writer.writerow(['robot','session','unix_s','monotonic_s','elapsed_s','frame','state','t0_unix_s'])
        try:
            while not self.stop_flag:
                m, addr = recv(self.sock, 0.01)
                if m is not None:
                    self.handle(m, addr)
                self.tick()
                self.record_telemetry(time.monotonic())
        finally:
            self.sock.close()
            if self.telemetry_file:
                self.telemetry_file.close()


def parse_endpoint(spec):
    host, sep, port = spec.rpartition(':')
    if not sep:
        raise ValueError(f'Expected HOST:PORT: {spec}')
    return (host, int(port))


class Coordinator:
    def __init__(self, endpoints, lead, duration, drop_after=None, quiet=False):
        self.endpoints = [parse_endpoint(x) for x in endpoints]
        if len(self.endpoints) != 2 or len(set(self.endpoints)) != 2:
            raise ValueError('Must provide two distinct agent endpoints')
        self.lead, self.duration = lead, duration
        self.drop_after, self.quiet = drop_after, quiet
        self.session = secrets.token_hex(16)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('0.0.0.0', 0))
        self.sock.setblocking(False)

    def log(self, *args):
        if not self.quiet:
            print('[coordinator]', *args, flush=True)

    def broadcast(self, kind, **args):
        msg = dict(v=VERSION, type=kind, session=self.session, **args)
        for addr in self.endpoints:
            send(self.sock, msg, addr)

    def collect(self, expected, seconds, **args):
        seen = {}
        deadline = time.monotonic() + seconds
        next_send = 0.0
        while time.monotonic() < deadline and len(seen) < len(self.endpoints):
            if time.monotonic() >= next_send:
                for addr in self.endpoints:
                    if addr not in seen:
                        send(self.sock, dict(v=VERSION, type=args['request'], session=self.session,
                                             **args.get('payload', {})), addr)
                next_send = time.monotonic() + 0.15
            m, addr = recv(self.sock, 0.025)
            if m and addr in self.endpoints and m.get('session') == self.session:
                if m.get('type') == 'REJECT':
                    raise RuntimeError(f'{addr} rejected: {m.get("reason")}')
                if m.get('type') == expected:
                    seen[addr] = m
        if len(seen) < len(self.endpoints):
            raise TimeoutError(f'{args["request"]}: missing {expected} from {set(self.endpoints)-set(seen)}')
        return seen

    def run(self):
        try:
            self.log('session', self.session, 'agents', self.endpoints)
            ready = self.collect('READY', 4.0, request='PREPARE')
            manifests = {(x['digest'], x['files'], x['frames'], x['fps']) for x in ready.values()}
            if len(manifests) != 1:
                raise RuntimeError(f'MOTION MISMATCH: {[(a, m["digest"], m["frames"]) for a,m in ready.items()]}')
            digest, _, frames, fps = next(iter(manifests))
            self.log('verified matching manifest', digest, f'{frames} frames at {fps} Hz')
            t0 = time.time()+self.lead
            self.collect('ARMED_ACK', 4.0, request='ARM', payload={'t0': t0})
            self.log('both ARMED for', f'{t0:.3f}')
            self.collect('COMMITTED_ACK', 3.0, request='COMMIT')
            self.log('both COMMITTED. Local agents will execute at T0.')
            start = time.monotonic()
            next_hb = 0
            last_print = 0
            while time.monotonic()-start < self.lead+self.duration:
                now = time.monotonic()
                elapsed = now-start
                if self.drop_after is not None and elapsed >= self.drop_after:
                    self.log('SIMULATING COORDINATOR LOSS. No more heartbeats.')
                    break
                if now >= next_hb:
                    self.broadcast('HEARTBEAT')
                    next_hb = now+HB_INTERVAL
                m, addr = recv(self.sock, 0.025)
                if m and m.get('session') == self.session and m.get('type') == 'STATUS':
                    if now-last_print > 1.0:
                        self.log('status', m.get('robot'), m.get('state'), 'frame', m.get('frame'))
                        last_print = now
            self.log('coordinator finished; agents remain independent')
            return True
        except Exception as exc:
            self.log('ERROR:', exc)
            self.log('sending ABORT; only affects agents before playback starts')
            for _ in range(4):
                self.broadcast('ABORT')
                time.sleep(0.05)
            return False
        finally:
            self.sock.close()


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        roots = [Path(d)/x for x in ('a', 'b')]
        for p in roots:
            p.mkdir()
            (p/'joint_pos.csv').write_text('0,1,2\n3,4,5\n')
        a = Agent('G1', '127.0.0.1', 19341, str(roots[0]), 150, verbose=False)
        b = Agent('Lugan', '127.0.0.1', 19342, str(roots[1]), 150, verbose=False)
        threads = [threading.Thread(target=x.run, daemon=True) for x in (a,b)]
        for t in threads: t.start()
        time.sleep(0.05)
        c = Coordinator(['127.0.0.1:19341', '127.0.0.1:19342'], 2.5, 0.5,
                        drop_after=3.0, quiet=True)
        assert c.run(), 'Expected coordination success'
        time.sleep(1.0)
        assert a.state == b.state == 'PLAYING_AUTONOMOUS', (a.state,b.state)
        assert a.frame > 0 and b.frame > 0
        print('PASS: matching hash, start, coordinator loss -> continued playback')
        time.sleep(2.0)
        assert a.state == b.state == 'FINISHED', (a.state,b.state)
        print('PASS: autonomous completion without shutdown')
        # A committed start must expire if the coordinator disappears BEFORE T0.
        c_pre = Coordinator(['127.0.0.1:19341', '127.0.0.1:19342'], 2.5, 0.1,
                            drop_after=0.5, quiet=True)
        assert c_pre.run(), 'Expected commit before simulated loss'
        time.sleep(3.0)
        assert a.state == b.state == 'ABORTED', (a.state, b.state)
        print('PASS: prestart heartbeat loss -> disarmed without playback')
        (roots[1]/'joint_pos.csv').write_text('different trajectory\n')
        b.digest, b.file_count = digest_dir(roots[1])
        c2 = Coordinator(['127.0.0.1:19341', '127.0.0.1:19342'], 2.5, 0.1, quiet=True)
        assert not c2.run(), 'Mismatched motion must be rejected'
        print('PASS: mismatch rejects arming')
        for x in (a,b): x.stop_flag = True
        for t in threads: t.join(timeout=1.0)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='mode', required=True)
    agent = sub.add_parser('agent')
    agent.add_argument('--name', required=True)
    agent.add_argument('--bind', default='0.0.0.0')
    agent.add_argument('--port', type=int, default=19041)
    agent.add_argument('--motion', required=True)
    agent.add_argument('--frames', type=int, default=1375)
    agent.add_argument('--telemetry', help='Write local 10 Hz CSV')
    agent.add_argument('--sonic-session', help='EXPERIMENTAL: send T once to this verified tmux session')
    coord = sub.add_parser('coordinator')
    coord.add_argument('--robots', nargs=2, required=True, metavar='HOST:PORT')
    coord.add_argument('--lead', type=float, default=6.0)
    coord.add_argument('--duration', type=float, default=30.0)
    coord.add_argument('--drop-after', type=float, default=None,
                       help='Simulate coordinator disappearing N seconds after PREPARE')
    sub.add_parser('selftest')
    args = p.parse_args()
    if args.mode == 'agent':
        if args.frames <= 0: p.error('--frames must be positive')
        Agent(args.name, args.bind, args.port, args.motion, args.frames, telemetry=args.telemetry, sonic_session=args.sonic_session).run()
    elif args.mode == 'coordinator':
        if args.lead < 5 or args.lead > 30:
            p.error('--lead must be 5..30 seconds for protocol margin')
        if args.duration <= 0: p.error('--duration must be positive')
        raise SystemExit(0 if Coordinator(args.robots,args.lead,args.duration,args.drop_after).run() else 1)
    else:
        selftest()


if __name__ == '__main__':
    main()

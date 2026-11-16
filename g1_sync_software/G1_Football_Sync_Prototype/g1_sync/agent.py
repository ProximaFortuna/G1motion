#!/usr/bin/env python3
"""Software-only synchronized timeline agent. No actuator/SONIC access."""
import argparse
import json
import socketserver
import threading
import time

TICK_HZ = 50.0


class State:
    def __init__(self, name):
        self.name = name
        self.lock = threading.RLock()
        self.offset_ns = None  # coordinator wall clock minus this agent's wall clock
        self.last_sync_mono = None
        self.rtt_ns = None
        self.motion = None
        self.start_coord_ns = None
        self.duration_ns = None
        self.ready = False
        self.started = False
        self.finished = False
        self.last_frame = -1
        self.first_tick_coord_ns = None
        self.running = True

    def coordinator_now_ns(self):
        return time.time_ns() + (self.offset_ns or 0)

    def timeline(self):
        with self.lock:
            if self.start_coord_ns is None or self.offset_ns is None:
                return {'status': 'IDLE' if self.start_coord_ns is None else 'UNSYNCED'}
            delta = self.coordinator_now_ns() - self.start_coord_ns
            phase = max(0.0, min(1.0, delta / self.duration_ns))
            return {'status': 'FINISHED' if self.finished else ('RUNNING' if delta >= 0 else 'ARMED'),
                    'motion': self.motion, 'phase': round(phase, 6),
                    'frame': max(0, int(delta * TICK_HZ / 1e9)),
                    'start_coord_ns': self.start_coord_ns,
                    'first_tick_coord_ns': self.first_tick_coord_ns}


def tick_worker(state):
    period = 1 / TICK_HZ
    deadline = time.monotonic()
    while state.running:
        deadline += period
        with state.lock:
            if state.ready and state.start_coord_ns is not None and state.offset_ns is not None:
                delta_ns = state.coordinator_now_ns() - state.start_coord_ns
                if delta_ns >= 0 and not state.finished:
                    frame = int(delta_ns * TICK_HZ / 1e9)
                    if not state.started:
                        state.started = True
                        state.first_tick_coord_ns = state.coordinator_now_ns()
                        print(f'[{state.name}] START motion={state.motion} start_error_ms='
                              f'{(state.first_tick_coord_ns-state.start_coord_ns)/1e6:.3f}', flush=True)
                    if frame != state.last_frame:
                        state.last_frame = frame
                        if frame % 50 == 0:
                            print(f'[{state.name}] phase={min(1, delta_ns/state.duration_ns):.3f} frame={frame}', flush=True)
                    if delta_ns >= state.duration_ns:
                        state.finished = True
                        print(f'[{state.name}] FINISHED', flush=True)
        time.sleep(max(0, deadline - time.monotonic()))
        if time.monotonic() - deadline > period * 5:
            deadline = time.monotonic()


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        state = self.server.state
        self.request.settimeout(4)
        for raw in self.rfile:
            try:
                msg = json.loads(raw)
                cmd = msg.get('cmd')
                if cmd == 'PROBE':
                    t1 = time.time_ns()
                    t2 = time.time_ns()
                    ans = {'ok': True, 't1': t1, 't2': t2}
                elif cmd == 'SYNC':
                    raw_offset = int(msg['offset_ns'])
                    rtt = int(msg['rtt_ns'])
                    if rtt > 30_000_000:
                        raise ValueError('RTT exceeds 30 ms sync sample threshold')
                    with state.lock:
                        # Low-pass correction: avoid sudden phase jumps. Limit each correction to 1 ms.
                        if state.offset_ns is None:
                            state.offset_ns = raw_offset
                        else:
                            delta = raw_offset - state.offset_ns
                            state.offset_ns += max(-1_000_000, min(1_000_000, round(delta * .25)))
                        state.last_sync_mono = time.monotonic()
                        state.rtt_ns = rtt
                    ans = {'ok': True, 'offset_ns': state.offset_ns}
                elif cmd == 'PREPARE':
                    motion = str(msg['motion'])
                    duration = float(msg['duration_s'])
                    if not (0.1 <= duration <= 600):
                        raise ValueError('duration_s must be 0.1 to 600')
                    with state.lock:
                        if state.started and not state.finished:
                            raise ValueError('existing mission is active')
                        state.motion = motion
                        state.duration_ns = round(duration * 1e9)
                        state.start_coord_ns = None
                        state.started = False
                        state.finished = False
                        state.ready = True
                        state.last_frame = -1
                        state.first_tick_coord_ns = None
                    ans = {'ok': True, 'status': 'READY', 'simulation_only': True}
                elif cmd == 'START_AT':
                    t0 = int(msg['start_coord_ns'])
                    with state.lock:
                        if not state.ready or state.offset_ns is None:
                            raise ValueError('not prepared or not synchronized')
                        if state.last_sync_mono is None or time.monotonic()-state.last_sync_mono > 5:
                            raise ValueError('clock sync is stale')
                        if t0 - state.coordinator_now_ns() < 2_000_000_000:
                            raise ValueError('start time must be >= 2 seconds ahead')
                        state.start_coord_ns = t0
                    ans = {'ok': True, 'status': 'ARMED'}
                elif cmd == 'STATUS':
                    ans = {'ok': True, **state.timeline()}
                    with state.lock:
                        ans['sync_age_s'] = (round(time.monotonic() - state.last_sync_mono, 3)
                                             if state.last_sync_mono else None)
                        ans['rtt_ms'] = state.rtt_ns / 1e6 if state.rtt_ns is not None else None
                elif cmd == 'CANCEL':
                    with state.lock:
                        if state.started and not state.finished:
                            raise ValueError('cannot cancel active timeline; hardware stop not implemented')
                        state.ready = False
                        state.start_coord_ns = None
                    ans = {'ok': True}
                else:
                    raise ValueError('unknown command')
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                ans = {'ok': False, 'error': str(exc)}
            self.wfile.write((json.dumps(ans) + '\n').encode())
            self.wfile.flush()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True)
    ap.add_argument('--bind', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=8765)
    args = ap.parse_args()
    state = State(args.name)
    threading.Thread(target=tick_worker, args=(state,), daemon=True).start()
    with Server((args.bind, args.port), Handler) as server:
        server.state = state
        print(f'[{state.name}] simulation-only agent listening on {args.bind}:{args.port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            state.running = False


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""G1 dual-robot sync V2 agent. SOFTWARE-ONLY: no SONIC or motor access."""
import argparse
import csv
import json
import math
import os
import socketserver
import threading
import time

HZ = 50
PERIOD_NS = 1_000_000_000 // HZ

class State:
    def __init__(self, name, logdir):
        self.name, self.logdir = name, logdir
        self.lock = threading.RLock()
        self.offset_ns = None            # coordinator monotonic - agent monotonic
        self.target_offset_ns = None
        self.sync_mono_ns = None
        self.rtt_ns = None
        self.motion = None
        self.duration_ns = None
        self.start_coord_ns = None
        self.started = False
        self.finished = False
        self.first_tick_coord_ns = None
        self.last_sample = None
        self.missed_ticks = 0
        self.mission_id = None
        self.writer = None
        self.csvfile = None
        self.next_tick = time.monotonic_ns() + PERIOD_NS

    def now_coord(self, now_mono=None):
        now_mono = time.monotonic_ns() if now_mono is None else now_mono
        return now_mono + (self.offset_ns or 0)

    def phase(self, now_mono=None):
        now_mono = time.monotonic_ns() if now_mono is None else now_mono
        if self.start_coord_ns is None or self.duration_ns is None:
            return 'IDLE', 0, 0.0, 0
        elapsed = self.now_coord(now_mono) - self.start_coord_ns
        frame = max(0, min(int(self.duration_ns / PERIOD_NS), int(elapsed / PERIOD_NS)))
        fraction = max(0., min(1., elapsed / self.duration_ns))
        status = 'FINISHED' if self.finished else ('RUNNING' if self.started else 'ARMED')
        return status, frame, fraction, elapsed

    def close_log(self):
        if self.csvfile is not None:
            self.csvfile.flush()
            self.csvfile.close()
            self.csvfile = None
            self.writer = None

    def open_log(self):
        self.close_log()
        os.makedirs(self.logdir, exist_ok=True)
        path = os.path.join(self.logdir, f'{self.name}_{self.mission_id}.csv')
        self.csvfile = open(path, 'w', newline='', buffering=1)
        self.writer = csv.writer(self.csvfile)
        self.writer.writerow(['agent_monotonic_ns','estimated_coordinator_monotonic_ns',
                              'elapsed_ns','frame','phase','applied_offset_ns',
                              'target_offset_ns','rtt_ns','sync_age_ms','tick_late_us','missed_ticks'])
        return path


def worker(st):
    while True:
        now = time.monotonic_ns()
        wait = st.next_tick - now
        if wait > 0:
            time.sleep(wait / 1e9)
        now = time.monotonic_ns()
        late = max(0, now - st.next_tick)
        st.next_tick += PERIOD_NS
        if late > PERIOD_NS:
            skipped = late // PERIOD_NS
            st.next_tick += skipped * PERIOD_NS
            with st.lock:
                st.missed_ticks += skipped
        with st.lock:
            # Slew by at most 50 microseconds per 20-ms period, no abrupt phase jump.
            if st.offset_ns is not None and st.target_offset_ns is not None:
                error = st.target_offset_ns - st.offset_ns
                st.offset_ns += max(-50_000, min(50_000, error))
            if st.start_coord_ns is None:
                continue
            status, frame, phase, elapsed = st.phase(now)
            if elapsed >= 0 and not st.started:
                st.started = True
                st.first_tick_coord_ns = st.now_coord(now)
                print(f'[{st.name}] START estimated_delay_ms='
                      f'{(st.first_tick_coord_ns-st.start_coord_ns)/1e6:.3f}', flush=True)
            if st.started and not st.finished:
                age = (now - st.sync_mono_ns)/1e6 if st.sync_mono_ns else float('inf')
                st.writer.writerow([now, st.now_coord(now), elapsed, frame,
                                    round(phase, 8), st.offset_ns, st.target_offset_ns,
                                    st.rtt_ns, round(age, 3), round(late/1e3, 3), st.missed_ticks])
                st.last_sample = {'mono_ns': now, 'coord_ns': st.now_coord(now),
                                  'elapsed_ns': elapsed, 'frame': frame}
                if elapsed >= st.duration_ns:
                    st.finished = True
                    st.close_log()
                    print(f'[{st.name}] FINISHED frame={frame} missed_ticks={st.missed_ticks}', flush=True)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(6)
        for line in self.rfile:
            try:
                msg = json.loads(line)
                cmd = msg.get('cmd')
                st = self.server.st
                if cmd == 'PROBE':
                    a = time.monotonic_ns()
                    b = time.monotonic_ns()
                    out = {'ok': True, 't1': a, 't2': b}
                elif cmd == 'SYNC':
                    off, rtt = int(msg['offset_ns']), int(msg['rtt_ns'])
                    if rtt < 0 or rtt > 30_000_000:
                        raise ValueError('Unreliable RTT; sample rejected')
                    with st.lock:
                        if st.offset_ns is None:
                            st.offset_ns = off
                        st.target_offset_ns = off
                        st.rtt_ns = rtt
                        st.sync_mono_ns = time.monotonic_ns()
                        out = {'ok': True, 'applied_offset_ns': st.offset_ns}
                elif cmd == 'PREPARE':
                    dur = float(msg['duration_s'])
                    if not math.isfinite(dur) or not (1 <= dur <= 600):
                        raise ValueError('duration must be 1-600 seconds')
                    with st.lock:
                        if st.started and not st.finished:
                            raise ValueError('Mission in progress')
                        if st.offset_ns is None:
                            raise ValueError('First synchronize clocks')
                        st.close_log()
                        st.motion = str(msg['motion'])
                        st.duration_ns = int(dur*1e9)
                        st.mission_id = str(msg['mission_id'])
                        if not st.mission_id.isalnum():
                            raise ValueError('mission_id must be alphanumeric')
                        st.start_coord_ns = None
                        st.started = st.finished = False
                        st.first_tick_coord_ns = None
                        st.last_sample = None
                        st.missed_ticks = 0
                        out = {'ok': True, 'status': 'READY', 'simulation_only': True}
                elif cmd == 'START_AT':
                    t0 = int(msg['start_coord_ns'])
                    with st.lock:
                        if st.motion is None or st.started or st.start_coord_ns is not None:
                            raise ValueError('Not ready for a new start')
                        if st.sync_mono_ns is None or time.monotonic_ns()-st.sync_mono_ns > 3e9:
                            raise ValueError('Clock synchronization stale')
                        if t0 - st.now_coord() < 2_000_000_000:
                            raise ValueError('Start must be at least 2 s ahead')
                        path = st.open_log()
                        st.start_coord_ns = t0
                        out = {'ok': True, 'status': 'ARMED', 'csv_path': path}
                elif cmd == 'STATUS':
                    with st.lock:
                        status, frame, phase, elapsed = st.phase()
                        out = {'ok': True, 'status': status, 'frame': frame, 'phase': phase,
                               'first_tick_coord_ns': st.first_tick_coord_ns,
                               'offset_ns': st.offset_ns, 'target_offset_ns': st.target_offset_ns,
                               'sync_age_s': None if st.sync_mono_ns is None else
                               round((time.monotonic_ns()-st.sync_mono_ns)/1e9,3),
                               'rtt_ms': None if st.rtt_ns is None else round(st.rtt_ns/1e6,3),
                               'missed_ticks': st.missed_ticks, 'last_sample': st.last_sample}
                elif cmd == 'CANCEL':
                    with st.lock:
                        if st.started and not st.finished:
                            raise ValueError('Cannot cancel active simulation')
                        st.start_coord_ns = None
                        st.close_log()
                        out = {'ok': True}
                else:
                    raise ValueError('Unknown command')
            except (KeyError, ValueError, TypeError, json.JSONDecodeError) as e:
                out = {'ok': False, 'error': str(e)}
            self.wfile.write((json.dumps(out)+'\n').encode())
            self.wfile.flush()

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', required=True)
    ap.add_argument('--bind', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--logdir', default='/home/unitree/g1_sync_logs')
    args = ap.parse_args()
    st = State(args.name, args.logdir)
    threading.Thread(target=worker, args=(st,), daemon=True).start()
    with Server((args.bind, args.port), Handler) as server:
        server.st = st
        print(f'[{args.name}] SOFTWARE ONLY listening on {args.bind}:{args.port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            with st.lock:
                st.close_log()

#!/usr/bin/env python3
"""Aurelius demo coordinator. Software-only, no physical motion commands."""
import argparse
import json
import socket
import threading
import time


def rpc(host, msg, timeout=3):
    with socket.create_connection((host, 8765), timeout=timeout) as s:
        s.settimeout(timeout)
        f = s.makefile('rwb')
        f.write((json.dumps(msg) + '\n').encode())
        f.flush()
        line = f.readline()
        if not line:
            raise RuntimeError(f'{host}: no response')
        reply = json.loads(line)
        if not reply.get('ok'):
            raise RuntimeError(f'{host}: {reply.get("error")}')
        return reply


def sync(host, tries=8):
    samples = []
    for _ in range(tries):
        t0 = time.time_ns()
        reply = rpc(host, {'cmd': 'PROBE'})
        t3 = time.time_ns()
        # Offset (coordinator time - agent time), NTP-style four timestamp estimate.
        offset = round(((t0 - reply['t1']) + (t3 - reply['t2'])) / 2)
        rtt = (t3 - t0) - (reply['t2'] - reply['t1'])
        samples.append((rtt, offset))
        time.sleep(0.035)
    rtt, offset = min(samples)
    rpc(host, {'cmd': 'SYNC', 'offset_ns': offset, 'rtt_ns': rtt})
    return rtt / 1e6, offset / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--g1', default='192.168.0.8')
    ap.add_argument('--lugan', default='192.168.0.42')
    ap.add_argument('--motion', default='J_Dance2_Salsa')
    ap.add_argument('--duration', type=float, default=20)
    ap.add_argument('--start-delay', type=float, default=8)
    args = ap.parse_args()
    hosts = {'G1': args.g1, 'Lugan': args.lugan}
    if args.start_delay < 5:
        ap.error('--start-delay must be at least 5 seconds')
    print('SOFTWARE SIMULATION ONLY. No SONIC controls or motor commands.')
    for name, host in hosts.items():
        rtt, offset = sync(host)
        print(f'{name}: best RTT={rtt:.2f} ms, offset estimate={offset:+.2f} ms')
    for name, host in hosts.items():
        print(f'{name}:', rpc(host, {'cmd': 'PREPARE', 'motion': args.motion, 'duration_s': args.duration}))
    t0 = time.time_ns() + int(args.start_delay * 1e9)
    armed = []
    try:
        for name, host in hosts.items():
            print(f'{name}:', rpc(host, {'cmd': 'START_AT', 'start_coord_ns': t0}))
            armed.append(host)
    except Exception:
        for host in armed:
            try:
                rpc(host, {'cmd': 'CANCEL'})
            except Exception:
                pass
        raise
    stop = threading.Event()

    def resync_loop():
        while not stop.wait(1):
            for name, host in hosts.items():
                try:
                    rtt, offset = sync(host, tries=4)
                    if rtt > 15:
                        print(f'WARNING {name}: high RTT {rtt:.1f} ms')
                except Exception as exc:
                    print(f'WARNING {name}: sync failed: {exc}')

    worker = threading.Thread(target=resync_loop, daemon=True)
    worker.start()
    print('Scheduled T0:', t0, 'coordinator UNIX epoch ns')
    try:
        while True:
            statuses = {name: rpc(host, {'cmd': 'STATUS'}) for name, host in hosts.items()}
            print(' | '.join(f'{name}: {s["status"]} phase={s.get("phase")} frame={s.get("frame")}'
                             for name, s in statuses.items()))
            if all(s['status'] == 'FINISHED' for s in statuses.values()):
                errors = {name: (s['first_tick_coord_ns'] - t0) / 1e6
                          for name, s in statuses.items()}
                print('Software first-tick delay vs scheduled T0 (ms):', errors)
                print('Observed first-tick skew (ms):', abs(errors['G1']-errors['Lugan']))
                print('Not a measurement of physical robot motion synchronization.')
                break
            time.sleep(1)
    finally:
        stop.set()
        worker.join(timeout=2)


if __name__ == '__main__':
    main()

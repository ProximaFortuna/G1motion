#!/usr/bin/env python3
"""Aurelius coordinator for G1 sync V2. SOFTWARE ONLY."""
import argparse
import csv
import json
import os
import socket
import threading
import time
from datetime import datetime

PORT = 8765

def rpc(host, message, timeout=4):
    with socket.create_connection((host, PORT), timeout=timeout) as s:
        s.settimeout(timeout)
        f = s.makefile('rwb')
        f.write((json.dumps(message)+'\n').encode())
        f.flush()
        reply = json.loads(f.readline())
        if not reply.get('ok'):
            raise RuntimeError(f'{host}: {reply.get("error")}')
        return reply

def synchronize(host, tries=8):
    samples = []
    for _ in range(tries):
        t0 = time.monotonic_ns()
        response = rpc(host, {'cmd':'PROBE'})
        t3 = time.monotonic_ns()
        t1, t2 = response['t1'], response['t2']
        rtt = (t3-t0)-(t2-t1)
        offset = round(((t0-t1)+(t3-t2))/2)
        if rtt >= 0:
            samples.append((rtt, offset))
        time.sleep(0.025)
    if not samples:
        raise RuntimeError(f'{host}: no valid clock samples')
    rtt, offset = min(samples)
    rpc(host, {'cmd':'SYNC','offset_ns':offset,'rtt_ns':rtt})
    return rtt/1e6, offset/1e6

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--g1', default='192.168.0.8')
    p.add_argument('--lugan', default='192.168.0.42')
    p.add_argument('--motion', default='J_Dance2_Salsa')
    p.add_argument('--duration', type=float, default=60)
    p.add_argument('--start-delay', type=float, default=10)
    p.add_argument('--logdir', default='logs')
    args = p.parse_args()
    if args.start_delay < 8:
        p.error('--start-delay must be >= 8 seconds')
    hosts = {'G1':args.g1, 'Lugan':args.lugan}
    mission_id = datetime.now().strftime('%Y%m%d%H%M%S')
    os.makedirs(args.logdir,exist_ok=True)
    print('SOFTWARE SIMULATION ONLY. No SONIC or motor commands.')
    print('Mission:',mission_id,flush=True)
    for name, host in hosts.items():
        rtt, offset = synchronize(host)
        print(f'{name}: RTT={rtt:.3f}ms estimated_offset={offset:+.3f}ms',flush=True)
    for name, host in hosts.items():
        print(f'{name}:',rpc(host,{'cmd':'PREPARE','motion':args.motion,
                                'duration_s':args.duration,'mission_id':mission_id}),flush=True)
    # Re-sync just before arming, then pick a common future monotonic T0.
    for host in hosts.values():
        synchronize(host, tries=4)
    t0 = time.monotonic_ns()+round(args.start_delay*1e9)
    armed=[]
    try:
        for name,host in hosts.items():
            print(name,rpc(host,{'cmd':'START_AT','start_coord_ns':t0}),flush=True)
            armed.append(host)
    except Exception:
        for host in armed:
            try: rpc(host,{'cmd':'CANCEL'})
            except Exception: pass
        raise
    stop=threading.Event()
    def background():
        while not stop.wait(0.75):
            for name,host in hosts.items():
                try:
                    rtt, offset = synchronize(host, tries=3)
                    if rtt>15:
                        print(f'WARNING {name}: RTT {rtt:.2f}ms',flush=True)
                except Exception as exc:
                    print(f'WARNING {name}: clock update failed: {exc}',flush=True)
    th=threading.Thread(target=background,daemon=True)
    th.start()
    path=os.path.join(args.logdir,mission_id+'_coordinator.csv')
    records=[]
    try:
        while True:
            row={'coordinator_mono_ns':time.monotonic_ns()}
            complete=True
            for name,host in hosts.items():
                try:
                    s=rpc(host,{'cmd':'STATUS'})
                    row[name]=s
                    if s['status']!='FINISHED':complete=False
                except Exception as exc:
                    row[name]={'status':'ERROR','error':str(exc)}
                    complete=False
            records.append(row)
            a,b=row['G1'],row['Lugan']
            print(f"G1 {a['status']} frame={a.get('frame')} | "
                  f"Lugan {b['status']} frame={b.get('frame')}",flush=True)
            if complete:break
            time.sleep(1)
    except KeyboardInterrupt:
        print('Coordinator interrupted. Agents may continue simulated timeline.',flush=True)
    finally:
        stop.set()
        th.join(timeout=3)
        with open(path,'w',newline='') as f:
            w=csv.writer(f)
            w.writerow(['coordinator_monotonic_ns','robot','status','frame','phase',
                        'estimated_offset_ns','target_offset_ns','sync_age_s','rtt_ms',
                        'missed_ticks','last_sample_coord_ns','last_sample_elapsed_ns'])
            for row in records:
                for name in hosts:
                    s=row[name]
                    last=s.get('last_sample') or {}
                    w.writerow([row['coordinator_mono_ns'],name,s.get('status'),s.get('frame'),
                                s.get('phase'),s.get('offset_ns'),s.get('target_offset_ns'),
                                s.get('sync_age_s'),s.get('rtt_ms'),s.get('missed_ticks'),
                                last.get('coord_ns'),last.get('elapsed_ns')])
        print('Coordinator CSV:',path)
        first={name: next((r[name].get('first_tick_coord_ns') for r in reversed(records)
                          if r[name].get('first_tick_coord_ns') is not None),None)
               for name in hosts}
        print('Estimated first-tick timing vs scheduled T0 (ms):',
              {name: None if ts is None else round((ts-t0)/1e6,3) for name,ts in first.items()})
        if all(ts is not None for ts in first.values()):
            print('Estimated first-tick skew (ms):',round(abs(first['G1']-first['Lugan'])/1e6,3))
        print('Note: NOT independently measured cross-robot skew or physical synchronization.')

if __name__=='__main__':
    main()

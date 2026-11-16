#!/usr/bin/env python3
"""Compare timestamped local agent timelines; read-only, dry-run only.

NTP wall-clock uncertainty bounds real relative physical sync; this tool
measures estimated frame phase, NOT motor motion or guaranteed clock accuracy.
"""
import argparse
import csv
import statistics
from pathlib import Path

FPS = 50.0

def read(path):
    with open(path, newline='') as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r['state'] in ('PLAYING_SYNCED','PLAYING_AUTONOMOUS')
            and r['elapsed_s']]

def main():
    p = argparse.ArgumentParser()
    p.add_argument('g1_csv')
    p.add_argument('lugan_csv')
    a = p.parse_args()
    g, l = read(a.g1_csv), read(a.lugan_csv)
    if not g or not l:
        p.error('Need PLAYING_SYNCED/PLAYING_AUTONOMOUS samples from both robots')
    sessions_g = {r['session'] for r in g}
    sessions_l = {r['session'] for r in l}
    shared = sessions_g & sessions_l
    if len(shared) != 1:
        p.error(f'Expected one matching session; shared={shared}')
    sid = next(iter(shared))
    g = [r for r in g if r['session'] == sid]
    l = [r for r in l if r['session'] == sid]
    # Estimate effective shared-start epochs using independently sampled wall time
    # minus monotonic playback elapsed. This avoids pairing unsynchronized log lines.
    # For each Lugan sample, compare to the G1 sample closest in wall time.
    gs = sorted((float(r['unix_s']), float(r['elapsed_s']), int(r['frame'])) for r in g)
    ls = sorted((float(r['unix_s']), float(r['elapsed_s']), int(r['frame'])) for r in l)
    pairs = []
    i = 0
    for tl, el, fl in ls:
        while i+1 < len(gs) and abs(gs[i+1][0]-tl) < abs(gs[i][0]-tl):
            i += 1
        tg, eg, fg = gs[i]
        if abs(tl-tg) > 0.15:
            continue
        # Evaluate G1's expected continuous phase at Lugan's timestamp,
        # using its own monotonic-derived phase and their wall-clock mapping.
        diff_ms = 1000.0*(el-(eg+(tl-tg)))
        pairs.append(diff_ms)
    if len(pairs) < 5:
        p.error(f'Insufficient near-time samples: {len(pairs)}')
    abs_errors = sorted(abs(x) for x in pairs)
    def pct(v):
        return abs_errors[min(len(abs_errors)-1, int((len(abs_errors)-1)*v))]
    print('Session:', sid)
    print('Paired samples:', len(pairs))
    print('Mean signed timeline difference (Lugan minus G1): %.3f ms' % statistics.mean(pairs))
    print('Median absolute difference: %.3f ms' % statistics.median(abs_errors))
    print('95th percentile absolute difference: %.3f ms' % pct(.95))
    print('Maximum absolute difference: %.3f ms' % max(abs_errors))
    print('NOTE: Estimates depend on NTP clock alignment and wall-clock stability.')
    print('NOTE: These numbers describe software phases, not observed physical motion.')

if __name__ == '__main__':
    main()

import pickle
from pathlib import Path

import numpy as np

EVENTS = {
    "B_LongDance": [13.98, 18.34],
    "J_Dance2_Salsa": [12.62, 32.32],
    "J_Dance4_Broadway": [4.94, 20.80],
    "J_Dance8_WestCoast": [15.56, 16.74, 34.02],
    "J_Dance17_Shuffle": [20.66, 31.10],
}

def load_csv(path):
    return np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)

def inspect(q, pos, fps, event_time, label):
    # Print transitions within 0.12 seconds of the event.
    center = round(event_time * fps)
    radius = max(2, round(0.12 * fps))

    start = max(0, center - radius)
    end = min(len(q) - 1, center + radius)

    print(f"\n  {label} ({fps:g} Hz)")
    print("    Time     Max joint jump   Affected joints   Root jump")

    for i in range(start, end):
        change = np.abs(q[i + 1] - q[i])

        max_jump = change.max()
        affected = np.count_nonzero(change > 0.15)

        root_jump = np.linalg.norm(
            pos[i + 1] - pos[i]
        )

        flag = " <--" if max_jump > 0.25 else ""

        print(
            f"    {i/fps:7.3f}s"
            f"   {max_jump:10.4f} rad"
            f"      {affected:3d}"
            f"          {root_jump:.4f} m"
            f"{flag}"
        )

for name, times in EVENTS.items():
    original = (
        Path("dataset/dance") / name /
        "retarget" / f"{name}.pkl"
    )

    converted = Path("converted") / name

    if not original.exists():
        print(f"Missing source: {original}")
        continue

    # Load only PKL files from a source you trust.
    with original.open("rb") as f:
        data = pickle.load(f)

    fps_src = float(data["fps"])
    q_src = np.asarray(data["dof_pos"])
    p_src = np.asarray(data["root_pos"])

    q_dst = load_csv(converted / "joint_pos.csv")
    p_dst = load_csv(converted / "body_pos.csv")

    print("\n" + "=" * 65)
    print(name)
    print("=" * 65)

    for t in times:
        print(f"\nEVENT NEAR {t:.3f}s")

        inspect(q_src, p_src, fps_src, t, "ORIGINAL")
        inspect(q_dst, p_dst, 50.0, t, "CONVERTED")

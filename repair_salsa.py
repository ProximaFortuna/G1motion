from pathlib import Path
from shutil import copy2

import numpy as np
from scipy.interpolate import BPoly
from scipy.spatial.transform import Rotation, Slerp

FPS = 50.0
DT = 1.0 / FPS

NAME = "J_Dance2_Salsa"

SOURCE = Path("converted") / NAME
OUTPUT = Path("repaired") / NAME

# Known discontinuities in the converted trajectory.
EVENTS = [12.62, 32.32]

# Experimental blend duration: 0.8 seconds.
# Simulation-only. Not a verified hardware-safe value.
HALF_WINDOW = 0.40


def load_csv(filename):
    path = SOURCE / filename

    with path.open() as f:
        header = f.readline().rstrip("\n")

    data = np.loadtxt(
        path,
        delimiter=",",
        skiprows=1,
        ndmin=2
    )

    return data, header


def save_csv(filename, data, header):
    np.savetxt(
        OUTPUT / filename,
        data,
        delimiter=",",
        header=header,
        comments="",
        fmt="%.10f"
    )


def quintic_smoothstep(u):
    return 10*u**3 - 15*u**4 + 6*u**5


def blend_vectors(data, start, end):
    """
    Replace a local interval with a quintic Hermite
    polynomial matching position, velocity, and
    acceleration at both endpoints.
    """

    result = data.copy()

    vel = np.gradient(data, DT, axis=0)
    acc = np.gradient(vel, DT, axis=0)

    t0 = start * DT
    t1 = end * DT

    polynomial = BPoly.from_derivatives(
        [t0, t1],
        [
            [data[start], vel[start], acc[start]],
            [data[end], vel[end], acc[end]]
        ]
    )

    times = np.arange(start, end + 1) * DT

    result[start:end + 1] = polynomial(times)

    return result


def blend_quaternions(data, start, end):
    """
    Root quaternion input and output convention: WXYZ.

    Interpolate orientations using SLERP with a
    quintic time parameter.
    """

    result = data.copy()

    # SciPy uses XYZW.
    first = data[start, [1, 2, 3, 0]]
    last = data[end, [1, 2, 3, 0]]

    rotations = Rotation.from_quat(
        np.stack([first, last])
    )

    slerp = Slerp([0.0, 1.0], rotations)

    u = np.linspace(0.0, 1.0, end - start + 1)
    alpha = quintic_smoothstep(u)

    xyzw = slerp(alpha).as_quat()

    result[start:end + 1] = xyzw[:, [3, 0, 1, 2]]

    return result


def main():
    q, q_header = load_csv("joint_pos.csv")
    _, dq_header = load_csv("joint_vel.csv")
    pos, pos_header = load_csv("body_pos.csv")
    quat, quat_header = load_csv("body_quat.csv")

    if q.shape[1] != 29:
        raise ValueError("Expected 29 joints")

    if pos.shape[1] != 3:
        raise ValueError("Expected one root position")

    if quat.shape[1] != 4:
        raise ValueError("Expected one root quaternion")

    if not (
        len(q) == len(pos) == len(quat)
    ):
        raise ValueError("Frame counts do not match")

    if not all(np.isfinite(a).all() for a in (q, pos, quat)):
        raise ValueError("Non-finite source data")

    OUTPUT.mkdir(parents=True, exist_ok=True)

    q_new = q.copy()
    pos_new = pos.copy()
    quat_new = quat.copy()

    for event in EVENTS:
        start = round((event - HALF_WINDOW) * FPS)
        end = round((event + HALF_WINDOW) * FPS)

        if start < 2 or end > len(q) - 3:
            raise ValueError(
                f"Repair window out of bounds: {event}"
            )

        print(
            f"\nRepairing {event:.2f}s:"
            f" frames {start} to {end}"
        )

        q_new = blend_vectors(q_new, start, end)

        pos_new = blend_vectors(
            pos_new, start, end
        )

        quat_new = blend_quaternions(
            quat_new, start, end
        )

    # Recompute velocity from repaired joint positions.
    dq_new = np.gradient(q_new, DT, axis=0)

    for filename, data, header in [
        ("joint_pos.csv", q_new, q_header),
        ("joint_vel.csv", dq_new, dq_header),
        ("body_pos.csv", pos_new, pos_header),
        ("body_quat.csv", quat_new, quat_header),
    ]:
        save_csv(filename, data, header)

    metadata = SOURCE / "metadata.txt"

    if metadata.exists():
        copy2(metadata, OUTPUT / "metadata.txt")

    old_velocity = np.abs(
        np.diff(q, axis=0) / DT
    )

    new_velocity = np.abs(
        np.diff(q_new, axis=0) / DT
    )

    print("\n========== RESULTS ==========")

    print(
        "Original max joint velocity:",
        f"{old_velocity.max():.2f} rad/s"
    )

    print(
        "Repaired max joint velocity:",
        f"{new_velocity.max():.2f} rad/s"
    )

    print("\nLocal repair statistics:")

    for event in EVENTS:
        a = round((event - HALF_WINDOW) * FPS)
        b = round((event + HALF_WINDOW) * FPS)

        old = old_velocity[a:b].max()
        new = new_velocity[a:b].max()

        print(
            f"{event:.2f}s: "
            f"{old:.2f} -> {new:.2f} rad/s"
        )

    print(f"\nSaved to: {OUTPUT.resolve()}")
    print("SIMULATION-ONLY REFERENCE")


if __name__ == "__main__":
    main()

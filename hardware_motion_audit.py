from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

ROOT = Path("converted")
FPS = 50.0

def load(path):
    return np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)

for folder in sorted(ROOT.iterdir()):
    if not folder.is_dir():
        continue

    print(f"\n{'=' * 60}")
    print(folder.name)
    print("=" * 60)

    try:
        q = load(folder / "joint_pos.csv")
        dq_file = load(folder / "joint_vel.csv")
        pos = load(folder / "body_pos.csv")
        quat = load(folder / "body_quat.csv")
    except (OSError, ValueError) as e:
        print("FAILED: Unable to load reference:", e)
        continue

    n = len(q)

    if q.shape != (n, 29):
        print("FAILED: Expected 29 joints")
        continue

    if dq_file.shape != q.shape:
        print("FAILED: Joint velocity shape mismatch")
        continue

    if pos.shape != (n, 3) or quat.shape != (n, 4):
        print("FAILED: Expected one root position and quaternion")
        continue

    if n < 3:
        print("FAILED: Insufficient frames")
        continue

    if not all(np.isfinite(a).all()
               for a in [q, dq_file, pos, quat]):
        print("FAILED: Non-finite values detected")
        continue

    quat_norm = np.linalg.norm(quat, axis=1)

    if np.any(quat_norm < 1e-8):
        print("FAILED: Invalid zero-length quaternion")
        continue

    joint_vel = np.diff(q, axis=0) * FPS
    joint_acc = np.diff(joint_vel, axis=0) * FPS

    root_vel = np.diff(pos, axis=0) * FPS

    rotations = Rotation.from_quat(
        quat[:, [1, 2, 3, 0]]
    )

    angular_vel = (
        rotations[:-1].inv() * rotations[1:]
    ).magnitude() * FPS

    horizontal_path = np.linalg.norm(
        np.diff(pos[:, :2], axis=0), axis=1
    ).sum()

    displacement = np.ptp(pos[:, :2], axis=0)

    print(f"Duration: {(n - 1) / FPS:.2f} s")
    print(f"Frames: {n}")

    print(f"Max joint speed: {np.abs(joint_vel).max():.2f} rad/s")
    print(f"Max joint acceleration: {np.abs(joint_acc).max():.2f} rad/s²")

    print(f"Max root speed: {np.linalg.norm(root_vel, axis=1).max():.2f} m/s")
    print(f"Max root angular speed: {angular_vel.max():.2f} rad/s")

    print(f"Root height: {pos[:, 2].min():.3f} to {pos[:, 2].max():.3f} m")
    print(f"Root X range: {displacement[0]:.2f} m")
    print(f"Root Y range: {displacement[1]:.2f} m")
    print(f"Horizontal path length: {horizontal_path:.2f} m")

    print(f"Maximum quaternion norm error: {np.max(np.abs(quat_norm - 1)):.6f}")

    peak_joint = np.unravel_index(
        np.abs(joint_vel).argmax(),
        joint_vel.shape
    )

    print(
        f"Fastest joint: index {peak_joint[1]}, "
        f"at {peak_joint[0] / FPS:.2f} s"
    )

    print("RESULT: Numerical report generated. NOT hardware-certified.")

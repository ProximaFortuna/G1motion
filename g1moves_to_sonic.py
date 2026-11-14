#!/usr/bin/env python3
"""Convert trusted G1 Moves retarget PKL into SONIC root-only reference CSV.

This exports reference data for offline inspection and MuJoCo testing only.
Validate the exact G1 model and SONIC checkpoint before any real-robot use.
"""
import argparse
import csv
import pickle
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation, Slerp

# G1 Moves 29-DOF names from exptech/g1-moves dataset README.
SOURCE = '''left_hip_pitch left_hip_roll left_hip_yaw left_knee left_ankle_pitch left_ankle_roll right_hip_pitch right_hip_roll right_hip_yaw right_knee right_ankle_pitch right_ankle_roll waist_yaw waist_roll waist_pitch left_shoulder_pitch left_shoulder_roll left_shoulder_yaw left_elbow left_wrist_roll left_wrist_pitch left_wrist_yaw right_shoulder_pitch right_shoulder_roll right_shoulder_yaw right_elbow right_wrist_roll right_wrist_pitch right_wrist_yaw'''.split()
# SONIC G1_ISAACLab_ORDER from NVlabs gear_sonic/envs/env_utils/joint_utils.py.
TARGET = '''left_hip_pitch right_hip_pitch waist_yaw left_hip_roll right_hip_roll waist_roll left_hip_yaw right_hip_yaw waist_pitch left_knee right_knee left_shoulder_pitch right_shoulder_pitch left_ankle_pitch right_ankle_pitch left_shoulder_roll right_shoulder_roll left_ankle_roll right_ankle_roll left_shoulder_yaw right_shoulder_yaw left_elbow right_elbow left_wrist_roll right_wrist_roll left_wrist_pitch right_wrist_pitch left_wrist_yaw right_wrist_yaw'''.split()
assert len(SOURCE) == len(TARGET) == 29 and set(SOURCE) == set(TARGET)
PERMUTATION = [SOURCE.index(name) for name in TARGET]

def write_csv(path, data, headers):
    with path.open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(data)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input_pkl', type=Path)
    parser.add_argument('output_motion_dir', type=Path)
    parser.add_argument('--fps', type=float, default=50.0)
    args = parser.parse_args()
    if args.fps <= 0:
        parser.error('--fps must be positive')
    # CAUTION: Only unpickle files from a source you trust. Pickle can execute code.
    with args.input_pkl.open('rb') as f:
        m = pickle.load(f)
    required = {'fps', 'root_pos', 'root_rot', 'dof_pos'}
    if not isinstance(m, dict) or not required.issubset(m):
        raise ValueError(f'Expected G1 Moves retarget PKL keys {sorted(required)}')
    src_fps = float(m['fps'])
    q = np.asarray(m['dof_pos'], dtype=float)
    pos = np.asarray(m['root_pos'], dtype=float)
    quat_xyzw = np.asarray(m['root_rot'], dtype=float)
    n = len(q)
    if src_fps <= 0 or q.shape != (n,29) or pos.shape != (n,3) or quat_xyzw.shape != (n,4) or n < 3:
        raise ValueError('Invalid fps or unexpected data shapes')
    if not all(np.isfinite(x).all() for x in (q,pos,quat_xyzw)):
        raise ValueError('Non-finite values')
    if np.any(np.linalg.norm(quat_xyzw, axis=1) < 1e-6):
        raise ValueError('Invalid root quaternion')
    # Source samples occur at 0, 1/src_fps, ..., (N-1)/src_fps.
    duration = (n-1)/src_fps
    t_src = np.arange(n)/src_fps
    # Include only timestamps inside the source motion; never extrapolate.
    t_dst = np.arange(int(np.floor(duration*args.fps + 1e-9))+1)/args.fps
    # Retargeted robot joints are ordinary bounded revolute joints; use
    # piecewise-linear interpolation, not angular unwrapping across limits.
    q_dst = np.column_stack([np.interp(t_dst, t_src, q[:,j]) for j in PERMUTATION])
    vel = np.gradient(q_dst, 1.0/args.fps, axis=0, edge_order=2)
    root_pos = np.column_stack([np.interp(t_dst, t_src, pos[:,j]) for j in range(3)])
    # G1 Moves PKL quaternions are xyzw. SciPy Rotation takes xyzw.
    root_rot = Slerp(t_src, Rotation.from_quat(quat_xyzw))(t_dst).as_quat()
    # Convert from scipy xyzw to SONIC wxyz.
    root_wxyz = root_rot[:, [3,0,1,2]]
    out = args.output_motion_dir
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out/'joint_pos.csv', q_dst, [f'joint_{j}' for j in range(29)])
    write_csv(out/'joint_vel.csv', vel, [f'joint_vel_{j}' for j in range(29)])
    write_csv(out/'body_pos.csv', root_pos, ['body_0_x','body_0_y','body_0_z'])
    write_csv(out/'body_quat.csv', root_wxyz, ['body_0_w','body_0_x','body_0_y','body_0_z'])
    (out/'metadata.txt').write_text(
        f'Metadata for: {out.name}\n==============================\n\n'
        f'Body part indexes:\n[0]\n\nTotal timesteps: {len(t_dst)}\n')
    (out/'info.txt').write_text(
        f'Source: {args.input_pkl}\nSource FPS: {src_fps}\n'
        f'Output FPS: {args.fps}\nOutput frames: {len(t_dst)}\n'
        f'Motion duration: {duration:.4f} s\n'
        'Joint convention: SONIC IsaacLab 29-DOF\n'
        'Quaternion convention: wxyz\n'
        'Root data: G1 Moves retarget PKL root, not full-body FK\n')
    print('Output:', out)
    print('Source:', src_fps, 'Hz,', n, 'frames')
    print('Target:', args.fps, 'Hz,', len(t_dst), 'frames')
    print('Duration:', round(duration,3), 'seconds')
    print('Max |joint velocity|:', round(float(np.max(np.abs(vel))), 3), 'rad/s')
    print('Joint permutation (target index -> source index):', PERMUTATION)
    print('SIMULATION ONLY: validate origin, posture, joint limits and contacts.')

if __name__ == '__main__':
    main()

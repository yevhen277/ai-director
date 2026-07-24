# -*- coding: utf-8 -*-
"""A1Z FK sanity check — chain from A1Z_G1Z.urdf (all joint rpy = 0).
T_i = T(parent) · Trans(xyz) · Rot(axis, q). URDF Z-up, meters.
Camera model: offset CAM_OFF in arm_link6 frame, optical axis = +X of link6.
"""
import sys, math
import numpy as np
sys.stdout.reconfigure(encoding='utf-8')

JOINTS = [  # name, xyz, axis, lo, hi (URDF)
    ("J1", (0,      0, 0.075), (0, 0, 1), -2.094, 2.094),
    ("J2", (0.02,   0, 0.043), (0, 1, 0),  0.0,   3.142),
    ("J3", (-0.264, 0, 0),     (0, 1, 0), -3.142, 0.0),
    ("J4", (0.245,  0, 0.06),  (0, 1, 0), -1.309, 1.309),
    ("J5", (0.074,  0, 0.042), (0, 0, 1), -1.484, 1.484),
    ("J6", (0.0235, 0,-0.042), (1, 0, 0), -2.007, 2.007),
]
CAM_OFF = np.array([0.135, 0, 0])   # 候选相机安装点（指尖之外）
FINGER_L = (0.0727, -0.025, 0.018)
FINGER_R = (0.0727,  0.025, -0.018)

def rot_axis(axis, q):
    x, y, z = axis; c, s = math.cos(q), math.sin(q); C = 1 - c
    return np.array([
        [c + x*x*C,   x*y*C - z*s, x*z*C + y*s],
        [y*x*C + z*s, c + y*y*C,   y*z*C - x*s],
        [z*x*C - y*s, z*y*C + x*s, c + z*z*C]])

def fk(q):
    T = np.eye(4)
    for i, (_, xyz, axis, *_ ) in enumerate(JOINTS):
        A = np.eye(4); A[:3, 3] = xyz
        B = np.eye(4); B[:3, :3] = rot_axis(axis, q[i])
        T = T @ A @ B
    return T  # link6 frame

def cam(T):
    C = T[:3, 3] + T[:3, :3] @ CAM_OFF
    f = T[:3, :3] @ np.array([1, 0, 0])
    return C, f

PRESETS = {
    "zero  ": [0, 0, 0, 0, 0, 0],
    "home  ": [0, 60, -60, 0, 0, 0],
    "ready ": [0, 30, -30, 0, 45, 0],
    "reach ": [0, 20, -30, 0, 60, 0],
    "bow   ": [0, 110, -130, 0, 0, 0],
    "salute": [30, 35, -80, 0, 80, 90],
}

for name, deg in PRESETS.items():
    q = [math.radians(d) for d in deg]
    T = fk(q)
    C, f = cam(T)
    tcp = T[:3, 3] + T[:3, :3] @ np.array([0.0727, 0, 0])
    print(f"{name} q={deg}")
    print(f"   link6 org = {np.round(T[:3,3], 3)}  tcp = {np.round(tcp, 3)}")
    print(f"   cam pos   = {np.round(C, 3)}  cam fwd = {np.round(f, 3)}")

# 工作空间粗扫：相机点能到达的 x/z 范围（J2,J3 栅格，其余 0）
xs, zs = [], []
for q2 in np.linspace(0, 3.142, 40):
    for q3 in np.linspace(-3.142, 0, 40):
        T = fk([0, q2, q3, 0, 0, 0])
        C, _ = cam(T)
        xs.append(C[0]); zs.append(C[2])
print("\ncam reach (J1=0,J4-6=0): x∈[%.3f,%.3f] z∈[%.3f,%.3f]" % (min(xs), max(xs), min(zs), max(zs)))

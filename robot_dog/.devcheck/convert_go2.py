# -*- coding: utf-8 -*-
"""Go2 官方 DAE → 二进制 STL（URDF 系：米制 / Z-up / X 前向），含尺寸断言与减面。
来源：unitreerobotics/unitree_ros@master robots/go2_description/dae/
减面前先按 1e-4m 容差焊接顶点（DAE 由多子网格拼接、接缝顶点重合但未共享，
直接减面会把接缝拉开产生裂缝），并用低 aggression 温和减面。
运行：.devcheck/venv/Scripts/python .devcheck/convert_go2.py"""
import os, sys, numpy as np, trimesh
sys.stdout.reconfigure(encoding='utf-8')

ROOT = os.path.dirname(os.path.abspath(__file__))
DAE = os.path.join(ROOT, 'go2', 'dae')
OUT = os.path.join(ROOT, 'go2', 'meshes')
os.makedirs(OUT, exist_ok=True)

# 文件名 → (减面目标, 包围盒断言[dx范围,dy范围,dz范围]) —— 范围按官方 DAE 实测标定
SPEC = {
    'base':         (40000, ([0.35, 0.60], [0.10, 0.30], [0.10, 0.25])),
    'hip':          (16000, ([0.05, 0.20], [0.04, 0.15], [0.05, 0.20])),
    'thigh':        (14000, ([0.03, 0.15], [0.03, 0.15], [0.20, 0.32])),
    'thigh_mirror': (14000, ([0.03, 0.15], [0.03, 0.15], [0.20, 0.32])),
    'calf':         ( 6000, ([0.02, 0.12], [0.02, 0.12], [0.20, 0.32])),
    'calf_mirror':  ( 6000, ([0.02, 0.12], [0.02, 0.12], [0.20, 0.32])),
    'foot':         ( 2000, ([0.03, 0.06], [0.03, 0.06], [0.03, 0.06])),
}

WELD_TOL = 1e-4  # 焊接容差（米）：子网格接缝处重合顶点合并为共享顶点

def weld(mesh, tol=WELD_TOL):
    """按位置容差焊接顶点，返回新 Trimesh（丢弃法线/UV，STL 本就不存）"""
    key = np.round(mesh.vertices / tol).astype(np.int64)
    _, first, inverse = np.unique(key, axis=0, return_index=True, return_inverse=True)
    faces = inverse[mesh.faces]
    faces = faces[(faces[:, 0] != faces[:, 1]) & (faces[:, 1] != faces[:, 2]) & (faces[:, 0] != faces[:, 2])]
    return trimesh.Trimesh(vertices=mesh.vertices[first], faces=faces, process=False)

def boundary_edges(mesh):
    """开放边界边数（仅被 1 个三角形引用的边）"""
    _, c = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    return int((c == 1).sum())

total_in = total_out = total_bytes = 0
for name, (target, box) in SPEC.items():
    src = os.path.join(DAE, name + '.dae')
    mesh = trimesh.load(src, force='scene').to_geometry()  # 烘焙场景图变换 → URDF link 系
    n0 = len(mesh.faces)
    ext = mesh.extents
    for k, (lo, hi) in enumerate(box):
        assert lo <= ext[k] <= hi, f'{name} 轴{k} 尺寸异常: {ext[k]:.4f} ∉ [{lo},{hi}]（单位/轴向错误？）'
    if name == 'base':
        assert abs(mesh.bounds[0][2] + ext[2] / 2) < 0.06, f'base 未关于 z=0 居中: {mesh.bounds}'
    b_raw = boundary_edges(mesh)
    mesh = weld(mesh)                    # 减面前焊接：接缝变共享边，防止减面开缝
    b_weld = boundary_edges(mesh)
    assert b_weld < b_raw or b_raw == 0, f'{name} 焊接无效: 边界边 {b_raw} → {b_weld}'
    ext2 = mesh.extents
    assert np.allclose(ext, ext2, atol=1e-3), f'{name} 焊接后尺寸变化异常: {ext} vs {ext2}'
    if len(mesh.faces) > target:
        mesh = mesh.simplify_quadric_decimation(face_count=target, aggression=2)
    assert len(mesh.faces) <= target * 1.05, f'{name} 减面失败: {len(mesh.faces)}'
    b_out = boundary_edges(mesh)
    dst = os.path.join(OUT, f'go2_{name}.STL')
    mesh.export(dst, file_type='stl')  # 二进制 STL
    sz = os.path.getsize(dst)
    assert sz == 84 + 50 * len(mesh.faces), f'{name} STL 长度校验失败'
    total_in += n0; total_out += len(mesh.faces); total_bytes += sz
    e = mesh.extents
    print(f'{name:14s} {n0:6d} → {len(mesh.faces):6d} tris  边界边 {b_raw:5d}→焊{b_weld:5d}→出{b_out:5d}  ext=({e[0]:.3f},{e[1]:.3f},{e[2]:.3f})  {sz/1e6:.2f}MB')

print(f'\n合计 {total_in} → {total_out} tris，STL {total_bytes/1e6:.2f}MB，内嵌 base64 ≈ {total_bytes*4/3/1e6:.2f}MB')
print('全部尺寸断言通过（米制 · Z-up · URDF link 系 · 焊接后减面）')

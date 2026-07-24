# -*- coding: utf-8 -*-
"""将 directorx.html 中的 13 个 SO-ARM100 STL base64 块替换为 9 个 A1Z_G1Z 网格块。
块格式与原有一致：<script type="text/plain" class="dx-stl" data-file="...">BASE64</script> 单行。"""
import base64, os, sys, re
sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'C:/Users/Winnie/Desktop/Robot_dog'
HTML = os.path.join(ROOT, 'directorx.html')
MESHDIR = os.path.join(ROOT, '.devcheck', 'a1z', 'meshes')
FILES = ['base_link.STL', 'arm_link1.STL', 'arm_link2.STL', 'arm_link3.STL',
         'arm_link4.STL', 'arm_link5.STL', 'arm_link6.STL',
         'gripper_finger_left_link.STL', 'gripper_finger_rIght_link.STL']

with open(HTML, 'r', encoding='utf-8') as f:
    text = f.read()
lines = text.split('\n')

i0 = next(i for i, l in enumerate(lines) if 'class="dx-stl"' in l)
i1 = next(i for i, l in enumerate(lines) if 'id="dx-module"' in l)
old_blocks = [l for l in lines[i0:i1] if 'class="dx-stl"' in l]
print(f'旧块区间: 行 {i0+1}..{i1}，共 {len(old_blocks)} 个 STL 块')

new_lines = []
for fn in FILES:
    with open(os.path.join(MESHDIR, fn), 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    new_lines.append(f'<script type="text/plain" class="dx-stl" data-file="{fn}">{b64}</script>')
    print(f'  {fn}: {len(b64)} chars base64')

lines[i0:i1] = new_lines
out = '\n'.join(lines)
with open(HTML, 'w', encoding='utf-8') as f:
    f.write(out)
print(f'完成: {len(old_blocks)} 块 → {len(new_lines)} 块; 文件 {len(out)} 字节')

# 回读验证：块数量 + base64 可解码 + 前 84 字节为 STL 头
with open(HTML, 'r', encoding='utf-8') as f:
    t2 = f.read()
blocks = re.findall(r'class="dx-stl" data-file="([^"]+)">([A-Za-z0-9+/=]+)</script>', t2)
assert len(blocks) == 9, f'块数量异常: {len(blocks)}'
for fn, b64 in blocks:
    raw = base64.b64decode(b64)
    n = int.from_bytes(raw[80:84], 'little')
    assert len(raw) == 84 + 50 * n, f'{fn} 长度校验失败'
print('回读验证通过: 9/9 块 base64 可还原为合法二进制 STL')

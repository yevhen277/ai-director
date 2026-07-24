# -*- coding: utf-8 -*-
"""将 7 个 Go2 STL 以 base64 块追加到 directorx.html（紧随现有 9 个 A1Z 块之后、dx-module 之前）。
块格式：<script type="text/plain" class="dx-stl" data-file="...">BASE64</script> 单行。可重复运行（先删旧 go2 块）。"""
import base64, os, sys, re
sys.stdout.reconfigure(encoding='utf-8')

ROOT = r'C:/Users/Winnie/Desktop/Robot_dog'
HTML = os.path.join(ROOT, 'directorx.html')
MESHDIR = os.path.join(ROOT, '.devcheck', 'go2', 'meshes')
FILES = ['go2_base.STL', 'go2_hip.STL', 'go2_thigh.STL', 'go2_thigh_mirror.STL',
         'go2_calf.STL', 'go2_calf_mirror.STL', 'go2_foot.STL']

with open(HTML, 'r', encoding='utf-8') as f:
    lines = f.read().split('\n')

# 先剔除旧的 go2 块（幂等），再定位最后一个 dx-stl 块
lines = [l for l in lines if not ('class="dx-stl"' in l and 'data-file="go2_' in l)]
stl_idx = [i for i, l in enumerate(lines) if 'class="dx-stl"' in l]
mod_idx = next(i for i, l in enumerate(lines) if 'id="dx-module"' in l)
assert stl_idx and max(stl_idx) < mod_idx, 'dx-stl 块定位失败'
print(f'现有 STL 块 {len(stl_idx)} 个，末块行 {max(stl_idx)+1}，dx-module 行 {mod_idx+1}')

new_lines = []
for fn in FILES:
    with open(os.path.join(MESHDIR, fn), 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('ascii')
    new_lines.append(f'<script type="text/plain" class="dx-stl" data-file="{fn}">{b64}</script>')
    print(f'  {fn}: {len(b64)} chars base64')

at = max(stl_idx) + 1
lines[at:at] = new_lines
out = '\n'.join(lines)
with open(HTML, 'w', encoding='utf-8', newline='\n') as f:
    f.write(out)
print(f'完成: 共 {len(stl_idx)+len(new_lines)} 块; 文件 {len(out)} 字节')

# 回读验证：16 块、base64 可解码、二进制 STL 长度自洽
with open(HTML, 'r', encoding='utf-8') as f:
    t2 = f.read()
blocks = re.findall(r'class="dx-stl" data-file="([^"]+)">([A-Za-z0-9+/=]+)</script>', t2)
assert len(blocks) == 16, f'块数量异常: {len(blocks)}'
for fn, b64 in blocks:
    raw = base64.b64decode(b64)
    n = int.from_bytes(raw[80:84], 'little')
    assert len(raw) == 84 + 50 * n, f'{fn} 长度校验失败'
print('回读验证通过: 16/16 块 base64 可还原为合法二进制 STL')

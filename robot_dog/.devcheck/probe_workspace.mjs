/* 工作空间探测 —— 狗背挂载新几何（S=(0.40,0,0.10)，臂 base 系）下各镜头极限扫描
   扫描 200k 随机位形（确定性种子），筛选瞄准误差 ≤2° 的解，报告：
   far=最大视距 / close=最小视距 / top=最大俯角 / low=最低机位（tip z 最小）
   运动学链与 solve_a1z.mjs 严格一致（A1Z_G1Z.urdf）。运行：node probe_workspace.mjs */
let _rngS = 20260723;
Math.random = () => (_rngS = (_rngS * 1103515245 + 12345) & 0x7fffffff) / 0x7fffffff;
const J = [
  [[0, 0, 0.075], [0, 0, 1], [-2.094, 2.094]],
  [[0.02, 0, 0.043], [0, 1, 0], [0, 3.142]],
  [[-0.264, 0, 0], [0, 1, 0], [-3.142, 0]],
  [[0.245, 0, 0.06], [0, 1, 0], [-1.309, 1.309]],
  [[0.074, 0, 0.042], [0, 0, 1], [-1.484, 1.484]],
  [[0.0235, 0, -0.042], [1, 0, 0], [-2.007, 2.007]],
];
const CAM = [0.135, 0, 0], S = [0.40, 0, -0.10 + 0.20]; // = [0.40, 0, 0.10]
const D2R = Math.PI / 180, R2D = 180 / Math.PI;
function ax(a, q) { const [x, y, z] = a, c = Math.cos(q), s = Math.sin(q), C = 1 - c;
  return [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
          [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
          [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]; }
const mm = (A, B) => A.map((r, i) => B[0].map((_, j) => r[0] * B[0][j] + r[1] * B[1][j] + r[2] * B[2][j]));
const mv = (A, v) => [A[0][0] * v[0] + A[0][1] * v[1] + A[0][2] * v[2], A[1][0] * v[0] + A[1][1] * v[1] + A[1][2] * v[2], A[2][0] * v[0] + A[2][1] * v[1] + A[2][2] * v[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const nrm = v => Math.hypot(...v);
function info(q) { let R = [[1,0,0],[0,1,0],[0,0,1]], p = [0,0,0];
  for (let i = 0; i < 6; i++) { p = add(p, mv(R, J[i][0])); R = mm(R, ax(J[i][1], q[i])); }
  const tip = add(p, mv(R, CAM)), gaze = mv(R, [1, 0, 0]);
  const d = sub(S, tip), dist = nrm(d);
  const aim = Math.acos(Math.min(1, Math.max(-1, dot(gaze, d) / dist)));
  const pitch = -Math.asin(Math.min(1, Math.max(-1, gaze[2])));
  return { tip, dist, aim: aim * R2D, pitch: pitch * R2D }; }

const best = { far: null, close: null, top: null, low: null };
let bestAim = null;
const N = 200000;
for (let k = 0; k < N; k++) {
  const q = J.map(j => j[2][0] + Math.random() * (j[2][1] - j[2][0]));
  q[5] = 1.571 + (Math.random() - 0.5) * 0.3;  // J6 近地平线基准（与 v5 机位族一致）
  const e = info(q);
  if (!bestAim || e.aim < bestAim.e.aim) bestAim = { q, e };
  if (e.aim > 2) continue;
  if (!best.far || e.dist > best.far.e.dist) best.far = { q, e };
  if (!best.close || e.dist < best.close.e.dist) best.close = { q, e };
  if (!best.top || e.pitch > best.top.e.pitch) best.top = { q, e };
  if (!best.low || e.tip[2] < best.low.e.tip[2]) best.low = { q, e };
}
if (bestAim) console.log('minAim', 'q=[' + bestAim.q.map(x => x.toFixed(3)).join(',') + ']',
  'tip=(' + bestAim.e.tip.map(x => x.toFixed(3)).join(',') + ')',
  'dist', (bestAim.e.dist * 100).toFixed(1) + 'cm', 'aim', bestAim.e.aim.toFixed(2) + '°', 'pitch', bestAim.e.pitch.toFixed(1) + '°');
let hits = 0;
for (const [k, v] of Object.entries(best)) {
  if (!v) { console.log(k.padEnd(6), '无命中'); continue; }
  hits++;
  const { q, e } = v;
  console.log(k.padEnd(6), 'q=[' + q.map(x => x.toFixed(3)).join(',') + ']',
    'tip=(' + e.tip.map(x => x.toFixed(3)).join(',') + ')',
    'dist', (e.dist * 100).toFixed(1) + 'cm', 'aim', e.aim.toFixed(2) + '°', 'pitch', e.pitch.toFixed(1) + '°');
}

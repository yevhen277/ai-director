/* A1Z 镜头位姿求解器 v6 —— 运动学链严格取自 A1Z_G1Z.urdf（全关节 rpy=0）
   相机模型：安装点 = arm_link6 系 (0.135,0,0)，光轴 = link6 +X，上向量 = link6 +Y
   v6：机械臂挂载 Unitree Go2 背部 → 被摄物 S=(0.40,0,0.10)（臂 base 系，世界系 43.2cm 展示台）。
       far/top/low/close 改为「瞄准强约束下优化极限指标」直接锚定（不再平移 v5 目标——
       平移会破坏锚定位形的瞄准几何，已证伪）。运行：node solve_a1z.mjs */
import { writeFileSync } from 'fs';
// 固定随机种子：求解结果可复现（pose_a1z.json 与打印指标严格对应）
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
const CAM = [0.135, 0, 0];
// 被摄物：臂 base 系 S=(0.40,0,0.10)（狗背挂载几何：MOUNT=(0.08,0,0.063)，base 离地 0.2868m
// → 世界系 (0.48,0,0.45)，43.2cm 展示台。抬高被摄物后全部机位相机位均高于狗头凸包
// （狗 base 系 z≤0.055），无碰撞通道；低机位微仰在此几何下方为物理可达）
const S = [0.40, 0, 0.10];
const BETA = 0;
const GAZE_L = [Math.cos(BETA), -Math.sin(BETA), 0];
const UP_L = [Math.sin(BETA), Math.cos(BETA), 0];
const D2R = Math.PI / 180, R2D = 180 / Math.PI;

function ax(a, q) { const [x, y, z] = a, c = Math.cos(q), s = Math.sin(q), C = 1 - c;
  return [[c + x * x * C, x * y * C - z * s, x * z * C + y * s],
          [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
          [z * x * C - y * s, z * y * C + x * s, c + z * z * C]]; }
const mm = (A, B) => A.map((r, i) => B[0].map((_, j) => r[0] * B[0][j] + r[1] * B[1][j] + r[2] * B[2][j]));
const mv = (A, v) => [A[0][0] * v[0] + A[0][1] * v[1] + A[0][2] * v[2], A[1][0] * v[0] + A[1][1] * v[1] + A[1][2] * v[2], A[2][0] * v[0] + A[2][1] * v[1] + A[2][2] * v[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]], sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const nrm = v => Math.hypot(...v);

function fkR(q) { let R = [[1, 0, 0], [0, 1, 0], [0, 0, 1]], p = [0, 0, 0];
  for (let i = 0; i < 6; i++) { p = add(p, mv(R, J[i][0])); R = mm(R, ax(J[i][1], q[i])); }
  return { R, p }; }
function info(q) {
  const { R, p } = fkR(q);
  const tip = add(p, mv(R, CAM)), gaze = mv(R, GAZE_L), up = mv(R, UP_L);
  const d = sub(S, tip), dist = nrm(d);
  const aim = Math.acos(Math.min(1, Math.max(-1, dot(gaze, d) / dist)));
  const pitch = -Math.asin(Math.min(1, Math.max(-1, gaze[2])));
  const gz = dot([0, 0, 1], gaze), zproj = [0, 0, 1].map((v, i) => v - gz * gaze[i]);
  let roll = 0;
  if (nrm(zproj) > 0.05) {
    const u = up.map((v, i) => v - dot(up, gaze) * gaze[i]);
    roll = Math.atan2(dot(cross(u, zproj), gaze), dot(u, zproj));
  }
  return { tip, dist, aim: aim * R2D, roll: roll * R2D, pitch: pitch * R2D };
}
function mkcost(T, rollT, q1T, o, cont) { return q => {
  const { tip, aim, roll } = info(q);
  const e = sub(tip, T);
  let c = o.wPos * (e[0] ** 2 + e[1] ** 2 + e[2] ** 2) + o.wAim * (aim * D2R) ** 2
       + o.wRoll * ((roll - rollT) * D2R) ** 2 + 0.12 * (q[0] - q1T) ** 2;
  if (cont) { let s = 0; for (let i = 0; i < 6; i++) s += (q[i] - cont.q[i]) ** 2; c += cont.w * s; }
  return c;
}; }
function descend(seed, cost, freeMask) {
  let best = seed.map((v, i) => Math.min(J[i][2][1], Math.max(J[i][2][0], v))), bc = cost(best), step = 0.25;
  for (let it = 0; it < 2000; it++) { let moved = false;
    for (let j = 0; j < 6; j++) { if (!freeMask[j]) continue;
      for (const s of [1, -1]) {
        const c = [...best]; c[j] += s * step;
        if (c[j] < J[j][2][0] || c[j] > J[j][2][1]) continue;
        const cc = cost(c);
        if (cc < bc) { best = c; bc = cc; moved = true; } } }
    if (!moved) { step *= 0.5; if (step < 1e-5) break; } }
  return best;
}
const ALL = [1, 1, 1, 1, 1, 1], WRIST = [0, 0, 0, 0, 1, 1];
function solvePose(name, T, q1T, seed, o = {}) {
  const p = { rollT: 0, wRoll: 0.8, wPos: 16, wAim: 1, restarts: 24, jitter: 0.3, cont: null, quiet: false, ...o };
  let best = null, bc = 1e9;
  const costA = mkcost(T, 0, q1T, p, p.cont);
  for (let r = 0; r < p.restarts; r++) {
    const s0 = seed.map(v => v + (Math.random() - 0.5) * p.jitter);
    const b = descend(s0, costA, ALL), c = costA(b);
    if (c < bc) { best = b; bc = c; } }
  best = descend(best, mkcost(T, p.rollT, q1T, p, p.cont), WRIST);
  const { tip, dist, aim, roll, pitch } = info(best), perr = nrm(sub(tip, T)) * 1000;
  if (!p.quiet) console.log(name.padEnd(7), '[' + best.map(x => x.toFixed(3)).join(', ') + ']',
    '| aim', aim.toFixed(1).padStart(5), '° roll', roll.toFixed(0).padStart(4),
    '° pitch', pitch.toFixed(0).padStart(4), '° perr', perr.toFixed(0).padStart(3),
    'mm dist', (dist * 100).toFixed(1).padStart(5), 'cm z', tip[2].toFixed(3));
  return best;
}
const T = (dx, dy, dz) => [S[0] + dx, S[1] + dy, S[2] + dz];
const rot = (dx, a) => [dx * Math.cos(a), dx * Math.sin(a)];
const mirror = q => [-q[0], q[1], q[2], q[3], -q[4], q[5]];
const mid = (na, a, nb, b) => { const q = a.map((v, i) => (v + b[i]) / 2); const { dist, aim } = info(q);
  console.log(('  ' + na + '->' + nb).padEnd(18), 'aim', aim.toFixed(1).padStart(5), '° dist', (dist * 100).toFixed(1), 'cm'); };

console.log('=== 基础机位（aim 优先，位置近似）===');
const home  = solvePose('home', T(-0.28, 0, 0.16), 0, [-0.006, 0.589, -1.341, 1.272, 0.005, 1.568], { wAim: 25, wPos: 4 });
const close = solvePose('close', T(-0.13, 0, 0.06), 0, home, { wAim: 25, wPos: 4, restarts: 8, jitter: 0.1, cont: { q: home, w: 0.05 } });

/* 极限机位：瞄准强约束（≤约1°）下直接优化极限指标 ——
   far=最大视距 / top=最大俯角 / low=最低机位（tip z 最小；dist≥15cm 防微距顶撞被摄物） */
function optExtreme(name, seed, obj) {
  const cost = q => { const e = info(q); return 25 * (e.aim * D2R) ** 2 + obj(e); };
  let best = null, bc = 1e9;
  for (let r = 0; r < 12; r++) {
    const s0 = seed.map(v => v + (Math.random() - 0.5) * 0.15);
    const b = descend(s0, cost, ALL), c = cost(b);
    if (c < bc) { best = b; bc = c; }
  }
  best = descend(best, cost, WRIST);
  const e = info(best);
  console.log(name.padEnd(7), '[' + best.map(x => x.toFixed(3)).join(', ') + ']',
    '| aim', e.aim.toFixed(1).padStart(5), '° roll', e.roll.toFixed(0).padStart(4),
    '° pitch', e.pitch.toFixed(0).padStart(4), '° dist', (e.dist * 100).toFixed(1).padStart(5), 'cm z', e.tip[2].toFixed(3));
  return best;
}
const far   = optExtreme('far', [-0.000, 0.020, -1.057, 1.309, 0.000, 1.571], e => -0.3 * e.dist);
const top   = optExtreme('top', [-0.001, 1.544, -1.807, 1.284, 0.002, 1.567], e => -0.3 * e.pitch * D2R + Math.max(0, 0.22 - e.dist) * 3);
const low   = optExtreme('low', [0.008, 1.156, -0.021, -1.242, -0.012, 1.569], e => 0.6 * e.tip[2] + Math.max(0, 0.15 - e.dist) * 2);

console.log('=== 低机位过渡链（插值中点自瞄）===');
const lowPre= solvePose('lowPre', info(home.map((v, i) => (v + low[i]) / 2)).tip, 0,
  home.map((v, i) => (v + low[i]) / 2), { wPos: 6, wAim: 25, restarts: 1, jitter: 0 });
const lowPre0=solvePose('lowPre0', info(home.map((v, i) => (v + lowPre[i]) / 2)).tip, 0,
  home.map((v, i) => (v + lowPre[i]) / 2), { wPos: 6, wAim: 25, restarts: 1, jitter: 0 });
const lowPre2=solvePose('lowPre2', info(lowPre.map((v, i) => (v + low[i]) / 2)).tip, 0,
  lowPre.map((v, i) => (v + low[i]) / 2), { wPos: 6, wAim: 25, restarts: 1, jitter: 0 });

console.log('\n=== 弧拍（软化滚转，目标 dutch 5°/10°）===');
let orbCfg = null;
for (const [r, a1, a2, d1, d2] of [[0.26, 12, 24, 5, 10], [0.28, 12, 24, 5, 10], [0.28, 14, 28, 6, 12], [0.30, 12, 24, 6, 12], [0.26, 13, 26, 6, 12]]) {
  const [x1, y1] = rot(-r, a1 * D2R), [x2, y2] = rot(-r, a2 * D2R);
  const o0 = solvePose('o0', T(-r, 0, 0.14), 0, home, { quiet: true });
  const o1 = solvePose('o1', T(x1, -y1, 0.14), -a1 * D2R, o0, { rollT: d1, wRoll: 0.15, wPos: 20, wAim: 9, quiet: true });
  const o2 = solvePose('o2', T(x2, -y2, 0.14), -a2 * D2R, o1, { rollT: d2, wRoll: 0.15, wPos: 20, wAim: 9, quiet: true });
  const e1 = info(o1), e2 = info(o2);
  console.log(`r=${r} a=${a1}/${a2} d=${d1}/${d2}: o1 aim ${e1.aim.toFixed(1)}° roll ${e1.roll.toFixed(0)}° | o2 aim ${e2.aim.toFixed(1)}° roll ${e2.roll.toFixed(0)}°`);
  if (!orbCfg && e1.aim < 2.5 && e2.aim < 2.5) orbCfg = { r, a1, a2, d1, d2, o0, o1, o2 };
}
if (!orbCfg) throw new Error('弧拍无可行配置');
const { r: oR, a1: oA1, a2: oA2, d1: oD1, d2: oD2, o0: orb0, o1: orbL1, o2: orbL2 } = orbCfg;
console.log(`选定: r=${oR} a=${oA1}/${oA2}° dutch=${oD1}/${oD2}°`);
const [ox1, oy1] = rot(-oR, oA1 * D2R), [ox2, oy2] = rot(-oR, oA2 * D2R);
const orbR1 = solvePose('orbR1', T(ox1, oy1, 0.14), oA1 * D2R, mirror(orbL1), { rollT: -oD1, wRoll: 0.15, wPos: 20, wAim: 9 });
const orbR2 = solvePose('orbR2', T(ox2, oy2, 0.14), oA2 * D2R, mirror(orbL2), { rollT: -oD2, wRoll: 0.15, wPos: 20, wAim: 9 });

console.log('\n=== 横移扫掠 ===');
const [sxA, syA] = rot(-0.32, 18 * D2R), [sxB, syB] = rot(-0.32, -18 * D2R);
const swpA = solvePose('swpA', T(sxA, syA, 0.20), 0.31, home, { wPos: 6, wAim: 9 });
const swpB = solvePose('swpB', T(sxB, syB, 0.20), -0.31, mirror(swpA), { wPos: 6, wAim: 9 });

console.log('\n=== 线性插值中点瞄准检查（分镜实际转移）===');
mid('home', home, 'orb0', orb0);
mid('orb0', orb0, 'orbL1', orbL1); mid('orbL1', orbL1, 'orbL2', orbL2);
mid('orb0', orb0, 'orbR1', orbR1); mid('orbR1', orbR1, 'orbR2', orbR2);
mid('home', home, 'close', close); mid('close', close, 'far', far); mid('far', far, 'home', home);
mid('home', home, 'top', top); mid('top', top, 'home', home);
mid('home', home, 'lowPre0', lowPre0); mid('lowPre0', lowPre0, 'lowPre', lowPre); mid('lowPre', lowPre, 'lowPre2', lowPre2); mid('lowPre2', lowPre2, 'low', low); mid('low', low, 'lowPre2', lowPre2);
mid('home', home, 'swpA', swpA); mid('swpA', swpA, 'swpB', swpB); mid('swpB', swpB, 'home', home);
mid('orbR1', orbR1, 'top', top);

const POSE = { home, close, far, top, low, lowPre0, lowPre, lowPre2, orb0, orbL1, orbL2, orbR1, orbR2, swpA, swpB };
writeFileSync('pose_a1z.json', JSON.stringify(POSE, null, 1));
console.log('\n已写出 pose_a1z.json');
console.log('\nPOSE = {');
for (const [k, q] of Object.entries(POSE))
  console.log(`  ${k.padEnd(7)}: [${q.map(v => v.toFixed(3).padStart(6)).join(',')}],`);
console.log('};');

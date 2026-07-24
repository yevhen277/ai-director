/* DirectorX A1Z 版逻辑测试：从 app_a1z.mjs 抽取纯逻辑块在 node 中执行验证
   —— 方案生成 / 采样 / 官方 move 序列，全部对照 A1Z URDF 限位与速度上限 */
import { readFileSync } from 'fs';
const src = readFileSync('app_a1z.mjs', 'utf8').replace(/\r\n/g, '\n');

function grab(start, end) {
  const i = src.indexOf(start);
  if (i < 0) throw new Error('未找到: ' + start.slice(0, 40));
  const j = src.indexOf(end, i);
  if (j < 0) throw new Error('未找到结束: ' + end.slice(0, 40));
  return src.slice(i, j + end.length);
}
const blocks = [
  grab('const CONFIG = {', '};'),
  grab('const JOINTS = [', '];'),
  grab('const POSE = {', '};'),
  grab('const rollShift =', ';'),
  grab('const yawShift =', ';'),
  grab('const DirectorAI = (() => {', '})();'),
  grab('function planToWaypoints', 'return wps;\n}'),
  grab('function buildSamples', 'return { samples, dur: W[n - 1].t };\n}'),
  grab('const A1Z_LIMITS =', ';'),
  grab('const clampA1Z =', ';'),
  grab('const sleep =', ';'),
  grab('function planToMoves', 'return moves;\n}'),
];
const code = blocks.join('\n') + '\nreturn { CONFIG, JOINTS, POSE, DirectorAI, planToWaypoints, buildSamples, planToMoves, A1Z_LIMITS };';
const M = new Function(code)();

let pass = 0, fail = 0;
const ok = (cond, name, extra = '') => { if (cond) { pass++; } else { fail++; console.log('FAIL:', name, extra); } };

// 1. POSE 全在 URDF 限位内
for (const [k, q] of Object.entries(M.POSE)) {
  ok(q.length === 6 && q.every((v, i) => v >= M.A1Z_LIMITS[i][0] - 1e-6 && v <= M.A1Z_LIMITS[i][1] + 1e-6),
    'POSE 限位: ' + k, JSON.stringify(q));
}

// 2. 方案生成：六种指令 + 大片
const cmds = ['缓慢推近，给产品一个特写', '荷兰角环绕拍一圈', '拉远展示全貌', '俯拍展示，然后复位', '低机位仰拍', '横移扫掠', '来一条完整产品大片'];
for (const c of cmds) {
  const plan = await M.DirectorAI.generatePlan(c);
  const wps = M.planToWaypoints(plan);
  // 时间轴单调（分镜边界允许等时重复关键帧，位姿须一致）
  ok(wps.every((w, i) => i === 0 || w.t >= wps[i - 1].t), '时间轴单调: ' + c);
  ok(wps.every((w, i) => i === 0 || w.t > wps[i - 1].t || w.q.every((v, j) => Math.abs(v - wps[i - 1].q[j]) < 1e-9)), '边界重复帧位姿一致: ' + c);
  // 所有关键帧限位内
  ok(wps.every(w => w.q.every((v, i) => v >= M.A1Z_LIMITS[i][0] - 1e-6 && v <= M.A1Z_LIMITS[i][1] + 1e-6)), '关键帧限位: ' + c);
  // 采样连续、无 NaN
  const traj = M.buildSamples(wps, 0.7);
  ok(traj.samples.every(s => s.q.every(Number.isFinite)), '采样有限: ' + c);
  // 采样速度峰值（Hermite 插值不超 2.0 rad/s 太多）
  let vMax = 0;
  for (let i = 1; i < traj.samples.length; i++) {
    const a = traj.samples[i - 1], b = traj.samples[i], dt = b.t - a.t;
    if (dt <= 0) continue;
    for (let j = 0; j < 6; j++) vMax = Math.max(vMax, Math.abs(b.q[j] - a.q[j]) / dt);
  }
  ok(vMax < 3.0, '采样速度峰值合理: ' + c, 'vMax=' + vMax.toFixed(2));
  // 官方 move 序列：速度 ≤ 上限、关节角限位内、时长为正
  const moves = M.planToMoves(plan, 1.0);
  ok(moves.length >= 1, 'move 非空: ' + c);
  ok(moves.every(m => m.speed > 0 && m.speed <= M.CONFIG.A1Z_MOVE_MAX_SPEED + 1e-9), 'move 速度上限: ' + c,
    moves.map(m => m.speed.toFixed(2)).join(','));
  ok(moves.every(m => m.joints.every((v, i) => v >= M.A1Z_LIMITS[i][0] - 1e-6 && v <= M.A1Z_LIMITS[i][1] + 1e-6)), 'move 限位: ' + c);
  ok(moves.every(m => m.dur > 0), 'move 时长为正: ' + c);
  // move 总时长与方案时长同量级
  const tot = moves.reduce((s, m) => s + m.dur, 0);
  ok(tot > plan.total * 0.5 && tot < plan.total * 2.5, 'move 总时长同量级: ' + c,
    `moves=${tot.toFixed(1)}s plan=${plan.total.toFixed(1)}s`);
}
// 3. 速度倍率传导
{
  const plan = await M.DirectorAI.generatePlan('推近特写');
  const m1 = M.planToMoves(plan, 1.0), m2 = M.planToMoves(plan, 2.0);
  ok(Math.abs(m1[0].speed * 2 - m2[0].speed) < 1e-6 || m2[0].speed === M.CONFIG.A1Z_MOVE_MAX_SPEED,
    '速度倍率传导', `1×=${m1[0].speed} 2×=${m2[0].speed}`);
}
console.log(`\n${pass} 项通过, ${fail} 项失败`);
process.exit(fail ? 1 : 0);

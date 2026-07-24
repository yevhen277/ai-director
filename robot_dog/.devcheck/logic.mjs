const JOINTS = [
  { name:'shoulder_pan',  xyz:[0,-0.0452,0.0165], rpy:[1.57079,0,0],       axis:[0,1,0], min:-2,        max:2,        label:'J1 基座' },
  { name:'shoulder_lift', xyz:[0,0.1025,0.0306],  rpy:[-1.8,0,0],          axis:[1,0,0], min:0,         max:3.5,      label:'J2 肩'   },
  { name:'elbow_flex',    xyz:[0,0.11257,0.028],  rpy:[1.57079,0,0],       axis:[1,0,0], min:-Math.PI,  max:0,        label:'J3 肘'   },
  { name:'wrist_flex',    xyz:[0,0.0052,0.1349],  rpy:[-1,0,0],            axis:[1,0,0], min:-2.5,      max:1.2,      label:'J4 腕俯仰' },
  { name:'wrist_roll',    xyz:[0,-0.0601,0],      rpy:[0,1.57079,0],       axis:[0,1,0], min:-Math.PI,  max:Math.PI,  label:'J5 腕滚转' },
  { name:'gripper',       xyz:[-0.0202,-0.0244,0],rpy:[0,Math.PI,0],       axis:[0,0,1], min:-0.2,      max:2,        label:'J6 夹爪' },
];
const POSE = {
  home:  [ 0,    0.285, -0.792,  1.200,  0,     0.35],  // 中景待机
  close: [ 0,    0.452, -0.635,  0.915,  0,     0.35],  // 特写
  far:   [ 0,    0.431, -0.894,  1.200,  0,     0.35],  // 高位拉远（升降）
  top:   [ 0,    0.663, -1.009,  1.200,  0,     0.35],  // 高位俯拍
  low:   [ 0,    0.000, -0.297,  0.793,  0,     0.35],  // 低位仰拍
  orbL:  [-0.30, 0.593, -0.980,  1.200,  0.552, 0.35],  // 弧拍·左（荷兰角）
  orb0:  [ 0,    0.000, -0.639,  1.200,  0,     0.35],  // 弧拍·中
  orbR:  [ 0.30, 0.593, -0.980,  1.200, -0.552, 0.35],  // 弧拍·右（荷兰角）
  swpA:  [-0.55, 0.350, -0.850,  1.050,  0,     0.35],  // 横移扫掠·起
  swpB:  [ 0.55, 0.350, -0.850,  1.050,  0,     0.35],  // 横移扫掠·止
};
const withGrip = (p, g) => p.map((v, i) => i === 5 ? g : v);
const DirectorAI = (() => {
  const K = (p, d) => [p, d]; // [位姿, 段时长]

  function buildShots(defs, timeScale) {
    let t = 0, last = POSE.home;
    return defs.map(d => {
      const kfs = [[last, t]];                 // 起点 = 上一分镜的结束机位
      let cur = t;
      const frames = d.moves.map(mv => {
        cur += Math.max(0.7, mv[1] * timeScale);
        last = mv[0];
        return [mv[0], cur];
      });
      const shot = { name: d.name, tech: d.tech, desc: d.desc, keyframes: kfs.concat(frames), t0: t, t1: cur };
      t = cur;
      return shot;
    });
  }

  const library = [
    { keys: ['环绕', '弧拍', '绕', 'orbit', 'arc', '荷兰角'],
      title: '荷兰角弧拍', tech: 'ARC ORBIT',
      make: ts => buildShots([
        { name: '入弧', tech: 'ARC ORBIT', desc: '滑入弧拍起点，建立被摄体关系', moves: [K(POSE.orb0, 2.2), K(POSE.orbL, 2.6)] },
        { name: '弧拍过肩', tech: 'ARC ORBIT', desc: '带荷兰角的环绕弧拍，末端轨迹保持圆润', moves: [K(POSE.orb0, 2.4), K(POSE.orbR, 2.8)] },
        { name: '收尾回中', tech: 'RECOVER', desc: '回到中景待机位', moves: [K(POSE.home, 2.6)] },
      ], ts) },
    { keys: ['推近', '特写', '靠近', 'dolly', 'close', 'macro'],
      title: '缓推特写', tech: 'DOLLY IN',
      make: ts => buildShots([
        { name: '建立镜头', tech: 'ESTABLISH', desc: '中景构图，停留建立预期', moves: [K(withGrip(POSE.home, 0.35), 1.4)] },
        { name: '推轨靠近', tech: 'DOLLY IN', desc: '匀速推近至特写机位，视线始终锁定被摄体', moves: [K(POSE.close, 4.2)] },
        { name: '特写律动', tech: 'INSERT', desc: '夹爪微动作，画面呼吸感', moves: [K(withGrip(POSE.close, 0.10), 1.0), K(withGrip(POSE.close, 0.95), 1.2), K(withGrip(POSE.close, 0.35), 0.9)] },
        { name: '复位', tech: 'RECOVER', desc: '回到中景待机位', moves: [K(POSE.home, 2.8)] },
      ], ts) },
    { keys: ['拉远', '拉镜', '升高', 'pull', 'crane', 'out'],
      title: '升降拉远', tech: 'CRANE OUT',
      make: ts => buildShots([
        { name: '特写起手', tech: 'INSERT', desc: '从特写机位开始', moves: [K(POSE.close, 2.2)] },
        { name: '升降拉远', tech: 'CRANE OUT', desc: '边升边拉，空间关系展开', moves: [K(POSE.far, 4.0), K(withGrip(POSE.far, 0.35), 1.4)] },
        { name: '复位', tech: 'RECOVER', desc: '回到中景待机位', moves: [K(POSE.home, 3.0)] },
      ], ts) },
    { keys: ['俯拍', '顶拍', '俯视', 'top', 'overhead'],
      title: '高位俯拍', tech: 'TOP SHOT',
      make: ts => buildShots([
        { name: '升镜', tech: 'TOP SHOT', desc: '机位抬升，俯视被摄体', moves: [K(POSE.top, 3.6)] },
        { name: '俯视停留', tech: 'HOLD', desc: '高位凝视，微滚转增加动感', moves: [K(withGrip(POSE.top, 0.35).map((v,i)=>i===4?0.3:v), 1.6), K(withGrip(POSE.top, 0.35), 1.2)] },
        { name: '复位', tech: 'RECOVER', desc: '回到中景待机位', moves: [K(POSE.home, 3.0)] },
      ], ts) },
    { keys: ['仰拍', '低角度', 'low'],
      title: '低位仰拍', tech: 'LOW ANGLE',
      make: ts => buildShots([
        { name: '下沉', tech: 'LOW ANGLE', desc: '机位下沉贴台，视线微仰', moves: [K(POSE.low, 3.2)] },
        { name: '仰拍停留', tech: 'HOLD', desc: '低角度凝视，纪念碑感', moves: [K(withGrip(POSE.low, 0.35), 2.0)] },
        { name: '复位', tech: 'RECOVER', desc: '回到中景待机位', moves: [K(POSE.home, 2.8)] },
      ], ts) },
    { keys: ['扫掠', '横移', '横扫', 'sweep', 'truck'],
      title: '横移扫掠', tech: 'TRUCK SWEEP',
      make: ts => buildShots([
        { name: '入位', tech: 'TRUCK', desc: '移至扫掠起点', moves: [K(POSE.swpA, 2.6)] },
        { name: '匀速扫掠', tech: 'TRUCK SWEEP', desc: '被摄体横穿画面，视差拉满', moves: [K(POSE.swpB, 4.6)] },
        { name: '复位', tech: 'RECOVER', desc: '回到中景待机位', moves: [K(POSE.home, 2.6)] },
      ], ts) },
  ];

  const epic = ts => buildShots([
    { name: '建立 · 全景', tech: 'ESTABLISH', desc: '高位交代全局，缓降至中景', moves: [K(POSE.far, 2.4), K(POSE.home, 3.0)] },
    { name: '推近 · 特写', tech: 'DOLLY IN', desc: '匀速推近，夹爪微动点睛', moves: [K(POSE.close, 3.8), K(withGrip(POSE.close, 0.10), 0.9), K(withGrip(POSE.close, 0.95), 1.1), K(withGrip(POSE.close, 0.35), 0.8)] },
    { name: '弧拍 · 荷兰角', tech: 'ARC ORBIT', desc: '环绕弧拍过肩，动态失衡美', moves: [K(POSE.orb0, 2.2), K(POSE.orbL, 2.6), K(POSE.orb0, 2.2), K(POSE.orbR, 2.8)] },
    { name: '定格 · 收尾', tech: 'FINALE', desc: '升镜俯拍后落回中景，完成叙事闭环', moves: [K(POSE.top, 3.0), K(withGrip(POSE.top, 0.35), 1.4), K(POSE.home, 2.8)] },
  ], ts);

  async function generatePlan(text) {
    // —— 模拟 LLM 推理延迟；接入真实模型时替换为 API 调用 ——
    await new Promise(r => setTimeout(r, 700 + Math.random() * 700));
    const s = (text || '').toLowerCase();
    let ts = 1.0, speedNote = '标准速度';
    if (/慢|缓慢|优雅|slow/.test(s)) { ts = 1.55; speedNote = '舒缓 0.65×'; }
    if (/快|快速|迅速|fast|quick/.test(s)) { ts = 0.62; speedNote = '利落 1.6×'; }
    const repeat = /两次|两遍|重复|twice|again|x2|×2/.test(s) ? 2 : 1;

    let entry = library.find(e => e.keys.some(k => s.includes(k)));
    let shots, title, tech;
    if (!entry || /大片|完整|全部|广告|epic|film/.test(s)) {
      title = '产品大片 · 四幕'; shots = epic(ts);
    } else { title = entry.title; shots = entry.make(ts); }

    if (repeat === 2) {
      const base = shots;
      const offset = base[base.length - 1].t1;
      const round2 = base.map(sh => ({
        ...sh, name: sh.name + ' · 二刷',
        keyframes: sh.keyframes.map(f => [f[0], f[1] + offset]),
        t0: sh.t0 + offset, t1: sh.t1 + offset,
      }));
      shots = base.concat(round2);
    }
    const total = shots[shots.length - 1].t1;
    return {
      title,
      summary: `${shots.length} 个分镜 · 总时长约 ${total.toFixed(1)}s · ${speedNote} · Catmull-Rom 平滑插值${repeat > 1 ? ' · 重复 2 遍' : ''}`,
      shots, total,
    };
  }
  return { generatePlan };
})();
function planToWaypoints(plan) {
  const wps = [];
  plan.shots.forEach(sh => sh.keyframes.forEach(([q, t]) => wps.push({ t, q: [...q] })));
  return wps;
}
function buildSamples(waypoints, smooth) {
  const W = waypoints, n = W.length;
  const tang = W.map((w, i) => {
    const m = [];
    for (let j = 0; j < 6; j++) {
      let d;
      if (i === 0) d = n > 1 ? (W[1].q[j] - W[0].q[j]) / Math.max(1e-6, W[1].t - W[0].t) : 0;
      else if (i === n - 1) d = (W[n - 1].q[j] - W[n - 2].q[j]) / Math.max(1e-6, W[n - 1].t - W[n - 2].t);
      else d = (W[i + 1].q[j] - W[i - 1].q[j]) / Math.max(1e-6, W[i + 1].t - W[i - 1].t);
      m.push(d * smooth);
    }
    return m;
  });
  const dt = 1 / 30, samples = [];
  for (let i = 0; i < n - 1; i++) {
    const a = W[i], b = W[i + 1], T = b.t - a.t;
    if (T <= 1e-6) continue;
    const steps = Math.max(1, Math.round(T / dt));
    for (let s = 0; s < steps; s++) {
      const u = s / steps, t = a.t + u * T;
      const h00 = 2 * u ** 3 - 3 * u ** 2 + 1, h10 = u ** 3 - 2 * u ** 2 + u;
      const h01 = -2 * u ** 3 + 3 * u ** 2, h11 = u ** 3 - u ** 2;
      const q = [];
      for (let j = 0; j < 6; j++)
        q.push(h00 * a.q[j] + h10 * T * tang[i][j] + h01 * b.q[j] + h11 * T * tang[i + 1][j]);
      samples.push({ t, q });
    }
  }
  samples.push({ t: W[n - 1].t, q: [...W[n - 1].q] });
  return { samples, dur: W[n - 1].t };
}
const assert=(c,m)=>{if(!c){console.error('FAIL:',m);process.exit(1)}};
const inLim=(q)=>q.every((v,i)=>v>=JOINTS[i].min-0.15&&v<=JOINTS[i].max+0.15&&!Number.isNaN(v));
async function check(text){
  const plan=await DirectorAI.generatePlan(text);
  assert(plan.shots.length>0,'no shots');
  let prevLast=null,prevT=0;
  for(const sh of plan.shots){
    assert(sh.t1>sh.t0,'shot duration '+sh.name);
    sh.keyframes.forEach(([q,t])=>{assert(inLim(q),'q out of limits '+sh.name);assert(t>=prevT-1e-9,'time not monotonic');prevT=t;});
    if(prevLast)assert(sh.keyframes[0][0]===prevLast,'chain broken at '+sh.name);
    prevLast=sh.keyframes[sh.keyframes.length-1][0];
  }
  for(const sm of[0,0.35,0.7,1]){
    const tr=buildSamples(planToWaypoints(plan),sm);
    assert(tr.samples.length>2,'samples too few');
    let t=-1;for(const s of tr.samples){assert(s.t>t-1e-9,'sample time order');assert(inLim(s.q),'sample q limits (smooth='+sm+')');t=s.t;}
    assert(Math.abs(tr.dur-plan.total)<1e-6,'dur mismatch');
  }
  console.log('OK:',text,'->',plan.title,'|',plan.shots.length,'shots |',plan.total.toFixed(1)+'s');
}
(async()=>{
  await check('缓慢推近，给产品一个特写');
  await check('荷兰角环绕拍一圈');
  await check('俯拍展示，然后复位');
  await check('来一条完整产品大片');
  await check('快速横移扫掠两次');
  await check('随便一句话没有关键词');
  console.log('ALL LOGIC TESTS PASSED');
})();

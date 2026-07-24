
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

/* ============================================================
   CONFIG — 全部可调常量集中于此
   ============================================================ */
const CONFIG = {
  // SO-ARM100 官方网格（Simulation/SO100/assets，与 URDF 对齐），双 CDN 互为备份
  MESH_BASES: [
    'https://cdn.jsdelivr.net/gh/TheRobotStudio/SO-ARM100@main/Simulation/SO100/assets/',
    'https://raw.githubusercontent.com/TheRobotStudio/SO-ARM100/main/Simulation/SO100/assets/',
  ],
  // —— DimOS / A1Z 真实控制接口（文档：https://dimensionalos.mintlify.site/platforms/arms/a1z）
  // DimOS McpServer 将所有 @skill 以 MCP tools 形式暴露在 HTTP 9990 端口（JSON-RPC）。
  // 本地等价命令：dimos mcp list-tools / dimos mcp call <skill> --arg k=v
  MCP_ENDPOINT: 'http://127.0.0.1:9990/mcp',
  // 技能名需与 `dimos mcp list-tools` 实际输出一致，接入真机时按输出修改：
  MCP_SKILLS: { trajectory: 'execute_trajectory', joints: 'set_joint_positions', estop: 'estop' },
  // WebSocket 备用通道：未来由本地 bridge.py（包装 Dimos.connect().skills.*）提供
  WS_ENDPOINT: 'ws://127.0.0.1:8765',
  STREAM_HZ: 10,          // 执行期向真实机械臂推送目标的频率
  TRAIL_MAX: 900,         // 末端轨迹最大点数
};

/* SO-ARM100 运动学 —— 直接取自官方 URDF（Simulation/SO100/so100.urdf），米制、Z-up */
const JOINTS = [
  { name:'shoulder_pan',  xyz:[0,-0.0452,0.0165], rpy:[1.57079,0,0],       axis:[0,1,0], min:-2,        max:2,        label:'J1 基座' },
  { name:'shoulder_lift', xyz:[0,0.1025,0.0306],  rpy:[-1.8,0,0],          axis:[1,0,0], min:0,         max:3.5,      label:'J2 肩'   },
  { name:'elbow_flex',    xyz:[0,0.11257,0.028],  rpy:[1.57079,0,0],       axis:[1,0,0], min:-Math.PI,  max:0,        label:'J3 肘'   },
  { name:'wrist_flex',    xyz:[0,0.0052,0.1349],  rpy:[-1,0,0],            axis:[1,0,0], min:-2.5,      max:1.2,      label:'J4 腕俯仰' },
  { name:'wrist_roll',    xyz:[0,-0.0601,0],      rpy:[0,1.57079,0],       axis:[0,1,0], min:-Math.PI,  max:Math.PI,  label:'J5 腕滚转' },
  { name:'gripper',       xyz:[-0.0202,-0.0244,0],rpy:[0,Math.PI,0],       axis:[0,0,1], min:-0.2,      max:2,        label:'J6 夹爪' },
];
/* 各 link 对应的网格文件（URDF visual，材质：print=3D打印件 / motor=舵机） */
const LINK_MESHES = [
  [ ['Base.stl','print'], ['Base_Motor.stl','motor'] ],
  [ ['Rotation_Pitch.stl','print'], ['Rotation_Pitch_Motor.stl','motor'] ],
  [ ['Upper_Arm.stl','print'], ['Upper_Arm_Motor.stl','motor'] ],
  [ ['Lower_Arm.stl','print'], ['Lower_Arm_Motor.stl','motor'] ],
  [ ['Wrist_Pitch_Roll.stl','print'], ['Wrist_Pitch_Roll_Motor.stl','motor'] ],
  [ ['Fixed_Jaw.stl','print'], ['Fixed_Jaw_Motor.stl','motor'] ],
  [ ['Moving_Jaw.stl','print'] ],
];

/* 基准位姿 —— 由逆解数值求解器针对被摄物 S=(0,-0.22,0.105) 优化验证：
   各镜头瞄准误差 ≤5°，镜头间线性插值中点瞄准误差 ≤6°（见 .devcheck/solve5.mjs） */
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

/* ============================================================
   DirectorAI — 导演指令 → 摄影方案（当前为本地规则模拟）
   ┌─────────────────────────────────────────────────────────┐
   │ 接入真实 LLM 时：仅需重写 generatePlan(text)，保持返回    │
   │ 结构不变即可（例如 fetch 你的模型 API，把分镜 JSON 映射   │
   │ 为 shots 数组，keyframes 引用 POSE 中的机位或自定义关节角）│
   └─────────────────────────────────────────────────────────┘
   ShotPlan = { title, summary, shots: Shot[] }
   Shot     = { name, tech, desc, keyframes: [[q1..q6, t]...], t0, t1 }
   keyframes 的 t 为方案全局时间轴上的累计秒数（执行器按此插值）
   ============================================================ */
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

/* ============================================================
   Kinematics — URDF 关节链（three.js 场景图层级即正运动学）
   URDF joint: parent → T(xyz)·R(rpy) → 绕 axis 转 q → child
   ============================================================ */
const AXIS_VEC = JOINTS.map(j => new THREE.Vector3(...j.axis).normalize());
const clampQ = (q, i) => Math.min(JOINTS[i].max, Math.max(JOINTS[i].min, q));

function buildKinematics(root) {
  const linkGroups = [], rotors = [];
  const base = new THREE.Group(); base.name = 'link_base';
  root.add(base); linkGroups.push(base);
  let parent = base;
  for (let i = 0; i < 6; i++) {
    const j = JOINTS[i];
    const origin = new THREE.Group();
    origin.position.set(...j.xyz);
    origin.rotation.set(j.rpy[0], j.rpy[1], j.rpy[2], 'ZYX'); // URDF rpy 约定 = Rz(y)·Ry(p)·Rx(r)
    parent.add(origin);
    const rotor = new THREE.Group();
    origin.add(rotor); rotors.push(rotor);
    const link = new THREE.Group(); link.name = 'link_' + j.name;
    rotor.add(link); linkGroups.push(link);
    parent = link;
  }
  const tcp = new THREE.Object3D();           // 末端执行器参考点（与轨迹求解器一致：jaw 沿 -Y 4.5cm）
  tcp.position.set(0, -0.045, 0);
  linkGroups[6].add(tcp);
  const camMount = new THREE.Object3D();      // 腕部相机：挂在 gripper link（不随夹爪开合摆动）
  // 位置 = URDF 指尖参考点（jaw 关节原点 + J6=0.35 时的 -Y 4.5cm 偏移，换算到 gripper 系）；
  // 朝向 = Rz(-0.35)·Rx(-90°)，使镜头光轴与轨迹求解器的瞄准方向严格一致（各镜头瞄准误差 ≤5°，已数值验证）
  camMount.position.set(-0.0356, -0.0667, 0);
  camMount.rotation.set(-Math.PI / 2, 0, -0.35, 'ZXY');
  linkGroups[5].add(camMount);
  return { linkGroups, rotors, tcp, camMount };
}

/* ============================================================
   RobotScene — 影棚级场景：三点布光 / PBR 环境 / 被摄静物
   ============================================================ */
const stageEl = document.getElementById('viewport');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.12;
stageEl.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b0b0d);
scene.fog = new THREE.Fog(0x0b0b0d, 1.5, 3.6);

const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 20);
camera.position.set(0.52, 0.40, 0.66);
camera.layers.enable(1); // layer 1 = 轨迹线/预览线（腕部相机不可见）

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0, 0.13, 0.06);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 0.25;
controls.maxDistance = 2.4;
controls.maxPolarAngle = 1.52;

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;

// —— 灯光：暖金主光 / 中性补光 / 香槟轮廓光 ——
const keyLight = new THREE.SpotLight(0xffe9c4, 30, 7, 0.55, 1.0);
keyLight.position.set(0.75, 1.05, 0.55);
keyLight.castShadow = true;
keyLight.shadow.mapSize.set(2048, 2048);
keyLight.shadow.bias = -0.0004;
keyLight.shadow.camera.near = 0.2;
keyLight.shadow.camera.far = 4;
scene.add(keyLight);
keyLight.target.position.set(0, 0.08, 0.1);
scene.add(keyLight.target);

const fillLight = new THREE.DirectionalLight(0xd8d4cc, 0.85);
fillLight.position.set(-0.9, 0.5, -0.4);
scene.add(fillLight);

const rimLight = new THREE.SpotLight(0xd8b25c, 22, 7, 0.7, 1.0);
rimLight.position.set(-0.65, 0.85, -0.75);
scene.add(rimLight);
rimLight.target.position.set(0, 0.15, 0);
scene.add(rimLight.target);

scene.add(new THREE.HemisphereLight(0x35322c, 0x0b0b0d, 0.5));

// —— 地面 / 舞台 ——
const ground = new THREE.Mesh(
  new THREE.CircleGeometry(2.4, 96),
  new THREE.MeshStandardMaterial({ color: 0x0f0f11, roughness: 0.95, metalness: 0 })
);
ground.rotation.x = -Math.PI / 2;
ground.receiveShadow = true;
scene.add(ground);

const grid = new THREE.PolarGridHelper(1.2, 16, 9, 96, 0x2c2c30, 0x1c1c20);
grid.position.y = 0.001;
grid.material.transparent = true;
grid.material.opacity = 0.45;
scene.add(grid);

const stageDisc = new THREE.Mesh(
  new THREE.CylinderGeometry(0.135, 0.14, 0.014, 96),
  new THREE.MeshStandardMaterial({ color: 0x17171a, roughness: 0.55, metalness: 0.35 })
);
stageDisc.position.y = 0.007;
stageDisc.castShadow = true;
stageDisc.receiveShadow = true;
scene.add(stageDisc);

const MAT = {
  print: new THREE.MeshStandardMaterial({ color: 0xe7dfd0, roughness: 0.52, metalness: 0.06 }),
  motor: new THREE.MeshStandardMaterial({ color: 0x17171b, roughness: 0.38, metalness: 0.55 }),
  accent: new THREE.MeshStandardMaterial({ color: 0xd8b25c, roughness: 0.3, metalness: 0.8, emissive: 0x3a2c10, emissiveIntensity: 0.45 }),
};
const stageRing = new THREE.Mesh(new THREE.TorusGeometry(0.135, 0.0012, 12, 128), MAT.accent);
stageRing.rotation.x = Math.PI / 2;
stageRing.position.y = 0.0142;
scene.add(stageRing);

// —— 被摄静物：S=(0,-0.22,0.105) URDF 系 → three 系 (0,0.105,0.22) ——
(function buildSubject() {
  const ped = new THREE.Mesh(
    new THREE.CylinderGeometry(0.045, 0.052, 0.085, 64),
    new THREE.MeshStandardMaterial({ color: 0xcfc6b4, roughness: 0.75, metalness: 0.02 })
  );
  ped.position.set(0, 0.0425, 0.22);
  ped.castShadow = true; ped.receiveShadow = true;
  const obj = new THREE.Mesh(
    new THREE.SphereGeometry(0.02, 48, 32),
    new THREE.MeshPhysicalMaterial({ color: 0x0e0e10, roughness: 0.12, metalness: 0.2, clearcoat: 1, clearcoatRoughness: 0.08 })
  );
  obj.position.set(0, 0.105, 0.22);
  obj.castShadow = true;
  const halo = new THREE.Mesh(new THREE.TorusGeometry(0.026, 0.0012, 12, 64), MAT.accent.clone());
  halo.rotation.x = Math.PI / 2;
  halo.position.set(0, 0.0865, 0.22);
  const spot = new THREE.SpotLight(0xfff0d8, 8, 3, 0.32, 0.9);
  spot.position.set(0.3, 0.55, 0.52);
  spot.target = obj;
  scene.add(ped, obj, halo, spot);
})();

// —— 机械臂本体 ——
const robotRoot = new THREE.Group();
robotRoot.rotation.x = -Math.PI / 2; // URDF Z-up → three.js Y-up
scene.add(robotRoot);
const kin = buildKinematics(robotRoot);
function setAngles(q) {
  for (let i = 0; i < 6; i++) rotorsSet(kin.rotors[i], clampQ(q[i] ?? 0, i), i);
}
function rotorsSet(rotor, q, i) {
  rotor.quaternion.setFromAxisAngle(AXIS_VEC[i], q);
}

/* STL 加载（双 CDN 互为备份）；失败时降级为程序化胶囊臂（运动学不变） */
const veilFill = document.getElementById('vBarFill');
const veilSub = document.getElementById('vSub');
async function loadArmMeshes() {
  const loader = new STLLoader();
  const total = LINK_MESHES.flat().length;
  let done = 0;
  const tick = () => { done++; veilFill.style.width = Math.round(done / total * 100) + '%'; };
  const loadOne = async file => {
    for (const base of CONFIG.MESH_BASES) {
      try { return await loader.loadAsync(base + file); } catch (e) { /* 换下一个 CDN */ }
    }
    return null;
  };
  const jobs = [];
  LINK_MESHES.forEach((files, li) => files.forEach(([file, kind]) => {
    jobs.push(loadOne(file).then(geo => {
      tick();
      if (!geo) return;
      const mesh = new THREE.Mesh(geo, MAT[kind]);
      mesh.castShadow = true;
      kin.linkGroups[li].add(mesh);
    }));
  }));
  await Promise.all(jobs);
  const loaded = kin.linkGroups.reduce((n, g) => n + g.children.filter(c => c.isMesh).length, 0);
  if (loaded < total) {
    buildProceduralArm();
    return loaded === 0 ? 'procedural' : 'partial';
  }
  return 'stl';
}
function buildProceduralArm() {
  kin.linkGroups.forEach(g => g.clear());
  const baseM = new THREE.Mesh(new THREE.CylinderGeometry(0.052, 0.058, 0.05, 48), MAT.print);
  baseM.position.y = 0.025; baseM.castShadow = true;
  kin.linkGroups[0].add(baseM);
  const NEXT = [JOINTS[1].xyz, JOINTS[2].xyz, JOINTS[3].xyz, JOINTS[4].xyz, JOINTS[5].xyz, [0, -0.045, 0]];
  NEXT.forEach((n, k) => {
    const g = kin.linkGroups[k + 1];
    const v = new THREE.Vector3(...n);
    const len = v.length();
    const cap = new THREE.Mesh(new THREE.CapsuleGeometry(Math.max(0.007, 0.016 - k * 0.0016), len, 6, 16), k % 2 ? MAT.motor : MAT.print);
    cap.castShadow = true;
    cap.position.copy(v.clone().multiplyScalar(0.5));
    cap.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), v.clone().normalize());
    g.add(cap);
    const hub = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.009, 0.02 - k * 0.0016), 24, 16), MAT.accent);
    hub.castShadow = true;
    g.add(hub);
  });
  // 保留 tcp / camMount（clear 会移除它们，需重新挂载）
  kin.linkGroups[6].add(kin.tcp);
  kin.linkGroups[5].add(kin.camMount);
}

function onResize() {
  const w = stageEl.clientWidth, h = stageEl.clientHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', onResize);
onResize();

/* ============================================================
   TrailRenderer — 末端执行器发光轨迹（加色混合暖金渐变）
   仅在 layer 1：主视角可见，腕部相机不可见
   ============================================================ */
const LAYER_FX = 1;
const trail = (() => {
  const MAX = CONFIG.TRAIL_MAX;
  const pts = [];
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(MAX * 3);
  const col = new Float32Array(MAX * 3);
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  const line = new THREE.Line(geo, new THREE.LineBasicMaterial({
    vertexColors: true, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
  }));
  line.layers.set(LAYER_FX);
  line.frustumCulled = false;
  scene.add(line);
  // 轨迹头部光晕 sprite
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const ctx = c.getContext('2d');
  const grad = ctx.createRadialGradient(32, 32, 0, 32, 32, 32);
  grad.addColorStop(0, 'rgba(255,232,175,1)');
  grad.addColorStop(0.35, 'rgba(240,217,168,.55)');
  grad.addColorStop(1, 'rgba(216,178,92,0)');
  ctx.fillStyle = grad; ctx.fillRect(0, 0, 64, 64);
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
    map: new THREE.CanvasTexture(c), blending: THREE.AdditiveBlending, depthWrite: false, transparent: true,
  }));
  sprite.scale.setScalar(0.04);
  sprite.layers.set(LAYER_FX);
  sprite.visible = false;
  scene.add(sprite);
  function refresh() {
    const n = pts.length;
    for (let i = 0; i < n; i++) {
      const p = pts[i], f = n <= 1 ? 1 : i / (n - 1);
      pos[i * 3] = p.x; pos[i * 3 + 1] = p.y; pos[i * 3 + 2] = p.z;
      col[i * 3] = 0.06 + 0.9 * f * f;
      col[i * 3 + 1] = 0.045 + 0.68 * f * f;
      col[i * 3 + 2] = 0.02 + 0.34 * f * f;
    }
    geo.attributes.position.needsUpdate = true;
    geo.attributes.color.needsUpdate = true;
    geo.setDrawRange(0, n);
    if (n) { sprite.position.copy(pts[n - 1]); sprite.visible = true; }
  }
  return {
    push(p) {
      const last = pts[pts.length - 1];
      if (last && last.distanceToSquared(p) < 9e-8) return; // <0.3mm 不记
      pts.push(p.clone());
      if (pts.length > MAX) pts.shift();
      refresh();
    },
    clear() { pts.length = 0; geo.setDrawRange(0, 0); sprite.visible = false; },
  };
})();

/* 方案预览轨迹（虚线）：执行前展示「优化后」的完整运动路径 */
const preview = (() => {
  const geo = new THREE.BufferGeometry();
  const line = new THREE.Line(geo, new THREE.LineDashedMaterial({
    color: 0xd8b25c, dashSize: 0.007, gapSize: 0.005, transparent: true, opacity: 0.3,
  }));
  line.layers.set(LAYER_FX);
  line.frustumCulled = false;
  line.visible = false;
  scene.add(line);
  return {
    set(points) {
      geo.setFromPoints(points);
      line.computeLineDistances();
      line.visible = points.length > 1;
    },
    hide() { line.visible = false; },
  };
})();

/* ============================================================
   Trajectory — 关键帧 → 平滑时间序列
   每关节三次 Hermite；切线 = Catmull-Rom 有限差分 × 平滑度
   （平滑度 0 = 逐段缓动启停·机械感；100% = 流畅贯通·摄影师手感）
   ============================================================ */
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

/* FK 取样（用于预览线 / 不依赖渲染帧） */
const _fkV = new THREE.Vector3();
function fkTcp(q) {
  setAngles(q);
  robotRoot.updateMatrixWorld(true);
  return kin.tcp.getWorldPosition(_fkV).clone();
}

/* ============================================================
   Executor — 时间轴执行器：速度倍率 / 暂停 / 分镜追踪
   ============================================================ */
const executor = (() => {
  let traj = null, planRef = null, t = 0, playing = false, curShot = -1;
  function sample(time) {
    const s = traj.samples;
    let lo = 0, hi = s.length - 1;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (s[mid].t < time) lo = mid + 1; else hi = mid; }
    const i = Math.max(1, lo), a = s[i - 1], b = s[Math.min(i, s.length - 1)];
    const f = b.t > a.t ? Math.min(1, Math.max(0, (time - a.t) / (b.t - a.t))) : 1;
    return a.q.map((v, j) => v + (b.q[j] - v) * f);
  }
  return {
    get playing() { return playing; },
    get plan() { return planRef; },
    load(plan, smooth) { planRef = plan; traj = buildSamples(planToWaypoints(plan), smooth); t = 0; curShot = -1; },
    rebuild(smooth) { if (planRef) traj = buildSamples(planToWaypoints(planRef), smooth); },
    start() { if (traj) { playing = true; curShot = -1; } },
    pause() { playing = false; },
    resume() { playing = true; },
    stop() { playing = false; traj = null; planRef = null; t = 0; },
    tick(dt, speed) {
      if (!playing || !traj) return null;
      t += dt * speed;
      let done = false;
      if (t >= traj.dur) { t = traj.dur; playing = false; done = true; }
      let si = -1;
      if (planRef) for (let k = 0; k < planRef.shots.length; k++) if (t >= planRef.shots[k].t0 - 1e-6) si = k;
      const shotChanged = si !== curShot; curShot = si;
      return { q: sample(t), done, shotIndex: si, shotChanged, progress: traj.dur ? t / traj.dur : 1 };
    },
  };
})();

/* ============================================================
   WristCam — 腕部虚拟相机（拍摄画面）+ 录制回放
   ============================================================ */
const wristCam = new THREE.PerspectiveCamera(46, 16 / 9, 0.015, 6);
kin.camMount.add(wristCam);
const wristRenderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
wristRenderer.setSize(384, 216);
wristRenderer.toneMapping = THREE.ACESFilmicToneMapping;
wristRenderer.toneMappingExposure = 1.15;
wristRenderer.domElement.id = 'wristCanvas';
document.querySelector('#resultCard .fc-body').prepend(wristRenderer.domElement);

const recInd = document.getElementById('recInd');
const recTime = document.getElementById('recTime');
const recorder = (() => {
  let frames = [], timer = null, t0 = 0;
  const fmt = s => String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(Math.floor(s % 60)).padStart(2, '0');
  return {
    get recording() { return !!timer; },
    get frameCount() { return frames.length; },
    start() {
      frames = []; t0 = performance.now();
      recInd.classList.add('on');
      timer = setInterval(() => {
        recTime.textContent = fmt((performance.now() - t0) / 1000);
        try { if (frames.length < 900) frames.push(wristRenderer.domElement.toDataURL('image/jpeg', 0.7)); } catch (e) { }
      }, 100);
    },
    stop() { clearInterval(timer); timer = null; recInd.classList.remove('on'); },
    frames: () => frames,
  };
})();

const replayImg = document.getElementById('replayImg');
const replayBar = document.querySelector('#replayBar');
let replayTimer = null;
function stopReplay() {
  if (replayTimer) { clearInterval(replayTimer); replayTimer = null; }
  replayImg.style.display = 'none';
  replayBar.style.display = 'none';
}
function replayFrames(frames, onDone) {
  stopReplay();
  if (!frames.length) { onDone && onDone(); return; }
  let i = 0;
  replayImg.style.display = 'block';
  replayBar.style.display = 'block';
  replayImg.src = frames[0];
  replayTimer = setInterval(() => {
    i++;
    if (i >= frames.length) { stopReplay(); onDone && onDone(); return; }
    replayImg.src = frames[i];
    replayBar.firstElementChild.style.width = (i / frames.length * 100) + '%';
  }, 100);
}

/* ============================================================
   RobotBridge — 真实机械臂控制接口（预留，默认 Mock）
   对齐 DimOS / Galaxea A1Z 文档（dimensionalos.mintlify.site/platforms/arms/a1z）：
   · A1Z = 6 轴 + 夹爪 → 7 元素数组 [j1..j6, gripper]，单位 rad
   · 关节限位(rad)：j1 ±2.094, j2 [0,3.142], j3 [-3.142,0], j4/j5 ±1.484, j6 ±2.007
   · DimOS McpServer 将 @skill 暴露为 MCP tools over HTTP :9990（JSON-RPC tools/list · tools/call）
   · CLI 等价物：dimos mcp list-tools / dimos mcp call <skill> --arg k=v
   · Python 等价物：Dimos.connect().skills.<skill>(...)
   视觉模型 SO-ARM100(5+1) → 指令模型 A1Z(6+1) 的适配层：mapVisualToRobot()
   ============================================================ */
const A1Z_LIMITS = [[-2.094, 2.094], [0, 3.142], [-3.142, 0], [-1.484, 1.484], [-1.484, 1.484], [-2.007, 2.007], [0, 1]];
function mapVisualToRobot(q6) {
  // j1..j5 直通；A1Z 第 6 腕轴在 SO-ARM100 上不存在 → 补 0；夹爪按行程归一化到 [0,1]
  const grip = Math.min(1, Math.max(0, (q6[5] - JOINTS[5].min) / (JOINTS[5].max - JOINTS[5].min)));
  const q7 = [q6[0], q6[1], q6[2], q6[3], q6[4], 0, grip];
  return q7.map((v, i) => Math.min(A1Z_LIMITS[i][1], Math.max(A1Z_LIMITS[i][0], v)));
}
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* —— Mock：本地回环，模拟延迟与响应（默认） —— */
class MockTransport {
  constructor() { this.lastCmd = null; }
  async connect() { await sleep(250); return { detail: '本地回环模拟' }; }
  async disconnect() { }
  async getJointState() { return mapVisualToRobot(visualQ); }
  async sendJointTargets(q7, opts = {}) { this.lastCmd = { type: 'joints', q7, opts }; await sleep(6); return { ok: true, simulated: true }; }
  async sendTrajectory(wps, opts = {}) { this.lastCmd = { type: 'trajectory', count: wps.length, opts }; await sleep(10); return { ok: true, simulated: true }; }
  async estop() { this.lastCmd = { type: 'estop' }; await sleep(4); return { ok: true, simulated: true }; }
}

/* —— MCP over HTTP：直连 DimOS McpServer（:9990，JSON-RPC） ——
   注意：浏览器跨域需服务端允许 CORS；若 DimOS 端未开，可在本地起一个
   透明代理（或改用 WebSocket 桥）。技能名以 `dimos mcp list-tools` 实测为准。 */
class McpHttpTransport {
  constructor(endpoint) { this.endpoint = endpoint || CONFIG.MCP_ENDPOINT; this.rpcId = 0; this.tools = []; }
  async rpc(method, params, timeout = 3000) {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), timeout);
    try {
      const res = await fetch(this.endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream' },
        body: JSON.stringify({ jsonrpc: '2.0', id: ++this.rpcId, method, params }),
        signal: ctrl.signal,
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return await res.json();
    } finally { clearTimeout(to); }
  }
  async connect() {                                  // 等价：dimos mcp list-tools
    const r = await this.rpc('tools/list', {});
    this.tools = (r.result && r.result.tools) || [];
    if (!this.tools.length) throw new Error('MCP 已连接但未发现工具');
    return { detail: this.tools.length + ' 个 MCP 工具' };
  }
  async disconnect() { }
  async call(skill, args) {                          // 等价：dimos mcp call <skill> --arg ...
    const r = await this.rpc('tools/call', { name: skill, arguments: args });
    if (r.error) throw new Error(r.error.message || 'MCP 调用失败');
    return r.result;
  }
  async getJointState() { return this.call(CONFIG.MCP_SKILLS.joints, { read: true }); } // 按真机技能签名调整
  async sendJointTargets(q7, opts = {}) { return this.call(CONFIG.MCP_SKILLS.joints, { positions: q7, duration: opts.duration ?? 0.1, speed: opts.speedScale ?? 1 }); }
  async sendTrajectory(wps, opts = {}) { return this.call(CONFIG.MCP_SKILLS.trajectory, { waypoints: wps, speed: opts.speedScale ?? 1 }); }
  async estop() { return this.call(CONFIG.MCP_SKILLS.estop, {}); }
}

/* —— WebSocket：预留给本地 bridge.py（未来实现，包装 Dimos.connect().skills.*） ——
   上行（JSON）：{type:'joint_targets', q:[7], duration, speed}
                 {type:'trajectory', waypoints:[[q1..q7,t]...], speed}
                 {type:'estop'}
   下行：       {type:'joint_state', q:[7]} · {type:'ack', ok, error?} */
class WsTransport {
  constructor(url) { this.url = url || CONFIG.WS_ENDPOINT; this.ws = null; this.onJointState = null; }
  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url); this.ws = ws;
      const to = setTimeout(() => { ws.close(); reject(new Error('连接超时')); }, 3000);
      ws.onopen = () => { clearTimeout(to); resolve({ detail: 'WebSocket 桥已连接' }); };
      ws.onerror = () => { clearTimeout(to); reject(new Error('无法连接 ' + this.url)); };
      ws.onclose = () => { };
      ws.onmessage = e => {
        try {
          const m = JSON.parse(e.data);
          if (m.type === 'joint_state' && this.onJointState) this.onJointState(m.q);
        } catch (_) { }
      };
    });
  }
  _send(o) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(o)); }
  async disconnect() { this.ws && this.ws.close(); }
  async getJointState() { this._send({ type: 'get_joint_state' }); }
  async sendJointTargets(q7, opts = {}) { this._send({ type: 'joint_targets', q: q7, duration: opts.duration ?? 0.1, speed: opts.speedScale ?? 1 }); }
  async sendTrajectory(wps, opts = {}) { this._send({ type: 'trajectory', waypoints: wps, speed: opts.speedScale ?? 1 }); }
  async estop() { this._send({ type: 'estop' }); }
}

/* —— Bridge 门面：模式切换 + 状态通知，上层只感知 6 轴视觉关节角 —— */
const bridge = (() => {
  let transport = new MockTransport(), mode = 'mock';
  const api = {
    get mode() { return mode; },
    onJointState: null,
    async setMode(m) {
      if (m === mode) return;
      setConn('busy', m === 'mcp' ? 'MCP 连接中…' : m === 'ws' ? 'WS 连接中…' : '本地模拟');
      try {
        const t = m === 'mock' ? new MockTransport() : m === 'mcp' ? new McpHttpTransport() : new WsTransport();
        t.onJointState = q => api.onJointState && api.onJointState(q);
        const info = await t.connect();
        await transport.disconnect().catch(() => { });
        transport = t; mode = m;
        setConn(m === 'mock' ? '' : 'ok', m === 'mock' ? '本地模拟' : (m === 'mcp' ? 'MCP · ' : 'WS · ') + info.detail);
        toast(m === 'mock' ? '已切换到本地模拟模式' : '已连接：' + info.detail);
      } catch (e) {
        setConn('err', (m === 'mcp' ? 'MCP' : 'WS') + ' 连接失败');
        toast('连接失败：' + e.message + '（端点见 CONFIG）', 'err');
        setSeg(mode);
      }
    },
    async sendJointTargets(q6, opts) { try { return await transport.sendJointTargets(mapVisualToRobot(q6), opts); } catch (e) { /* 静默：执行期高频调用 */ } },
    async sendTrajectory(wps, opts) { try { return await transport.sendTrajectory(wps, opts); } catch (e) { toast('轨迹发送失败：' + e.message, 'err'); } },
    async estop() { try { return await transport.estop(); } catch (e) { } },
    async getJointState() { try { return await transport.getJointState(); } catch (e) { return null; } },
  };
  return api;
})();

/* ============================================================
   UI — 对话 / 方案卡 / 控制条 / 状态机
   ============================================================ */
const msgsEl = document.getElementById('msgs');
const cmdInput = document.getElementById('cmdInput');
const sendBtn = document.getElementById('sendBtn');
const execBtn = document.getElementById('execBtn');
const pauseBtn = document.getElementById('pauseBtn');
const stopBtn = document.getElementById('stopBtn');
const smoothSlider = document.getElementById('smoothSlider');
const speedSlider = document.getElementById('speedSlider');
const connDot = document.getElementById('connDot');
const connText = document.getElementById('connText');
const resultCard = document.getElementById('resultCard');

const ICON_PAUSE = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';
const ICON_PLAY = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l11-6.5z"/></svg>';

let appState = 'idle';          // idle | planning | ready | executing | paused | done
let currentPlan = null;
let planCardEl = null;
let visualQ = new Array(6).fill(0);
let returnAnim = null;

const speed = () => speedSlider.value / 100;
const smooth = () => smoothSlider.value / 100;

let toastTimer = null;
function toast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show' + (type ? ' ' + type : '');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3200);
}
function setConn(cls, text) {
  connDot.className = 'dot' + (cls ? ' ' + cls : '');
  connText.textContent = text;
}
function setSeg(mode) {
  document.querySelectorAll('#modeSeg button').forEach(b => b.classList.toggle('on', b.dataset.mode === mode));
}
function setState(s) {
  appState = s;
  execBtn.disabled = !(s === 'ready' || s === 'done');
  execBtn.classList.toggle('ready', s === 'ready');
  execBtn.querySelector('span').textContent = s === 'done' ? '再执行' : '执行';
  pauseBtn.disabled = !(s === 'executing' || s === 'paused');
  stopBtn.disabled = !(s === 'executing' || s === 'paused');
}

/* —— 聊天消息 —— */
function scrollChat() { msgsEl.scrollTop = msgsEl.scrollHeight; }
function addUserMsg(text) {
  const el = document.createElement('div');
  el.className = 'msg user';
  el.textContent = text;
  msgsEl.appendChild(el); scrollChat();
}
function addTyping() {
  const el = document.createElement('div');
  el.className = 'msg ai';
  el.innerHTML = '<div class="who">DirectorX AI</div><div class="bubble"><span class="typing"><i></i><i></i><i></i></span></div>';
  msgsEl.appendChild(el); scrollChat();
  return el;
}
function renderPlanCard(plan) {
  const wrap = document.createElement('div');
  wrap.className = 'msg ai';
  let shotsHtml = '';
  plan.shots.forEach((sh, i) => {
    shotsHtml += '<div class="shot" data-i="' + i + '">'
      + '<div class="idx">' + (i + 1) + '</div>'
      + '<div class="body"><div class="name">' + sh.name + '<span class="tech">' + sh.tech + '</span></div>'
      + '<div class="desc">' + sh.desc + '</div>'
      + '<div class="params">时长 ' + (sh.t1 - sh.t0).toFixed(1) + 's · ' + sh.keyframes.length + ' 关键帧 · 平滑插值</div></div>'
      + '<div class="st">待执行</div></div>';
  });
  wrap.innerHTML = '<div class="who">DirectorX AI · 摄影方案</div>'
    + '<div class="plan"><div class="p-head"><span class="p-title">' + plan.title + '</span><span class="p-badge">本地模拟规划</span></div>'
    + '<div class="p-sub">' + plan.summary + '</div>' + shotsHtml
    + '<div class="p-foot"><span class="p-total">TOTAL ' + plan.total.toFixed(1) + 's · ' + plan.shots.length + ' SHOTS</span>'
    + '<button class="btn-gold p-exec"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l11-6.5z"/></svg>执行方案</button></div></div>';
  msgsEl.appendChild(wrap);
  wrap.querySelector('.p-exec').addEventListener('click', () => startExecution());
  planCardEl = wrap;
  scrollChat();
}
function setShotStatus(activeIdx, status) {
  if (!planCardEl) return;
  planCardEl.querySelectorAll('.shot').forEach(el => {
    const k = +el.dataset.i;
    el.classList.toggle('active', status === 'active' && k === activeIdx);
    el.classList.toggle('done', status === 'done' || (status === 'active' && k < activeIdx));
    const st = el.querySelector('.st');
    if (status === 'done' || (status === 'active' && k < activeIdx)) st.textContent = '完成';
    else if (status === 'active' && k === activeIdx) st.textContent = '执行中';
    else st.textContent = '待执行';
  });
}

/* —— 指令流：输入 → 方案 → 预览 —— */
async function submitCmd() {
  const text = cmdInput.value.trim();
  if (!text || appState === 'planning') return;
  if (appState === 'executing' || appState === 'paused') { toast('拍摄执行中，请先停止', 'warn'); return; }
  cmdInput.value = '';
  addUserMsg(text);
  setState('planning');
  const typing = addTyping();
  try {
    const plan = await DirectorAI.generatePlan(text);
    typing.remove();
    currentPlan = plan;
    renderPlanCard(plan);
    executor.load(plan, smooth());
    trail.clear();
    drawPreview();
    setState('ready');
  } catch (e) {
    typing.remove();
    toast('方案生成失败：' + e.message, 'err');
    setState('idle');
  }
}
function drawPreview() {
  if (!currentPlan) return;
  const traj = buildSamples(planToWaypoints(currentPlan), smooth());
  const pts = [];
  for (let i = 0; i < traj.samples.length; i += 3) pts.push(fkTcp(traj.samples[i].q));
  preview.set(pts);
  setAngles(visualQ); // FK 采样会改动姿态，恢复
}

/* —— 执行控制 —— */
async function startExecution() {
  if (!currentPlan || appState === 'executing') return;
  stopReplay();
  preview.hide();
  trail.clear();
  executor.load(currentPlan, smooth());
  executor.start();
  setState('executing');
  pauseBtn.innerHTML = ICON_PAUSE;
  resultCard.classList.remove('has-rec');
  recorder.start();
  // 整段轨迹下发真实机械臂（Mock 为回环记录；降采样至 ≤120 个路径点，[q1..q7, t] 格式）
  const traj = buildSamples(planToWaypoints(currentPlan), smooth());
  const step = Math.max(1, Math.floor(traj.samples.length / 120));
  const wps7 = traj.samples.filter((_, i) => i % step === 0).map(s => [...mapVisualToRobot(s.q), s.t]);
  bridge.sendTrajectory(wps7, { speedScale: speed() });
}
function finishExecution() {
  recorder.stop();
  setState('done');
  setShotStatus(-1, 'done');
  if (recorder.frameCount > 10) resultCard.classList.add('has-rec');
  toast('拍摄完成 · 已录制 ' + recorder.frameCount + ' 帧');
}
function stopExecution() {
  bridge.estop();
  executor.stop();
  recorder.stop();
  stopReplay();
  setState('ready');
  setShotStatus(-1, 'wait');
  drawPreview();
  returnAnim = { from: [...visualQ], t: 0, dur: 1.4 };
  toast('已停止 · 机械臂复位中');
}

/* —— HUD 关节遥测 —— */
const hudRows = [];
(function buildHud() {
  const jrowsEl = document.getElementById('jrows');
  JOINTS.forEach((j) => {
    const row = document.createElement('div');
    row.className = 'jrow';
    row.innerHTML = '<span class="jl">' + j.label + '</span><span class="jv">0.0°</span><span class="jbar"><i></i></span>';
    jrowsEl.appendChild(row);
    hudRows.push({ v: row.querySelector('.jv'), bar: row.querySelector('.jbar i'), min: j.min, max: j.max });
  });
})();
function updateHud(q) {
  for (let i = 0; i < 6; i++) {
    hudRows[i].v.textContent = (q[i] * 57.2958).toFixed(1) + '°';
    hudRows[i].bar.style.width = Math.min(100, Math.max(0, (q[i] - hudRows[i].min) / (hudRows[i].max - hudRows[i].min) * 100)) + '%';
  }
}

/* —— 控件绑定 —— */
sendBtn.addEventListener('click', submitCmd);
cmdInput.addEventListener('keydown', e => { if (e.key === 'Enter') submitCmd(); });
execBtn.addEventListener('click', () => { if (currentPlan) startExecution(); });
pauseBtn.addEventListener('click', () => {
  if (appState === 'executing') { executor.pause(); setState('paused'); pauseBtn.innerHTML = ICON_PLAY; }
  else if (appState === 'paused') { executor.resume(); setState('executing'); pauseBtn.innerHTML = ICON_PAUSE; }
});
stopBtn.addEventListener('click', stopExecution);
document.getElementById('replayBtn').addEventListener('click', () => {
  const frames = recorder.frames();
  if (frames.length) replayFrames(frames, () => { });
});
function bindSlider(el, label, fmt, onChange) {
  const upd = () => {
    const pct = (el.value - el.min) / (el.max - el.min) * 100;
    el.style.setProperty('--fill', pct + '%');
    label.textContent = fmt(el.value);
    onChange && onChange();
  };
  el.addEventListener('input', upd);
  upd();
}
bindSlider(speedSlider, document.getElementById('speedVal'), v => (v / 100).toFixed(2).replace(/0$/, '') + '×');
bindSlider(smoothSlider, document.getElementById('smoothVal'), v => v + '%', () => {
  if (!currentPlan) return;
  executor.rebuild(smooth());                    // 执行中也可实时改变平滑度（时间轴不变，连续性保持）
  if (appState === 'ready' || appState === 'done') drawPreview();
});
document.querySelectorAll('#modeSeg button').forEach(b => {
  b.addEventListener('click', () => {
    if (appState === 'executing' || appState === 'paused') { toast('拍摄执行中，无法切换连接模式', 'warn'); setSeg(bridge.mode); return; }
    setSeg(b.dataset.mode);
    bridge.setMode(b.dataset.mode);
  });
});

/* —— 欢迎消息 —— */
(function welcome() {
  const el = document.createElement('div');
  el.className = 'msg ai';
  el.innerHTML = '<div class="who">DirectorX AI</div><div class="bubble">'
    + '你好，导演。我是你的 AI 摄影指导。<br>描述你想要的镜头语言，我会生成分镜方案，并驱动 SO-ARM100 按真实运动学执行拍摄。'
    + '<div class="chips">'
    + '<button class="chip">缓慢推近，给产品一个特写</button>'
    + '<button class="chip">荷兰角环绕拍一圈</button>'
    + '<button class="chip">俯拍展示，然后复位</button>'
    + '<button class="chip">来一条完整产品大片</button>'
    + '</div></div>';
  msgsEl.appendChild(el);
  el.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => { cmdInput.value = c.textContent; submitCmd(); }));
})();

/* ============================================================
   主循环 + 初始化
   ============================================================ */
const clock = new THREE.Clock();
let streamAcc = 0;
const easeInOut = k => k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;

function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(clock.getDelta(), 0.05);
  controls.update();

  // 复位动画（停止后 / 开场）
  if (returnAnim) {
    returnAnim.t += dt;
    const k = easeInOut(Math.min(1, returnAnim.t / returnAnim.dur));
    visualQ = returnAnim.from.map((v, i) => v + (POSE.home[i] - v) * k);
    setAngles(visualQ);
    updateHud(visualQ);
    if (returnAnim.t >= returnAnim.dur) returnAnim = null;
  }

  const ev = executor.tick(dt, speed());
  if (ev) {
    visualQ = ev.q;
    setAngles(ev.q);
    robotRoot.updateMatrixWorld(true);
    trail.push(kin.tcp.getWorldPosition(_fkV));
    updateHud(ev.q);
    if (ev.shotChanged) setShotStatus(ev.shotIndex, 'active');
    streamAcc += dt;
    if (streamAcc >= 1 / CONFIG.STREAM_HZ) {   // 高频目标点流式下发（10Hz）
      streamAcc = 0;
      bridge.sendJointTargets(ev.q, { duration: 0.5, speedScale: speed() });
    }
    if (ev.done) finishExecution();
  }

  renderer.render(scene, camera);
  wristRenderer.render(scene, wristCam);
}

async function init() {
  setAngles(visualQ);
  updateHud(visualQ);
  animate();
  initWebcam();
  try {
    const status = await loadArmMeshes();
    veilSub.textContent = status === 'stl' ? '模型加载完成' : '模型加载失败 · 已启用程序化降级模型';
    if (status !== 'stl') toast('STL 未能加载，已降级为程序化模型（请检查网络）', 'warn');
  } catch (e) {
    buildProceduralArm();
    veilSub.textContent = '模型加载失败 · 已启用程序化降级模型';
  }
  await sleep(400);
  document.getElementById('veil').classList.add('gone');
  returnAnim = { from: [...visualQ], t: 0, dur: 2.2 };  // 开场：零位 → 中景待机
}
init();

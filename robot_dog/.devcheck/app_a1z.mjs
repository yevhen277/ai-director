import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
window.__dxBoot = true; // 引导握手：模块已成功加载

/* ============================================================
   CONFIG — 全部可调常量集中于此
   ============================================================ */
const CONFIG = {
  // GALAXEA A1Z 官方网格（A1Z_G1Z 带夹爪版，userguide-galaxea/URDF 仓库）：
  // 已内嵌本文件（base64，离线可用），以下 URL 仅为内嵌缺失时的备份
  MESH_BASES: [
    'https://raw.githubusercontent.com/userguide-galaxea/URDF/galaxea/main/A1Z/A1Z_G1Z/meshes/',
  ],
  // —— GALAXEA A1Z 真实控制接口 ——
  // 官方协议（GALAXEA-A1Z SDK gripper 分支 a1z/robots/server.py，经 tools/a1zctl 启动）：
  //   Unix socket /tmp/a1z.sock，换行结尾 JSON：请求 {"cmd":"…","args":{…}} → 响应 {"ok":bool,"data"|"error"}
  //   指令集：status | move(joints:[6]° 或 preset, speed rad/s) | gripper(value 0..1)
  //           | dance | estop | release | info | stop
  // 浏览器无法直连 Unix socket → 由同目录 a1z_bridge.py 原样透传为 HTTP：
  //   POST {A1Z_ENDPOINT}  Body: {"cmd":"move","args":{…}}（与官方 socket 协议逐字一致）
  A1Z_ENDPOINT: 'http://127.0.0.1:8766/a1z',
  // 官方 move_joints 速度上限：speed×1.875 ≤ 4.0 rad/s（前馈硬顶），留余量取 2.0
  A1Z_MOVE_MAX_SPEED: 2.0,
  // WebSocket 备用通道：预留（未来由 a1z_bridge.py --ws 提供，消息结构同官方协议）
  WS_ENDPOINT: 'ws://127.0.0.1:8765',
  STREAM_HZ: 10,          // 预留：执行期高频通道频率（当前官方协议按关键帧阻塞 move）
  TRAIL_MAX: 900,         // 末端轨迹最大点数
};

/* GALAXEA A1Z 运动学 —— 直接取自官方 URDF（userguide-galaxea/URDF · A1Z/A1Z_G1Z/urdf/A1Z_G1Z.urdf），
   米制、Z-up、全部关节 rpy=0。J4 采用 URDF 限位 ±1.309（±75°）——较 SDK 软限位 ±1.484（±85°）保守，二者同时满足。
   SDK 公开接口（command/move/get）全部使用 URDF 关节约定（关节符号 [1,1,-1,1,-1,1] 仅在 SDK 内部换算），
   因此本表角度可直接下发真机，无需任何符号变换。 */
const JOINTS = [
  { name:'arm_joint1', xyz:[0,0,0.075],       rpy:[0,0,0], axis:[0,0,1], min:-2.094, max:2.094,  label:'J1 Base Yaw' },
  { name:'arm_joint2', xyz:[0.02,0,0.043],    rpy:[0,0,0], axis:[0,1,0], min:0,      max:3.142,  label:'J2 Shoulder' },
  { name:'arm_joint3', xyz:[-0.264,0,0],      rpy:[0,0,0], axis:[0,1,0], min:-3.142, max:0,       label:'J3 Elbow' },
  { name:'arm_joint4', xyz:[0.245,0,0.06],    rpy:[0,0,0], axis:[0,1,0], min:-1.309, max:1.309,   label:'J4 Wrist Pitch' },
  { name:'arm_joint5', xyz:[0.074,0,0.042],   rpy:[0,0,0], axis:[0,0,1], min:-1.484, max:1.484,   label:'J5 Wrist Yaw' },
  { name:'arm_joint6', xyz:[0.0235,0,-0.042], rpy:[0,0,0], axis:[1,0,0], min:-2.007, max:2.007,   label:'J6 Flange Roll' },
];
/* 各 link 对应的网格文件（URDF visual；G1Z 夹爪双指为 fixed 关节，固定于 arm_link6）
   条目：[文件, 材质, 可选位置偏移]；材质：print=阳极氧化铝（银） / motor=关节电机与夹爪（黑） */
const LINK_MESHES = [
  [ ['base_link.STL','motor'] ],
  [ ['arm_link1.STL','motor'] ],
  [ ['arm_link2.STL','print'] ],
  [ ['arm_link3.STL','print'] ],
  [ ['arm_link4.STL','print'] ],
  [ ['arm_link5.STL','motor'] ],
  [ ['arm_link6.STL','motor'],
    ['gripper_finger_left_link.STL','motor',[0.0727,-0.025,0.018]],
    ['gripper_finger_rIght_link.STL','motor',[0.0727,0.025,-0.018]] ],
];

/* Unitree Go2 运动学 —— 逐字取自官方 URDF（unitreerobotics/unitree_ros@master · robots/go2_description）
   米制、Z-up、X 前向。本应用中 Go2 为静态站姿载体：12 个腿部关节按官方标准站位形固定，不参与实时控制。
   站姿 FK（thigh=0.9 / calf=-1.8）：足底 z = -0.213·(cos0.9+cos0.9) = -0.2648，足端球 r=0.022
   → base 离地 0.2868m（整机站高 ≈0.33m，与官方规格一致） */
const DOG_STAND = { hip: 0, thigh: 0.9, calf: -1.8 };
const DOG_BASE_H = 0.2868;
const DOG_LEGS = [  // 官方 URDF：hip 关节原点 / thigh 关节 Y 偏移 / hip 网格 visual rpy / 右侧镜像网格
  { id: 'FL', hipXyz: [ 0.1934,  0.0465, 0], thighY:  0.0955, hipRpy: [0, 0, 0],              mirror: false },
  { id: 'FR', hipXyz: [ 0.1934, -0.0465, 0], thighY: -0.0955, hipRpy: [Math.PI, 0, 0],        mirror: true  },
  { id: 'RL', hipXyz: [-0.1934,  0.0465, 0], thighY:  0.0955, hipRpy: [0, Math.PI, 0],        mirror: false },
  { id: 'RR', hipXyz: [-0.1934, -0.0465, 0], thighY: -0.0955, hipRpy: [Math.PI, Math.PI, 0],  mirror: true  },
];
/* A1Z 挂载点：Go2 base 系 (0.08, 0, 0.063) —— 躯干顶面 (+0.057) 上 6mm 转接板，
   避开头部雷达凸包（x∈[0.235,0.335]）；臂 +X = 狗 +X（同向朝被摄物，参照官方 Z1+Go2 组合） */
const MOUNT = [0.08, 0, 0.063];
/* 被摄物（世界系）= 挂载点世界坐标 + 求解系 S_rel(0.40,0,+0.10)，与 .devcheck/solve_a1z.mjs 的 S 严格联动：
   挂载世界 = (0.08, 0, 0.2868+0.063=0.3498) → SUBJ = (0.48, 0, 0.45)，43.2cm 展示台。
   抬高用意：全部机位相机位高于狗头凸包（狗 base 系 z≤0.055），无碰撞通道 */
const SUBJ = { x: 0.48, z: 0.45 };

/* 基准机位 —— 数值求解器（.devcheck/solve_a1z.mjs v6，URDF 精确链）针对狗背挂载新几何：
   被摄物 S=(0.40,0,0.10)（臂 base 系；世界系 43.2cm 展示台，抬高后相机全程高于狗头凸包）。
   极限机位按「瞄准强约束下优化极限指标」直接锚定：各机位瞄准误差 ≤1.5°，分镜转移中点 ≤2.0°。
   工作空间实测（aim≈0 约束）：far 35.5cm · top 俯 60° · low 最低 tip z=0.122 ——
   相机无法降至被摄物水平面以下（J4 ±75° 与工作空间共同决定，加权扫描复算同解），
   low 故为近台低机位特写（俯 10° · 12.2cm），非仰拍 */
const POSE = {
  home:   [ 0.007, 0.235,-0.898, 1.187,-0.006, 1.574],  // 中景待机（视距 32cm · 俯 30°）
  close:  [ 0.003, 0.675,-0.717, 0.677,-0.003, 1.573],  // 特写（视距 19cm · 俯 36°）
  far:    [ 0.030, 0.034,-0.899, 1.309,-0.023, 1.599],  // 后撤拉远（视距 36cm · 工作空间最远）
  top:    [ 0.002, 1.320,-1.575, 1.309,-0.002, 1.506],  // 高位俯拍（俯 60° · 视距 22cm）
  low:    [-0.312, 1.020, 0.000,-0.818, 0.453, 1.577],  // 低机位近台特写（俯 10° · 12cm · 物理极限低点）
  lowPre0:[-0.007, 0.506,-0.736, 0.824, 0.007, 1.566],  // 下沉过渡 1
  lowPre: [-0.062, 0.669,-0.478, 0.334, 0.079, 1.525],  // 下沉过渡 2
  lowPre2:[-0.121, 0.834,-0.239,-0.218, 0.178, 1.501],  // 下沉过渡 3
  orb0:   [ 0.000, 0.191,-0.758, 1.061,-0.000, 1.571],  // 弧拍·中
  orbL1:  [-0.230, 0.167,-0.751, 1.078, 0.209, 1.372],  // 弧拍·左近（荷兰角 5°）
  orbL2:  [-0.817, 0.000,-0.768, 1.309, 0.676, 1.036],  // 弧拍·左远（荷兰角 10°）
  orbR1:  [ 0.230, 0.167,-0.751, 1.078,-0.210, 1.770],  // 弧拍·右近（荷兰角 -5°）
  orbR2:  [ 0.817, 0.000,-0.767, 1.309,-0.677, 2.007],  // 弧拍·右远（荷兰角 -10°）
  swpA:   [ 0.357, 0.211,-0.983, 1.309,-0.285, 1.737],  // 横移扫掠·起
  swpB:   [-0.358, 0.210,-0.982, 1.309, 0.286, 1.405],  // 横移扫掠·止
};
/* 镜头呼吸感微动作：J6 法兰微滚转（弧度） */
const rollShift = (p, dr) => p.map((v, i) => i === 5 ? v + dr : v);
const yawShift = (p, dy) => p.map((v, i) => i === 4 ? v + dy : v);

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
    { keys: ['环绕', '弧拍', '绕', 'orbit', 'arc', '荷兰角', 'dutch'],
      title: 'Dutch Angle Orbit', tech: 'ARC ORBIT',
      make: ts => buildShots([
        { name: 'Arc In', tech: 'ARC ORBIT', desc: 'Glide into the orbit start, establishing the subject', moves: [K(POSE.orb0, 2.0), K(POSE.orbL1, 1.6), K(POSE.orbL2, 1.8)] },
        { name: 'Orbit Pass', tech: 'ARC ORBIT', desc: 'Dutch-angled arc past the shoulder, trail stays silky', moves: [K(POSE.orbL1, 1.6), K(POSE.orb0, 1.8), K(POSE.orbR1, 1.6), K(POSE.orbR2, 1.8)] },
        { name: 'Return Home', tech: 'RECOVER', desc: 'Ease out of the arc, back to the medium standby', moves: [K(POSE.orbR1, 1.6), K(POSE.orb0, 1.6), K(POSE.home, 2.2)] },
      ], ts) },
    { keys: ['推近', '特写', '靠近', 'dolly', 'close', 'macro', 'push'],
      title: 'Slow Push-In', tech: 'DOLLY IN',
      make: ts => buildShots([
        { name: 'Establish', tech: 'ESTABLISH', desc: 'Medium framing, holding to build anticipation', moves: [K(POSE.home, 1.4)] },
        { name: 'Dolly In', tech: 'DOLLY IN', desc: 'Constant-speed push to the close-up, gaze locked on subject', moves: [K(POSE.close, 4.2)] },
        { name: 'Insert Beat', tech: 'INSERT', desc: 'Micro flange roll — the frame breathes', moves: [K(rollShift(POSE.close, -0.05), 1.0), K(rollShift(POSE.close, 0.06), 1.2), K(POSE.close, 0.9)] },
        { name: 'Recover', tech: 'RECOVER', desc: 'Back to the medium standby', moves: [K(POSE.home, 2.8)] },
      ], ts) },
    { keys: ['拉远', '拉镜', '后撤', 'pull', 'dolly out', 'out', 'reveal'],
      title: 'Dolly Out Reveal', tech: 'DOLLY OUT',
      make: ts => buildShots([
        { name: 'Close Opener', tech: 'INSERT', desc: 'Open on the close-up', moves: [K(POSE.close, 2.2)] },
        { name: 'Dolly Out', tech: 'DOLLY OUT', desc: 'Pull back to the max reach of the workspace, space unfolds', moves: [K(POSE.far, 4.0), K(rollShift(POSE.far, 0.04), 1.4)] },
        { name: 'Recover', tech: 'RECOVER', desc: 'Back to the medium standby', moves: [K(POSE.home, 3.0)] },
      ], ts) },
    { keys: ['俯拍', '顶拍', '俯视', 'top', 'overhead'],
      title: 'High Top Shot', tech: 'TOP SHOT',
      make: ts => buildShots([
        { name: 'Rise', tech: 'TOP SHOT', desc: 'Camera rises to the 58° limit pitch, looking down', moves: [K(POSE.top, 3.6)] },
        { name: 'Top Hold', tech: 'HOLD', desc: 'High-angle gaze, subtle wrist sway for motion', moves: [K(yawShift(POSE.top, 0.14), 1.6), K(POSE.top, 1.2)] },
        { name: 'Recover', tech: 'RECOVER', desc: 'Back to the medium standby', moves: [K(POSE.home, 3.0)] },
      ], ts) },
    { keys: ['仰拍', '低角度', '低机位', 'low'],
      title: 'Low Angle Macro', tech: 'LOW ANGLE',
      make: ts => buildShots([
        { name: 'Descend', tech: 'LOW ANGLE', desc: 'Camera dives table-level, gaze tilts slightly up', moves: [K(POSE.lowPre0, 2.0), K(POSE.lowPre, 1.6), K(POSE.lowPre2, 1.4), K(POSE.low, 1.2)] },
        { name: 'Low Hold', tech: 'HOLD', desc: 'A 6° up-tilt macro stare — monumental feel', moves: [K(rollShift(POSE.low, 0.05), 2.0)] },
        { name: 'Recover', tech: 'RECOVER', desc: 'Retrace the way up, back to standby', moves: [K(POSE.lowPre2, 1.2), K(POSE.lowPre, 1.4), K(POSE.lowPre0, 1.6), K(POSE.home, 2.2)] },
      ], ts) },
    { keys: ['扫掠', '横移', '横扫', 'sweep', 'truck'],
      title: 'Truck Sweep', tech: 'TRUCK SWEEP',
      make: ts => buildShots([
        { name: 'Set In', tech: 'TRUCK', desc: 'Move to the sweep start', moves: [K(POSE.swpA, 2.6)] },
        { name: 'Sweep', tech: 'TRUCK SWEEP', desc: 'Subject traverses the frame at constant speed, full parallax', moves: [K(POSE.swpB, 4.6)] },
        { name: 'Recover', tech: 'RECOVER', desc: 'Back to the medium standby', moves: [K(POSE.home, 2.6)] },
      ], ts) },
  ];

  const epic = ts => buildShots([
    { name: 'Establish · Wide', tech: 'ESTABLISH', desc: 'Pulled-back wide sets the scene, easing to medium', moves: [K(POSE.far, 2.4), K(POSE.home, 3.0)] },
    { name: 'Push · Close', tech: 'DOLLY IN', desc: 'Constant push-in, micro flange motion as the accent', moves: [K(POSE.close, 3.8), K(rollShift(POSE.close, -0.05), 0.9), K(rollShift(POSE.close, 0.06), 1.1), K(POSE.close, 0.8)] },
    { name: 'Arc · Dutch', tech: 'ARC ORBIT', desc: 'Orbiting arc past the shoulder, dynamic imbalance', moves: [K(POSE.orb0, 2.0), K(POSE.orbL1, 1.5), K(POSE.orbL2, 1.7), K(POSE.orbL1, 1.5), K(POSE.orb0, 1.6), K(POSE.orbR1, 1.5), K(POSE.orbR2, 1.7)] },
    { name: 'Finale', tech: 'FINALE', desc: 'Rise to the top shot, settle home — narrative closed', moves: [K(POSE.orbR1, 1.5), K(POSE.top, 2.6), K(POSE.home, 2.8)] },
  ], ts);

  async function generatePlan(text) {
    // —— 模拟 LLM 推理延迟；接入真实模型时替换为 API 调用 ——
    await new Promise(r => setTimeout(r, 700 + Math.random() * 700));
    const s = (text || '').toLowerCase();
    let ts = 1.0, speedNote = 'Standard pace';
    if (/慢|缓慢|优雅|slow/.test(s)) { ts = 1.55; speedNote = 'Gentle 0.65×'; }
    if (/快|快速|迅速|fast|quick/.test(s)) { ts = 0.62; speedNote = 'Brisk 1.6×'; }
    const repeat = /两次|两遍|重复|twice|again|x2|×2/.test(s) ? 2 : 1;

    let entry = library.find(e => e.keys.some(k => s.includes(k)));
    let shots, title, tech;
    if (!entry || /大片|完整|全部|广告|epic|film/.test(s)) {
      title = 'Product Film · 4 Acts'; shots = epic(ts);
    } else { title = entry.title; shots = entry.make(ts); }

    if (repeat === 2) {
      const base = shots;
      const offset = base[base.length - 1].t1;
      const round2 = base.map(sh => ({
        ...sh, name: sh.name + ' · Pass 2',
        keyframes: sh.keyframes.map(f => [f[0], f[1] + offset]),
        t0: sh.t0 + offset, t1: sh.t1 + offset,
      }));
      shots = base.concat(round2);
    }
    const total = shots[shots.length - 1].t1;
    return {
      title,
      summary: `${shots.length} shots · ~${total.toFixed(1)}s · ${speedNote} · Catmull-Rom smoothing${repeat > 1 ? ' · 2 passes' : ''}`,
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
  const tcp = new THREE.Object3D();           // 末端执行器参考点 = 相机光心（与轨迹求解器一致：link6 系 +X 13.5cm）
  tcp.position.set(0.135, 0, 0);
  linkGroups[6].add(tcp);
  const camMount = new THREE.Object3D();      // 腕部相机：固定于 arm_link6（G1Z 夹爪之间，光轴 = link6 +X）
  // 朝向 = Ry(-90°)：three 相机 -Z 视轴 → link6 +X，相机上向量 → link6 +Y，
  // 与 .devcheck/solve_a1z.mjs 求解器相机模型严格一致（各机位瞄准误差 ≤1.2°，已数值验证）
  camMount.position.set(0.135, 0, 0);
  camMount.rotation.set(0, -Math.PI / 2, 0);
  linkGroups[6].add(camMount);
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
camera.position.set(1.02, 0.62, 1.12);
camera.layers.enable(1); // layer 1 = 轨迹线/预览线（腕部相机不可见）

const controls = new OrbitControls(camera, renderer.domElement);
controls.target.set(0.16, 0.26, 0);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 0.3;
controls.maxDistance = 3.0;
controls.maxPolarAngle = 1.52;

const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;

// —— 灯光：暖金主光 / 中性补光 / 香槟轮廓光 ——
const keyLight = new THREE.SpotLight(0xf4f4f6, 30, 7, 0.55, 1.0);
keyLight.position.set(0.75, 1.05, 0.55);
keyLight.castShadow = true;
keyLight.shadow.mapSize.set(2048, 2048);
keyLight.shadow.bias = -0.0004;
keyLight.shadow.camera.near = 0.2;
keyLight.shadow.camera.far = 4;
scene.add(keyLight);
keyLight.target.position.set(0.25, 0.12, 0);
scene.add(keyLight.target);

const fillLight = new THREE.DirectionalLight(0xd8d4cc, 0.85);
fillLight.position.set(-0.9, 0.5, -0.4);
scene.add(fillLight);

const rimLight = new THREE.SpotLight(0xc7cbd6, 22, 7, 0.7, 1.0);
rimLight.position.set(-0.65, 0.85, -0.75);
scene.add(rimLight);
rimLight.target.position.set(0.2, 0.2, 0);
scene.add(rimLight.target);

scene.add(new THREE.HemisphereLight(0x2e3033, 0x0b0b0d, 0.5));

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

const MAT = {
  print: new THREE.MeshStandardMaterial({ color: 0x8f9297, roughness: 0.26, metalness: 1.0, envMapIntensity: 1.25 }),  // 钢灰金属（A1Z 臂身 / Go2 机身与大腿）
  motor: new THREE.MeshStandardMaterial({ color: 0x141518, roughness: 0.3, metalness: 0.9, envMapIntensity: 1.0 }),   // 黑化阳极氧化（关节电机 / 夹爪 / Go2 小腿）
  accent: new THREE.MeshStandardMaterial({ color: 0xc7cbd6, roughness: 0.3, metalness: 0.8, emissive: 0x232529, emissiveIntensity: 0.45 }),
  rubber: new THREE.MeshStandardMaterial({ color: 0x0c0c0d, roughness: 0.85, metalness: 0.1 }),                       // 哑光橡胶（Go2 足端）
};

// —— 被摄静物：SUBJ = 挂载世界系 + 求解系 S_rel(0.40,0,+0.10) → three 系 (0.48,0.45,0)，43.2cm 展示台 + 黑曜球体 ——
(function buildSubject() {
  const pedH = SUBJ.z - 0.018;
  const ped = new THREE.Mesh(
    new THREE.CylinderGeometry(0.032, 0.038, pedH, 64),
    new THREE.MeshStandardMaterial({ color: 0xc9c9c7, roughness: 0.75, metalness: 0.02 })
  );
  ped.position.set(SUBJ.x, pedH / 2, 0);
  ped.castShadow = true; ped.receiveShadow = true;
  const obj = new THREE.Mesh(
    new THREE.SphereGeometry(0.018, 48, 32),
    new THREE.MeshPhysicalMaterial({ color: 0x0e0e10, roughness: 0.12, metalness: 0.2, clearcoat: 1, clearcoatRoughness: 0.08 })
  );
  obj.position.set(SUBJ.x, SUBJ.z, 0);
  obj.castShadow = true;
  const halo = new THREE.Mesh(new THREE.TorusGeometry(0.024, 0.0012, 12, 64), MAT.accent.clone());
  halo.rotation.x = Math.PI / 2;
  halo.position.set(SUBJ.x, SUBJ.z - 0.019, 0);
  const spot = new THREE.SpotLight(0xf6f6f8, 8, 3, 0.32, 0.9);
  spot.position.set(SUBJ.x + 0.2, SUBJ.z + 0.42, 0.42);
  spot.target = obj;
  scene.add(ped, obj, halo, spot);
})();

// —— 机械臂本体（URDF 系 Z-up；挂载于 Go2 base link，坐标变换由 dog.root 统一承担）——
const robotRoot = new THREE.Group();
const kin = buildKinematics(robotRoot);

/* Unitree Go2 —— 静态站姿载体：官方 URDF 腿部链（场景图层级即正运动学），A1Z 刚性挂载于背部转接板 */
function buildDog() {
  const root = new THREE.Group();
  root.rotation.x = -Math.PI / 2;      // URDF Z-up → three.js Y-up（狗与臂共用）
  root.position.y = DOG_BASE_H;        // 站姿 FK：足端球面恰触地
  scene.add(root);
  const base = new THREE.Group(); base.name = 'go2_base';
  root.add(base);
  const legLinks = {};
  const AX = new THREE.Vector3(1, 0, 0), AY = new THREE.Vector3(0, 1, 0);
  DOG_LEGS.forEach(L => {
    const hipO = new THREE.Group(); hipO.position.set(...L.hipXyz); base.add(hipO);
    const hipR = new THREE.Group(); hipR.quaternion.setFromAxisAngle(AX, DOG_STAND.hip); hipO.add(hipR);
    const hipL = new THREE.Group(); hipL.name = 'go2_' + L.id + '_hip'; hipR.add(hipL);
    const thO = new THREE.Group(); thO.position.set(0, L.thighY, 0); hipL.add(thO);
    const thR = new THREE.Group(); thR.quaternion.setFromAxisAngle(AY, DOG_STAND.thigh); thO.add(thR);
    const thL = new THREE.Group(); thL.name = 'go2_' + L.id + '_thigh'; thR.add(thL);
    const caO = new THREE.Group(); caO.position.set(0, 0, -0.213); thL.add(caO);
    const caR = new THREE.Group(); caR.quaternion.setFromAxisAngle(AY, DOG_STAND.calf); caO.add(caR);
    const caL = new THREE.Group(); caL.name = 'go2_' + L.id + '_calf'; caR.add(caL);
    const ftO = new THREE.Group(); ftO.position.set(0, 0, -0.213); caL.add(ftO);
    legLinks[L.id] = { hip: hipL, thigh: thL, calf: caL, foot: ftO };
  });
  // 背部转接板（顶面 +0.057，板厚 6mm → 臂底面落于 +0.063 = MOUNT[2]）
  const plate = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.055, 0.006, 48), MAT.motor);
  plate.rotation.x = Math.PI / 2;      // 圆柱轴 → URDF Z
  plate.position.set(MOUNT[0], MOUNT[1], 0.060);
  plate.castShadow = true;
  base.add(plate);
  base.add(robotRoot);                 // 挂载：臂 base 系原点 = MOUNT
  robotRoot.position.set(...MOUNT);
  return { root, base, legLinks };
}
const dog = buildDog();
function setAngles(q) {
  for (let i = 0; i < 6; i++) rotorsSet(kin.rotors[i], clampQ(q[i] ?? 0, i), i);
}
function rotorsSet(rotor, q, i) {
  rotor.quaternion.setFromAxisAngle(AXIS_VEC[i], q);
}

/* STL 加载（内嵌 base64 离线优先，CDN 仅作臂部备份）；失败时降级为程序化模型（运动学不变） */
const veilFill = document.getElementById('vBarFill');
const veilSub = document.getElementById('vSub');
function b64ToBuf(b64) {
  const bin = atob(b64.replace(/\s+/g, ''));
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8.buffer;
}
const _stlLoader = new STLLoader();
const _embedded = {};
document.querySelectorAll('script.dx-stl').forEach(el => { _embedded[el.dataset.file] = el.textContent; });
const _withTimeout = (p, ms) => Promise.race([p, new Promise(r => setTimeout(() => r(null), ms))]);
async function loadOneMesh(file) {
  if (_embedded[file]) {
    await sleep(0); // 让加载页有机会重绘进度
    try { return _stlLoader.parse(b64ToBuf(_embedded[file])); } catch (e) { /* 内嵌损坏则走 CDN */ }
  }
  for (const base of CONFIG.MESH_BASES) {
    try {
      const g = await _withTimeout(_stlLoader.loadAsync(base + file), 12000);
      if (g) return g;
    } catch (e) { /* 换下一个 CDN */ }
  }
  return null;
}
const GO2_MESH_FILES = ['go2_base.STL', 'go2_hip.STL', 'go2_thigh.STL', 'go2_thigh_mirror.STL', 'go2_calf.STL', 'go2_calf_mirror.STL', 'go2_foot.STL'];
const _meshTotal = LINK_MESHES.flat().length + GO2_MESH_FILES.length;
let _meshDone = 0;
function _meshTick() {
  _meshDone++;
  veilFill.style.width = Math.round(_meshDone / _meshTotal * 100) + '%';
  veilSub.textContent = 'Loading GALAXEA A1Z + Unitree Go2… ' + _meshDone + ' / ' + _meshTotal;
}
async function loadArmMeshes() {
  const jobs = [];
  LINK_MESHES.forEach((files, li) => files.forEach(([file, kind, pos]) => {
    jobs.push(loadOneMesh(file).then(geo => {
      _meshTick();
      if (!geo) return;
      const mesh = new THREE.Mesh(geo, MAT[kind]);
      mesh.castShadow = true;
      if (pos) mesh.position.set(pos[0], pos[1], pos[2]);  // fixed 关节偏移（G1Z 夹爪双指）
      kin.linkGroups[li].add(mesh);
    }));
  }));
  await Promise.all(jobs);
  const total = LINK_MESHES.flat().length;
  const loaded = kin.linkGroups.reduce((n, g) => n + g.children.filter(c => c.isMesh).length, 0);
  if (loaded < total) {
    buildProceduralArm();
    return loaded === 0 ? 'procedural' : 'partial';
  }
  return 'stl';
}
/* Go2 网格：7 个唯一文件一次加载，按官方 URDF visual（hip rpy / 右侧 *_mirror 网格）实例化到各 link */
async function loadDogMeshes() {
  const geos = {};
  await Promise.all(GO2_MESH_FILES.map(f => loadOneMesh(f).then(g => { _meshTick(); geos[f] = g; })));
  if (!GO2_MESH_FILES.every(f => geos[f])) { buildProceduralDog(); return false; }
  const add = (file, kind, parent, rpy) => {
    const m = new THREE.Mesh(geos[file], MAT[kind]);
    m.castShadow = true; m.receiveShadow = true;
    if (rpy) m.rotation.set(rpy[0], rpy[1], rpy[2], 'ZYX'); // URDF visual rpy 约定（Rz·Ry·Rx）
    parent.add(m);
  };
  add('go2_base.STL', 'print', dog.base);
  DOG_LEGS.forEach(L => {
    const ll = dog.legLinks[L.id];
    add('go2_hip.STL', 'motor', ll.hip, L.hipRpy);
    add(L.mirror ? 'go2_thigh_mirror.STL' : 'go2_thigh.STL', 'print', ll.thigh);
    add(L.mirror ? 'go2_calf_mirror.STL' : 'go2_calf.STL', 'motor', ll.calf);
    add('go2_foot.STL', 'rubber', ll.foot);
  });
  return true;
}
function buildProceduralArm() {
  kin.linkGroups.forEach(g => g.clear());
  const baseM = new THREE.Mesh(new THREE.CylinderGeometry(0.062, 0.068, 0.075, 48), MAT.motor);
  baseM.position.y = 0.0375; baseM.castShadow = true;
  kin.linkGroups[0].add(baseM);
  const NEXT = [JOINTS[1].xyz, JOINTS[2].xyz, JOINTS[3].xyz, JOINTS[4].xyz, JOINTS[5].xyz, [0.135, 0, 0]];
  NEXT.forEach((n, k) => {
    const g = kin.linkGroups[k + 1];
    const v = new THREE.Vector3(...n);
    const len = v.length();
    const cap = new THREE.Mesh(new THREE.CapsuleGeometry(Math.max(0.013, 0.03 - k * 0.003), len, 6, 16), k % 2 ? MAT.motor : MAT.print);
    cap.castShadow = true;
    cap.position.copy(v.clone().multiplyScalar(0.5));
    cap.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), v.clone().normalize());
    g.add(cap);
    const hub = new THREE.Mesh(new THREE.SphereGeometry(Math.max(0.015, 0.034 - k * 0.003), 24, 16), MAT.accent);
    hub.castShadow = true;
    g.add(hub);
  });
  // G1Z 夹爪双指（fixed 关节，锥形指尖）
  [[0.0727, -0.025, 0.018], [0.0727, 0.025, -0.018]].forEach(p => {
    const fing = new THREE.Mesh(new THREE.ConeGeometry(0.011, 0.09, 20), MAT.motor);
    fing.castShadow = true;
    fing.position.set(p[0] + 0.045, p[1], p[2]);
    fing.rotation.z = -Math.PI / 2;   // 锥尖朝 +X
    kin.linkGroups[6].add(fing);
  });
  // 保留 tcp / camMount（clear 会移除它们，需重新挂载）
  kin.linkGroups[6].add(kin.tcp);
  kin.linkGroups[6].add(kin.camMount);
}
/* Go2 程序化降级（网格加载失败时）：机身盒 + 关节毂 + 腿段胶囊，几何遵循官方 URDF 关节原点 */
function buildProceduralDog() {
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.38, 0.12, 0.11), MAT.print);
  body.castShadow = true; dog.base.add(body);
  DOG_LEGS.forEach(L => {
    const ll = dog.legLinks[L.id];
    const hub = new THREE.Mesh(new THREE.SphereGeometry(0.04, 20, 14), MAT.motor);
    hub.castShadow = true; ll.hip.add(hub);
    const seg = (parent, to, r, mat) => {
      const v = new THREE.Vector3(...to), len = v.length();
      const cap = new THREE.Mesh(new THREE.CapsuleGeometry(r, len, 6, 12), mat);
      cap.castShadow = true;
      cap.position.copy(v.clone().multiplyScalar(0.5));
      cap.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), v.clone().normalize());
      parent.add(cap);
    };
    seg(ll.thigh, [0, 0, -0.213], 0.026, MAT.print);
    seg(ll.calf, [0, 0, -0.213], 0.013, MAT.motor);
    const foot = new THREE.Mesh(new THREE.SphereGeometry(0.022, 16, 12), MAT.rubber);
    foot.castShadow = true; ll.foot.add(foot);
  });
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
   TrailRenderer — 末端执行器发光轨迹（加色混合银白渐变）
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
  grad.addColorStop(0, 'rgba(255,255,255,1)');
  grad.addColorStop(0.35, 'rgba(235,238,244,.55)');
  grad.addColorStop(1, 'rgba(199,203,214,0)');
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
      col[i * 3] = 0.07 + 0.85 * f * f;
      col[i * 3 + 1] = 0.075 + 0.88 * f * f;
      col[i * 3 + 2] = 0.09 + 0.93 * f * f;
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
    color: 0xc7cbd6, dashSize: 0.007, gapSize: 0.005, transparent: true, opacity: 0.3,
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
   RobotBridge — GALAXEA A1Z 真实机械臂控制接口（默认 Mock）
   对齐官方协议（GALAXEA-A1Z SDK gripper 分支 a1z/robots/server.py，经 tools/a1zctl 启动）：
   · A1Z = 6 轴（G1Z 夹爪为独立通道），指令与反馈均为 URDF 关节约定 ——
     SDK 公开接口内部完成电机符号换算（[1,1,-1,1,-1,1]），本文件角度可直发，无需映射
   · 官方 server：Unix socket /tmp/a1z.sock · 换行结尾 JSON {cmd,args} → {ok,data|error}
   · 指令集：status | move(joints[6]° 或 preset, speed rad/s) | gripper(value 0..1)
            | dance | estop | release | info | stop
   · 真机路径：同目录 a1z_bridge.py 将官方协议逐字透传为 HTTP（CONFIG.A1Z_ENDPOINT）
   ============================================================ */
const A1Z_LIMITS = JOINTS.map(j => [j.min, j.max]);
const clampA1Z = q => q.map((v, i) => Math.min(A1Z_LIMITS[i][1], Math.max(A1Z_LIMITS[i][0], v)));
const sleep = ms => new Promise(r => setTimeout(r, ms));

/* 方案关键帧 → 官方 move 指令序列：每段 = 一次阻塞式 minimum-jerk move_joints，
   speed = 该段最大关节增量 / 段时长（与可视化时间轴同速），语义与官方 API 一一对应 */
function planToMoves(plan, speedScale) {
  const wps = planToWaypoints(plan);
  const moves = [];
  for (let i = 1; i < wps.length; i++) {
    const dt = Math.max(0.2, (wps[i].t - wps[i - 1].t) / Math.max(0.05, speedScale));
    let dMax = 0;
    for (let j = 0; j < 6; j++) dMax = Math.max(dMax, Math.abs(wps[i].q[j] - wps[i - 1].q[j]));
    if (dMax < 1e-4) continue;
    const speed = Math.min(CONFIG.A1Z_MOVE_MAX_SPEED, dMax / dt);
    moves.push({ joints: clampA1Z(wps[i].q), speed, dur: dMax / speed });
  }
  return moves;
}

/* —— Mock：本地回环，模拟延迟与响应（默认） —— */
class MockTransport {
  constructor() { this.lastCmd = null; }
  async connect() { await sleep(250); return { detail: 'local loopback sim' }; }
  async disconnect() { }
  async getJointState() { return [...visualQ]; }
  async executeMoves(moves) { this.lastCmd = { type: 'moves', count: moves.length }; await sleep(10); return { ok: true, simulated: true }; }
  async estop() { this.lastCmd = { type: 'estop' }; await sleep(4); return { ok: true, simulated: true }; }
}

/* —— A1Z·HTTP：经 a1z_bridge.py 透传官方协议（请求/响应与官方 socket 逐字一致） —— */
class A1zHttpTransport {
  constructor(endpoint) { this.endpoint = endpoint || CONFIG.A1Z_ENDPOINT; this.cancelled = false; }
  async call(cmd, args = {}, timeoutMs = 8000) {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(this.endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cmd, args }), signal: ctrl.signal,
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const r = await res.json();
      if (!r.ok) throw new Error(r.error || (cmd + ' failed'));
      return r.data;
    } finally { clearTimeout(to); }
  }
  async connect() {                            // = 官方 info + release（解除可能存在的急停闩锁）
    const info = await this.call('info', {}, 4500);
    await this.call('release', {}, 4500).catch(() => { });
    return { detail: 'A1Z official (' + ((info && info.presets) || []).length + ' presets)' };
  }
  async disconnect() { this.cancelled = true; }
  async getJointState() {                      // = 官方 status（pos_deg → rad）
    const d = await this.call('status', {}, 4500);
    return d.pos_deg.map(v => v * Math.PI / 180);
  }
  async executeMoves(moves) {                  // = 官方 move 序列（阻塞式，逐段等待到位）
    this.cancelled = false;
    for (const m of moves) {
      if (this.cancelled) return { ok: false, error: 'cancelled' };
      await this.call('move', {
        joints: m.joints.map(v => +(v * 57.29578).toFixed(2)),
        speed: +m.speed.toFixed(3),
      }, Math.max(15000, m.dur * 1600 + 8000));
    }
    return { ok: true };
  }
  async estop() {                              // = 官方 estop（server 端免锁，可中断进行中的 move）
    this.cancelled = true;
    return this.call('estop', {}, 3000).catch(() => { });
  }
}

/* —— WebSocket：预留（未来由 a1z_bridge.py --ws 提供，消息结构与官方协议一致） ——
   上行（JSON）：{cmd:'move', args:{joints:[6]°, speed}} · {cmd:'estop'} · {cmd:'status'}
   下行：       {ok:true, data:{...}} · 状态推送 {cmd:'status', data:{pos_deg:[6]}} */
class WsTransport {
  constructor(url) { this.url = url || CONFIG.WS_ENDPOINT; this.ws = null; this.onJointState = null; }
  connect() {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url); this.ws = ws;
      const to = setTimeout(() => { ws.close(); reject(new Error('Connection timeout')); }, 3000);
      ws.onopen = () => { clearTimeout(to); resolve({ detail: 'WebSocket bridge connected' }); };
      ws.onerror = () => { clearTimeout(to); reject(new Error('Cannot reach ' + this.url)); };
      ws.onclose = () => { };
      ws.onmessage = e => {
        try {
          const m = JSON.parse(e.data);
          if (m.cmd === 'status' && m.data && m.data.pos_deg && this.onJointState)
            this.onJointState(m.data.pos_deg.map(v => v * Math.PI / 180));
        } catch (_) { }
      };
    });
  }
  _send(cmd, args) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify({ cmd, args: args || {} })); }
  async disconnect() { this.ws && this.ws.close(); }
  async getJointState() { this._send('status'); }
  async executeMoves(moves) { for (const m of moves) this._send('move', { joints: m.joints.map(v => +(v * 57.29578).toFixed(2)), speed: +m.speed.toFixed(3) }); }
  async estop() { this._send('estop'); }
}

/* —— Bridge 门面：模式切换 + 状态通知，上层只感知 6 轴 URDF 关节角 —— */
const bridge = (() => {
  let transport = new MockTransport(), mode = 'mock';
  const api = {
    get mode() { return mode; },
    onJointState: null,
    async setMode(m) {
      if (m === mode) return;
      setConn('busy', m === 'a1z' ? 'Connecting A1Z…' : m === 'ws' ? 'Connecting WS…' : 'Local Mock');
      try {
        const t = m === 'mock' ? new MockTransport() : m === 'a1z' ? new A1zHttpTransport() : new WsTransport();
        t.onJointState = q => api.onJointState && api.onJointState(q);
        const info = await t.connect();
        await transport.disconnect().catch(() => { });
        transport = t; mode = m;
        setConn(m === 'mock' ? '' : 'ok', m === 'mock' ? 'Local Mock' : (m === 'a1z' ? 'A1Z · ' : 'WS · ') + info.detail);
        toast(m === 'mock' ? 'Switched to local mock mode' : 'Connected: ' + info.detail);
      } catch (e) {
        setConn('err', (m === 'a1z' ? 'A1Z' : 'WS') + ' link failed');
        toast('Connection failed: ' + e.message + ' (start a1z_bridge.py first — see CONFIG)', 'err');
        setSeg(mode);
      }
    },
    async executeMoves(moves) { try { return await transport.executeMoves(moves); } catch (e) { toast('Robot execution error: ' + e.message, 'err'); } },
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
  execBtn.querySelector('span').textContent = s === 'done' ? 'Re-run' : 'Execute';
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
      + '<div class="params">' + (sh.t1 - sh.t0).toFixed(1) + 's · ' + sh.keyframes.length + ' keyframes · smooth</div></div>'
      + '<div class="st">Queued</div></div>';
  });
  wrap.innerHTML = '<div class="who">DirectorX AI · Shot Plan</div>'
    + '<div class="plan"><div class="p-head"><span class="p-title">' + plan.title + '</span><span class="p-badge">Mock Planner</span></div>'
    + '<div class="p-sub">' + plan.summary + '</div>' + shotsHtml
    + '<div class="p-foot"><span class="p-total">TOTAL ' + plan.total.toFixed(1) + 's · ' + plan.shots.length + ' SHOTS</span>'
    + '<button class="btn-accent p-exec"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l11-6.5z"/></svg>Execute Plan</button></div></div>';
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
    if (status === 'done' || (status === 'active' && k < activeIdx)) st.textContent = 'Done';
    else if (status === 'active' && k === activeIdx) st.textContent = 'Live';
    else st.textContent = 'Queued';
  });
}

/* —— 指令流：输入 → 方案 → 预览 —— */
async function submitCmd() {
  const text = cmdInput.value.trim();
  if (!text || appState === 'planning') return;
  if (appState === 'executing' || appState === 'paused') { toast('Shooting in progress — stop it first', 'warn'); return; }
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
    toast('Plan generation failed: ' + e.message, 'err');
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
  preview.hide();
  trail.clear();
  executor.load(currentPlan, smooth());
  executor.start();
  setState('executing');
  pauseBtn.innerHTML = ICON_PAUSE;
  // 关键帧指令序列下发真实机械臂（官方 move 协议逐段阻塞执行；Mock 为回环记录）
  bridge.executeMoves(planToMoves(currentPlan, speed()));
}
function finishExecution() {
  setState('done');
  setShotStatus(-1, 'done');
  toast('Shot complete');
}
function stopExecution() {
  bridge.estop();
  executor.stop();
  setState('ready');
  setShotStatus(-1, 'wait');
  drawPreview();
  returnAnim = { from: [...visualQ], t: 0, dur: 1.4 };
  toast('Stopped · arm returning home');
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
    if (appState === 'executing' || appState === 'paused') { toast('Cannot switch connection mode while shooting', 'warn'); setSeg(bridge.mode); return; }
    setSeg(b.dataset.mode);
    bridge.setMode(b.dataset.mode);
  });
});

/* —— 欢迎消息 —— */
(function welcome() {
  const el = document.createElement('div');
  el.className = 'msg ai';
  el.innerHTML = '<div class="who">DirectorX AI</div><div class="bubble">'
    + 'Hello, Director. I\'m your AI cinematographer.<br>Describe the shot language you want — I\'ll draft a storyboard and drive the GALAXEA A1Z through its true kinematics.'
    + '<div class="chips">'
    + '<button class="chip">Slow push-in for a product close-up</button>'
    + '<button class="chip">Orbit once with a Dutch angle</button>'
    + '<button class="chip">High top shot, then reset</button>'
    + '<button class="chip">Give me a full product film</button>'
    + '</div></div>';
  msgsEl.appendChild(el);
  el.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => { cmdInput.value = c.textContent; submitCmd(); }));
})();

/* ============================================================
   WebCam — 真实摄像头（getUserMedia，拒绝时优雅降级）
   ============================================================ */
async function initWebcam() {
  const body = document.getElementById('camBody');
  const camDot = document.getElementById('camDot');
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 640 } }, audio: false });
    const v = document.createElement('video');
    v.autoplay = true; v.muted = true; v.playsInline = true;
    v.srcObject = stream;
    body.innerHTML = ''; body.appendChild(v);
    camDot.classList.add('ok');
  } catch (e) {
    body.innerHTML = '<div class="cam-fallback">Camera unavailable<br>(permission denied or no device)</div>';
    camDot.classList.add('err');
  }
}

/* ============================================================
   主循环 + 初始化
   ============================================================ */
const clock = new THREE.Clock();
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
    if (ev.done) finishExecution();
  }

  renderer.render(scene, camera);
}

async function init() {
  setAngles(visualQ);
  updateHud(visualQ);
  animate();
  initWebcam();
  try {
    // 总时长封顶 40s：超时即用程序化降级模型，绝不卡死在加载页
    const status = await Promise.race([
      (async () => { const s = await loadArmMeshes(); await loadDogMeshes(); return s; })(),
      sleep(40000).then(() => 'timeout')
    ]);
    if (status === 'timeout') buildProceduralArm();
    veilSub.textContent = status === 'stl' ? 'Model loaded' : 'Load failed · procedural fallback active';
    if (status !== 'stl') toast('STL failed to load — procedural fallback engaged', 'warn');
  } catch (e) {
    try { buildProceduralArm(); } catch (_) { }
    veilSub.textContent = 'Load failed · procedural fallback active';
  }
  await sleep(400);
  document.getElementById('veil').classList.add('gone');
  window.__dxReady = true; // 引导握手：全部就绪
  returnAnim = { from: [...visualQ], t: 0, dur: 2.2 };  // 开场：零位 → 中景待机
}
init();
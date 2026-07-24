/* 端到端验证：用 three.js 场景图复现 directorx.html 的真实渲染运动学路径
   （buildKinematics 的 origin/rpy/rotor 层级 + robotRoot Z-up→Y-up 旋转 + camMount），
   与 .devcheck/solve_a1z.mjs 求解器的解析 FK 结果逐机位对照 */
import * as THREE from './node_modules/three/build/three.module.js';
import { readFileSync } from 'fs';

const src = readFileSync('app_a1z.mjs', 'utf8').replace(/\r\n/g, '\n');
const grab = (s, e) => { const i = src.indexOf(s); const j = src.indexOf(e, i);
  if (i < 0 || j < 0) throw new Error('grab 失败: ' + s.slice(0, 30)); return src.slice(i, j + e.length); };
const M = new Function(
  grab('const JOINTS = [', '];') + '\n' +
  grab('const POSE = {', '};') + '\n' +
  'return { JOINTS, POSE };')();

// —— 与应用完全一致的层级构建 ——
const robotRoot = new THREE.Group();
robotRoot.rotation.x = -Math.PI / 2;           // URDF Z-up → three.js Y-up（与应用一致）
const scene = new THREE.Scene();
scene.add(robotRoot);

const linkGroups = [], rotors = [];
const base = new THREE.Group();
robotRoot.add(base); linkGroups.push(base);
let parent = base;
for (let i = 0; i < 6; i++) {
  const j = M.JOINTS[i];
  const origin = new THREE.Group();
  origin.position.set(...j.xyz);
  origin.rotation.set(j.rpy[0], j.rpy[1], j.rpy[2], 'ZYX');
  parent.add(origin);
  const rotor = new THREE.Group();
  origin.add(rotor); rotors.push(rotor);
  const link = new THREE.Group();
  rotor.add(link); linkGroups.push(link);
  parent = link;
}
const tcp = new THREE.Object3D();
tcp.position.set(0.135, 0, 0);
linkGroups[6].add(tcp);
const camMount = new THREE.Object3D();
camMount.position.set(0.135, 0, 0);
camMount.rotation.set(0, -Math.PI / 2, 0);
linkGroups[6].add(camMount);

const AXIS = M.JOINTS.map(j => new THREE.Vector3(...j.axis).normalize());
const S = new THREE.Vector3(0.40, 0, 0.10);    // URDF 系被摄物（臂 base 系；世界系 43.2cm 展示台）
const u2t = v => new THREE.Vector3(v.x, v.z, -v.y);  // URDF → three 坐标换算（对照用）

let worst = 0, pass = 0, fail = 0;
for (const [name, q] of Object.entries(M.POSE)) {
  for (let i = 0; i < 6; i++) rotors[i].quaternion.setFromAxisAngle(AXIS[i], q[i]);
  robotRoot.updateMatrixWorld(true);
  const tipW = tcp.getWorldPosition(new THREE.Vector3());
  const gazeW = camMount.getWorldDirection(new THREE.Vector3()).negate(); // Object3D.getWorldDirection 返回 +Z 轴，取反得相机视轴（-Z）
  const tipU = new THREE.Vector3(tipW.x, -tipW.z, tipW.y);       // three → URDF
  const gazeU = new THREE.Vector3(gazeW.x, -gazeW.z, gazeW.y);
  const d = S.clone().sub(tipU), dist = d.length();
  const aim = Math.acos(Math.min(1, Math.max(-1, gazeU.dot(d) / dist))) * 180 / Math.PI;
  worst = Math.max(worst, aim);
  const okk = aim <= 1.5 && dist > 0.05;
  if (okk) pass++; else { fail++; console.log('FAIL', name, 'aim', aim.toFixed(2), '°'); }
  console.log(name.padEnd(7), 'tip(URDF)', tipU.x.toFixed(3), tipU.y.toFixed(3), tipU.z.toFixed(3),
    '| dist', (dist * 100).toFixed(1).padStart(5), 'cm | aim', aim.toFixed(2).padStart(5), '°');
}
console.log(`\n最差瞄准误差: ${worst.toFixed(2)}° · ${pass} 通过 / ${fail} 失败`);
process.exit(fail ? 1 : 0);

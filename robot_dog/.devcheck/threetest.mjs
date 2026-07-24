import * as THREE from 'three';
const JOINTS = [
  { name:'shoulder_pan',  xyz:[0,-0.0452,0.0165], rpy:[1.57079,0,0],       axis:[0,1,0], min:-2,        max:2 },
  { name:'shoulder_lift', xyz:[0,0.1025,0.0306],  rpy:[-1.8,0,0],          axis:[1,0,0], min:0,         max:3.5 },
  { name:'elbow_flex',    xyz:[0,0.11257,0.028],  rpy:[1.57079,0,0],       axis:[1,0,0], min:-Math.PI,  max:0 },
  { name:'wrist_flex',    xyz:[0,0.0052,0.1349],  rpy:[-1,0,0],            axis:[1,0,0], min:-2.5,      max:1.2 },
  { name:'wrist_roll',    xyz:[0,-0.0601,0],      rpy:[0,1.57079,0],       axis:[0,1,0], min:-Math.PI,  max:Math.PI },
  { name:'gripper',       xyz:[-0.0202,-0.0244,0],rpy:[0,Math.PI,0],       axis:[0,0,1], min:-0.2,      max:2 },
];
const POSE = {
  home:  [ 0,    0.285, -0.792,  1.200,  0,     0.35],
  close: [ 0,    0.452, -0.635,  0.915,  0,     0.35],
  orbL:  [-0.30, 0.593, -0.980,  1.200,  0.552, 0.35],
};
const AXIS_VEC = JOINTS.map(j => new THREE.Vector3(...j.axis).normalize());
function build(order){
  const root=new THREE.Group(); root.rotation.x=-Math.PI/2;
  const links=[],rotors=[];
  const base=new THREE.Group(); root.add(base); links.push(base);
  let parent=base;
  for(let i=0;i<6;i++){const j=JOINTS[i];
    const o=new THREE.Group(); o.position.set(...j.xyz); o.rotation.set(j.rpy[0],j.rpy[1],j.rpy[2],order);
    parent.add(o);
    const r=new THREE.Group(); o.add(r); rotors.push(r);
    const l=new THREE.Group(); r.add(l); links.push(l); parent=l;}
  const tcp=new THREE.Object3D(); tcp.position.set(0,-0.045,0); links[6].add(tcp);
  const gripLink=links[5];
  return {root,rotors,tcp,gripLink};
}
function run(order,pose){
  const{root,rotors,tcp,gripLink}=build(order);
  const scene=new THREE.Scene(); scene.add(root);
  for(let i=0;i<6;i++)rotors[i].quaternion.setFromAxisAngle(AXIS_VEC[i],pose[i]);
  root.updateMatrixWorld(true);
  const p=tcp.getWorldPosition(new THREE.Vector3());
  const g=new THREE.Vector3(0,-1,0).applyQuaternion(gripLink.getWorldQuaternion(new THREE.Quaternion()));
  return {p,g};
}
// 求解器(URDF系)参考值：URDF(x,y,z) → three(x, z, -y)
const REF={ // [tip_urdf, gaze_urdf] from solve5/j5test
  home: {tip:[0,-0.157,0.157], gaze:[0,-0.857,-0.512]},
  close:{tip:[0,-0.185,0.135], gaze:[0,-0.926,-0.375]},
};
const S_three=[0,0.105,0.22];
for(const order of ['ZYX','XYZ']){
  let maxErr=0;
  for(const[name,ref]of Object.entries(REF)){
    const{p,g}=run(order,POSE[name]);
    const exp=[ref.tip[0],ref.tip[2],-ref.tip[1]];
    const err=Math.hypot(p.x-exp[0],p.y-exp[1],p.z-exp[2])*1000;
    maxErr=Math.max(maxErr,err);
    // 瞄准角 vs 被摄物
    const d=[S_three[0]-p.x,S_three[1]-p.y,S_three[2]-p.z];
    const dist=Math.hypot(...d);
    const aim=Math.acos(Math.min(1,Math.max(-1,(g.x*d[0]+g.y*d[1]+g.z*d[2])/dist)))*180/Math.PI;
    console.log(order,name,'tcp three:',[p.x,p.y,p.z].map(v=>(v*100).toFixed(1)).join(','),' err',err.toFixed(1),'mm  aim',aim.toFixed(2),'°');
  }
  console.log(order,'=> max tcp error:',maxErr.toFixed(1),'mm\n');
}

// —— 修正方案：camMount.rotation.set(-π/2, 0, -0.35, 'ZXY')，挂在 links[5] ——
function runCam(order,pose){
  const{root,rotors,gripLink}=build(order);
  const scene=new THREE.Scene(); scene.add(root);
  const mount=new THREE.Object3D();
  mount.position.set(0,-0.012,0.012);
  mount.rotation.set(-Math.PI/2,0,-0.35,'ZXY');
  gripLink.add(mount);
  for(let i=0;i<6;i++)rotors[i].quaternion.setFromAxisAngle(AXIS_VEC[i],pose[i]);
  root.updateMatrixWorld(true);
  const fwd=new THREE.Vector3(0,0,-1).applyQuaternion(mount.getWorldQuaternion(new THREE.Quaternion()));
  const pos=mount.getWorldPosition(new THREE.Vector3());
  return {fwd,pos};
}
for(const[name,pose]of Object.entries(POSE)){
  const{fwd,pos}=runCam('ZYX',pose);
  const d=[S_three[0]-pos.x,S_three[1]-pos.y,S_three[2]-pos.z];
  const dist=Math.hypot(...d);
  const aim=Math.acos(Math.min(1,Math.max(-1,(fwd.x*d[0]+fwd.y*d[1]+fwd.z*d[2])/dist)))*180/Math.PI;
  console.log('camMount',name,'aim',aim.toFixed(2),'° dist',(dist*100).toFixed(1),'cm');
}

import * as THREE from 'three';
const JOINTS = [
  { xyz:[0,-0.0452,0.0165], rpy:[1.57079,0,0],       axis:[0,1,0]},
  { xyz:[0,0.1025,0.0306],  rpy:[-1.8,0,0],          axis:[1,0,0]},
  { xyz:[0,0.11257,0.028],  rpy:[1.57079,0,0],       axis:[1,0,0]},
  { xyz:[0,0.0052,0.1349],  rpy:[-1,0,0],            axis:[1,0,0]},
  { xyz:[0,-0.0601,0],      rpy:[0,1.57079,0],       axis:[0,1,0]},
  { xyz:[-0.0202,-0.0244,0],rpy:[0,Math.PI,0],       axis:[0,0,1]},
];
const POSES = {
  home:  [ 0,    0.285, -0.792,  1.200,  0,     0.35],
  close: [ 0,    0.452, -0.635,  0.915,  0,     0.35],
  far:   [ 0,    0.431, -0.894,  1.200,  0,     0.35],
  top:   [ 0,    0.663, -1.009,  1.200,  0,     0.35],
  low:   [ 0,    0.000, -0.297,  0.793,  0,     0.35],
  orbL:  [-0.30, 0.593, -0.980,  1.200,  0.552, 0.35],
  orbR:  [ 0.30, 0.593, -0.980,  1.200, -0.552, 0.35],
};
const AX = JOINTS.map(j => new THREE.Vector3(...j.axis).normalize());
const S=[0,0.105,0.22];
function test(mountPos, yaw){
  const root=new THREE.Group(); root.rotation.x=-Math.PI/2;
  const links=[],rotors=[];
  const base=new THREE.Group(); root.add(base); links.push(base);
  let parent=base;
  for(let i=0;i<6;i++){const j=JOINTS[i];
    const o=new THREE.Group(); o.position.set(...j.xyz); o.rotation.set(j.rpy[0],j.rpy[1],j.rpy[2],'ZYX');
    parent.add(o);
    const r=new THREE.Group(); o.add(r); rotors.push(r);
    const l=new THREE.Group(); r.add(l); links.push(l); parent=l;}
  const mount=new THREE.Object3D();
  mount.position.set(...mountPos);
  mount.rotation.set(-Math.PI/2,0,yaw,'ZXY');
  links[5].add(mount);
  const scene=new THREE.Scene(); scene.add(root);
  let out=[];
  for(const[n,pose]of Object.entries(POSES)){
    for(let i=0;i<6;i++)rotors[i].quaternion.setFromAxisAngle(AX[i],pose[i]);
    root.updateMatrixWorld(true);
    const fwd=new THREE.Vector3(0,0,-1).applyQuaternion(mount.getWorldQuaternion(new THREE.Quaternion()));
    const pos=mount.getWorldPosition(new THREE.Vector3());
    const d=[S[0]-pos.x,S[1]-pos.y,S[2]-pos.z];
    const dist=Math.hypot(...d);
    const aim=Math.acos(Math.min(1,Math.max(-1,(fwd.x*d[0]+fwd.y*d[1]+fwd.z*d[2])/dist)))*180/Math.PI;
    out.push(n+' '+aim.toFixed(1)+'°');
  }
  console.log('pos('+mountPos.join(',')+') yaw '+yaw.toFixed(2)+' →', out.join('  '));
}
test([-0.0356,-0.0667,0], -0.35);   // 精确指尖点
test([-0.025,-0.045,0.01], -0.35);  // 指尖后上方
test([-0.02,-0.03,0.012], -0.35);   // 更靠后
test([-0.025,-0.045,0.01], -0.30);
test([-0.025,-0.045,0.01], -0.42);

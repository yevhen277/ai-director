// SO-ARM100 FK check per URDF Simulation/SO100/so100.urdf
const D=Math.PI/180;
const J=[ // name, origin xyz, origin rpy, axis
 ['pan',  [0,-0.0452,0.0165],[1.57079,0,0],[0,1,0]],
 ['lift', [0,0.1025,0.0306],[-1.8,0,0],[1,0,0]],
 ['elbow',[0,0.11257,0.028],[1.57079,0,0],[1,0,0]],
 ['wflex',[0,0.0052,0.1349],[-1,0,0],[1,0,0]],
 ['wroll',[0,-0.0601,0],[0,1.57079,0],[0,1,0]],
 ['grip', [-0.0202,-0.0244,0],[0,3.14158,0],[0,0,1]],
];
function rpy2m([r,p,y]){ // Rz(y)*Ry(p)*Rx(r)
 const [cr,sr]=[Math.cos(r),Math.sin(r)],[cp,sp]=[Math.cos(p),Math.sin(p)],[cy,sy]=[Math.cos(y),Math.sin(y)];
 return [[cy*cp, cy*sp*sr-sy*cr, cy*sp*cr+sy*sr],
         [sy*cp, sy*sp*sr+cy*cr, sy*sp*cr-cy*sr],
         [-sp,   cp*sr,          cp*cr         ]];}
function axisRot(a,q){const[x,y,z]=a,[c,s]=[Math.cos(q),Math.sin(q)],C=1-c;
 return [[c+x*x*C, x*y*C-z*s, x*z*C+y*s],[y*x*C+z*s, c+y*y*C, y*z*C-x*s],[z*x*C-y*s, z*y*C+x*s, c+z*z*C]];}
const mm=(A,B)=>A.map((r,i)=>B[0].map((_,j)=>r[0]*B[0][j]+r[1]*B[1][j]+r[2]*B[2][j]));
const mv=(A,v)=>[A[0][0]*v[0]+A[0][1]*v[1]+A[0][2]*v[2],A[1][0]*v[0]+A[1][1]*v[1]+A[1][2]*v[2],A[2][0]*v[0]+A[2][1]*v[1]+A[2][2]*v[2]];
const add=(a,b)=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]];
function fk(q){let R=[[1,0,0],[0,1,0],[0,0,1]],p=[0,0,0];
 for(let i=0;i<6;i++){const[,xyz,rpy,axis]=J[i];
  R=mm(R,rpy2m(rpy)); p=add(p,mv(R,xyz)); // wait: translate THEN rotate is wrong order; fix below
 }
 return {R,p};}
// correct: p_new = p + R_prev*xyz ; R_new = R_prev*Rrpy*Raxis(q)
function fk2(q){let R=[[1,0,0],[0,1,0],[0,0,1]],p=[0,0,0];
 for(let i=0;i<6;i++){const[,xyz,rpy,axis]=J[i];
  p=add(p,mv(R,xyz)); R=mm(mm(R,rpy2m(rpy)),axisRot(axis,q[i]));}
 return {R,p};}
const f=(v)=>v.map(x=>(x*100).toFixed(1).padStart(7)).join(' ');
const poses={
 zero:[0,0,0,0,0,0],
 home:[0,1.05,-1.25,0.75,0,0.35],
 reach:[0,1.30,-0.90,0.50,0,0.35],
 far:[0,0.70,-1.50,1.05,0,0.35],
 high:[0,1.55,-0.60,-1.00,0,0.35],
 low:[0,0.55,-1.55,1.25,0,0.35],
 orbitL:[-0.95,1.05,-1.25,0.75,0,0.35],
 orbitR:[0.95,1.05,-1.25,0.75,0,0.35],
};
const out={};
for(const[n,q]of Object.entries(poses)){const{R,p}=fk2(q);
 const tip=add(p,mv(R,[0,-0.045,0])); // tcp: 4.5cm past jaw along -Y
 const gaze=mv(R,[0,-1,0]);
 out[n]={tip,gaze};
 console.log(n.padEnd(7),'tcp',f(tip),' gaze',f(gaze));}
// subject candidate: from home tcp along gaze 9cm
const h=out.home; let S=add(h.tip,h.gaze.map(x=>x*0.09));
S=[S[0],S[1],Math.max(0.10,Math.min(0.16,S[2]))];
console.log('\nSUBJECT S =',f(S));
for(const[n]of Object.entries(poses)){const{tip,gaze}=out[n];
 const d=[S[0]-tip[0],S[1]-tip[1],S[2]-tip[2]];
 const dist=Math.hypot(...d);
 const cos=(gaze[0]*d[0]+gaze[1]*d[1]+gaze[2]*d[2])/dist;
 console.log(n.padEnd(7),'dist_to_S',(dist*100).toFixed(1).padStart(6),'cm  aim_deg',(Math.acos(Math.min(1,Math.max(-1,cos)))/D).toFixed(1).padStart(6));}

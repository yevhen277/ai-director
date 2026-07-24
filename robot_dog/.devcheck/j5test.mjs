const J=[[[0,-0.0452,0.0165],[1.57079,0,0],[0,1,0]],[[0,0.1025,0.0306],[-1.8,0,0],[1,0,0]],[[0,0.11257,0.028],[1.57079,0,0],[1,0,0]],[[0,0.0052,0.1349],[-1,0,0],[1,0,0]],[[0,-0.0601,0],[0,1.57079,0],[0,1,0]],[[-0.0202,-0.0244,0],[0,3.14158,0],[0,0,1]]];
function rpy2m([r,p,y]){const[cr,sr]=[Math.cos(r),Math.sin(r)],[cp,sp]=[Math.cos(p),Math.sin(p)],[cy,sy]=[Math.cos(y),Math.sin(y)];
 return[[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],[sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]];}
function ax(a,q){const[x,y,z]=a,[c,s]=[Math.cos(q),Math.sin(q)],C=1-c;
 return[[c+x*x*C,x*y*C-z*s,x*z*C+y*s],[y*x*C+z*s,c+y*y*C,y*z*C-x*s],[z*x*C-y*s,z*y*C+x*s,c+z*z*C]];}
const mm=(A,B)=>A.map((r,i)=>B[0].map((_,j)=>r[0]*B[0][j]+r[1]*B[1][j]+r[2]*B[2][j]));
const mv=(A,v)=>[A[0][0]*v[0]+A[0][1]*v[1]+A[0][2]*v[2],A[1][0]*v[0]+A[1][1]*v[1]+A[1][2]*v[2],A[2][0]*v[0]+A[2][1]*v[1]+A[2][2]*v[2]];
const add=(a,b)=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]],sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
const nrm=v=>Math.hypot(...v);
// returns R at wrist (before J5), tip, gaze
function fkW(q){let R=[[1,0,0],[0,1,0],[0,0,1]],p=[0,0,0];let Rwrist=null;
 for(let i=0;i<6;i++){const[xyz,rpy,a]=J[i];p=add(p,mv(R,xyz));R=mm(R,rpy2m(rpy));
  if(i===4)Rwrist=R; // frame of joint5 before its rotation
  R=mm(R,ax(a,q[i]));}
 return{Rwrist,tip:add(p,mv(R,[0,-0.045,0])),gaze:mv(R,[0,-1,0])};}
const S=[0,-0.22,0.105];
const home=[0,0.283,-0.792,1.2,0,0.35];
const{Rwrist,gaze}=fkW(home);
const axisW=mv(Rwrist,[0,1,0]);
console.log('J5 axis(world):',axisW.map(x=>x.toFixed(3)).join(','),' gaze:',gaze.map(x=>x.toFixed(3)).join(','));
console.log('dot(axis,gaze)=',(axisW[0]*gaze[0]+axisW[1]*gaze[1]+axisW[2]*gaze[2]).toFixed(3));
for(const j5 of[-1.2,-0.6,0,0.6,1.2]){const q=[...home];q[4]=j5;
 const{tip,gaze:g}=fkW(q);const d=sub(S,tip),dist=nrm(d);
 const aim=Math.acos(Math.min(1,Math.max(-1,(g[0]*d[0]+g[1]*d[1]+g[2]*d[2])/dist)))*180/Math.PI;
 const az=Math.atan2(g[0],-g[1])*180/Math.PI;
 console.log('J5='+j5,' gaze',g.map(x=>x.toFixed(2)).join(','),' azim(rel -Y)',az.toFixed(1),'° aim',aim.toFixed(1),'°');}

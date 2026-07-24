const J=[[[0,-0.0452,0.0165],[1.57079,0,0],[0,1,0]],[[0,0.1025,0.0306],[-1.8,0,0],[1,0,0]],[[0,0.11257,0.028],[1.57079,0,0],[1,0,0]],[[0,0.0052,0.1349],[-1,0,0],[1,0,0]],[[0,-0.0601,0],[0,1.57079,0],[0,1,0]],[[-0.0202,-0.0244,0],[0,3.14158,0],[0,0,1]]];
const LIM=[[-2,2],[0,3.5],[-Math.PI,0],[-2.5,1.2],[-Math.PI,Math.PI],[-0.2,2]];
function rpy2m([r,p,y]){const[cr,sr]=[Math.cos(r),Math.sin(r)],[cp,sp]=[Math.cos(p),Math.sin(p)],[cy,sy]=[Math.cos(y),Math.sin(y)];
 return[[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],[sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]];}
function ax(a,q){const[x,y,z]=a,[c,s]=[Math.cos(q),Math.sin(q)],C=1-c;
 return[[c+x*x*C,x*y*C-z*s,x*z*C+y*s],[y*x*C+z*s,c+y*y*C,y*z*C-x*s],[z*x*C-y*s,z*y*C+x*s,c+z*z*C]];}
const mm=(A,B)=>A.map((r,i)=>B[0].map((_,j)=>r[0]*B[0][j]+r[1]*B[1][j]+r[2]*B[2][j]));
const mv=(A,v)=>[A[0][0]*v[0]+A[0][1]*v[1]+A[0][2]*v[2],A[1][0]*v[0]+A[1][1]*v[1]+A[1][2]*v[2],A[2][0]*v[0]+A[2][1]*v[1]+A[2][2]*v[2]];
const add=(a,b)=>[a[0]+b[0],a[1]+b[1],a[2]+b[2]],sub=(a,b)=>[a[0]-b[0],a[1]-b[1],a[2]-b[2]];
const nrm=v=>Math.hypot(...v);
function fk(q){let R=[[1,0,0],[0,1,0],[0,0,1]],p=[0,0,0];
 for(let i=0;i<6;i++){const[xyz,rpy,a]=J[i];p=add(p,mv(R,xyz));R=mm(mm(R,rpy2m(rpy)),ax(a,q[i]));}
 return{tip:add(p,mv(R,[0,-0.045,0])),gaze:mv(R,[0,-1,0])};}
const S=[0,-0.22,0.105];
function cost(q,T){const{tip,gaze}=fk(q);const d=sub(S,tip),dist=nrm(d);
 const aim=Math.acos(Math.min(1,Math.max(-1,(gaze[0]*d[0]+gaze[1]*d[1]+gaze[2]*d[2])/dist)));
 const e=sub(tip,T);return 9*(e[0]**2+e[1]**2+e[2]**2)+aim*aim;}
function solve(T,seed){let best=[...seed],bc=cost(best,T),step=0.35;
 for(let it=0;it<900&&bc>1e-9;it++){let moved=false;
  for(const j of[1,2,3]){for(const s of[1,-1]){const c=[...best];c[j]+=s*step;
   if(c[j]<LIM[j][0]||c[j]>LIM[j][1])continue;const cc=cost(c,T);
   if(cc<bc){best=c;bc=cc;moved=true;}}}
  if(!moved){step*=0.5;if(step<1e-4)break;}}
 return{best,bc};}
function report(name,T,seed){
 let best=null;
 for(let r=0;r<24;r++){const s0=seed.map((v,i)=>i===0||i>3?v:v+(Math.random()-0.5)*0.8);
  const{best:b,bc}=solve(T,s0);if(!best||bc<best.bc)best={b,bc};}
 const{b,bc}=best;const{tip,gaze}=fk(b);const d=sub(S,tip),dist=nrm(d);
 const aim=Math.acos(Math.min(1,Math.max(-1,(gaze[0]*d[0]+gaze[1]*d[1]+gaze[2]*d[2])/dist)))*180/Math.PI;
 const perr=nrm(sub(tip,T))*1000;
 console.log(name.padEnd(8),'q =',b.map(x=>x.toFixed(3)).join(', '),' | aim',aim.toFixed(1),'°  perr',perr.toFixed(0),'mm  distS',(dist*100).toFixed(1),'cm  tip',tip.map(x=>(x*100).toFixed(1)).join(','));
 return b;}
console.log('Subject S =',S.join(', '));
const home =report('home', [0,-0.15,0.165],[0,1.0,-1.2,0.8,0,0.35]);
const close=report('close',[0,-0.185,0.135],[0,1.1,-1.1,0.6,0,0.35]);
const far  =report('far',  [0,-0.075,0.225],[0,0.8,-1.4,1.0,0,0.35]);
const top  =report('top',  [0,-0.175,0.26],[0,1.5,-0.7,-0.9,0,0.35]);
const low  =report('low',  [0,-0.10,0.075],[0,0.6,-1.5,1.2,0,0.35]);
const orb0 =report('orbit0',[0,-0.1219,0.158],[0,1.0,-1.2,0.8,0,0.35]); // radius .22, dist~.11
// orbit aim check with pure J1 sweep
for(const th of[-0.6,-0.3,0,0.3,0.6]){const q=[th,...orb0.slice(1)];const{tip,gaze}=fk(q);
 const d=sub(S,tip),dist=nrm(d);const aim=Math.acos(Math.min(1,Math.max(-1,(gaze[0]*d[0]+gaze[1]*d[1]+gaze[2]*d[2])/dist)))*180/Math.PI;
 console.log('orbit J1='+th,' aim',aim.toFixed(1),'°  dist',(dist*100).toFixed(1),'cm  tcpR',(Math.hypot(tip[0],tip[1])*100).toFixed(1),'cm');}

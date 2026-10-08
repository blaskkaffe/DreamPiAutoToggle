// Snow background module, page side: a snowstorm in soft fog, rendered in 3D with WebGL (one draw call of point sprites with perspective, a depth of field
// that blurs the flakes near and far, and a sky and a drifting fog made in a fragment shader). The day and the night follow S.daylight.elev from /api (the
// sun's height at the place of the common time zone), so the sky is dark at night, light by day and warm for a little while at dawn and dusk; or "always
// day" / "always night" (S.snow.time). Drawn at half the screen's size (the scaling is part of the softness) and at most 30 times a second; paused while the
// page is hidden. Without WebGL a plain 2D canvas draws a simpler snowfall.
background("snow",function(host){
 var cv=h("canvas",{id:"snowbg","aria-hidden":"true"});host.appendChild(cv);
 var AMOUNT={light:.25,normal:.5,heavy:.8,blizzard:1},WIND={calm:.12,breeze:.55,storm:1.7},FOG={none:0,light:.8,thick:1.5},MAXN=3500;
 function cfg(){var c=S.snow||{};return {n:AMOUNT[c.amount]||.5,wind:WIND[c.wind]||.55,fog:FOG[c.fog]!==undefined?FOG[c.fog]:.55,time:c.time||"follow"}}
 function target(c){if(c.time==="day")return 1;if(c.time==="night")return 0;var e=S.daylight?S.daylight.elev:-20;return Math.max(0,Math.min(1,(e+8)/14))}
 function on(v){document.body.classList.toggle("snow-on",v);document.documentElement.classList.toggle("snow-on",v)}
 on(true);
 var gl=null;try{gl=cv.getContext("webgl",{antialias:false,alpha:false,premultipliedAlpha:true})||cv.getContext("experimental-webgl")}catch(e){}
 var day=target(cfg()),t0=Date.now(),last=0,w=0,hh=0;
 function resize(){var s=.5,nw=Math.max(320,Math.ceil(window.innerWidth*s)),nh=Math.max(180,Math.ceil(window.innerHeight*s));if(nw!==w||nh!==hh){w=cv.width=nw;hh=cv.height=nh;if(gl)gl.viewport(0,0,w,hh)}}
 window.addEventListener("resize",resize);resize();
 if(!gl)return fallback();
 var VS_SKY="attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}",
  FS_SKY="precision mediump float;uniform vec2 uRes;uniform float uTime,uDay,uFog,uWind,uPass;"+
   "float hs(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}"+
   "float nz(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hs(i),hs(i+vec2(1.,0.)),f.x),mix(hs(i+vec2(0.,1.)),hs(i+vec2(1.,1.)),f.x),f.y);}"+
   "float fbm(vec2 p){float a=.5,s=0.;for(int i=0;i<4;i++){s+=a*nz(p);p=p*2.03+vec2(1.7,9.2);a*=.5;}return s;}"+
   "void main(){vec2 uv=gl_FragCoord.xy/uRes;vec2 q=uv*vec2(uRes.x/uRes.y,1.)*1.7;"+
   "float f1=fbm(q+vec2(uTime*.018*(1.+uWind),-uTime*.004)),f2=fbm(q*2.3+vec2(uTime*.034*(1.+uWind),uTime*.009)+7.);"+
   "float fog=min(1.,smoothstep(.3,.7,f1*.62+f2*.38)*uFog);vec3 fogC=mix(vec3(.17,.21,.30),vec3(.93,.95,.98),uDay);"+
   "if(uPass>.5){float a=fog*.26;gl_FragColor=vec4(fogC*a,a);return;}"+
   "vec3 top=mix(vec3(.022,.036,.085),vec3(.60,.70,.81),uDay),bot=mix(vec3(.085,.115,.185),vec3(.90,.93,.96),uDay);"+
   "vec3 col=mix(bot,top,pow(uv.y,.8));float dusk=uDay*(1.-uDay)*4.;col+=vec3(.20,.09,.04)*dusk*pow(1.-uv.y,3.)*.55;"+
   "col=mix(col,fogC,fog*.78);col*=1.-.28*pow(length(uv-.5)*1.25,2.);gl_FragColor=vec4(col,1.);}",
  VS_P="attribute vec4 aS;uniform float uTime,uAspect,uFall,uWind,uPx;varying float vA,vB;"+
   "void main(){float z=aS.z,dp=mix(.45,3.2,z),spd=mix(1.,.5,z)*(.7+.6*aS.w),W=1.25*uAspect*dp,H=1.25*dp;"+
   "float sway=sin(uTime*.7+aS.w*40.)*.09*dp+sin(aS.y*9.+uTime*.35)*.05*dp*uWind;"+
   "float x=(aS.x*2.-1.)*W+uWind*uTime*spd*dp*.35+sway;float y=(aS.y*2.-1.)*H-uFall*uTime*spd*dp*.32;"+
   "x=mod(x+W,2.*W)-W;y=mod(y+H,2.*H)-H;"+
   "float blur=smoothstep(.0,.55,abs(z-.5));float sz=(.034+.03*aS.w)/dp*uPx*.5;"+
   "gl_PointSize=max(2.,sz*(1.+blur*2.6));vA=(.4+.6*aS.w)*mix(1.,.5,blur)*(1.-.35*z);vB=blur;"+
   "gl_Position=vec4(x/(uAspect*dp),y/dp,0.,1.);}",
  FS_P="precision mediump float;varying float vA,vB;uniform vec3 uFlake;"+
   "void main(){vec2 c=gl_PointCoord*2.-1.;float r=length(c);float a=1.-smoothstep(mix(.5,.0,vB),1.,r);a*=a*vA;if(a<.004)discard;gl_FragColor=vec4(uFlake*a,a);}";
 function sh(type,src){var s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS)){if(window.console)console.warn("snow shader: "+gl.getShaderInfoLog(s));gl=null;return null}return s}
 function prog(vs,fs){var a=sh(gl.VERTEX_SHADER,vs),b=gl&&sh(gl.FRAGMENT_SHADER,fs);if(!a||!b)return null;var p=gl.createProgram();gl.attachShader(p,a);gl.attachShader(p,b);gl.linkProgram(p);
  if(!gl.getProgramParameter(p,gl.LINK_STATUS)){gl=null;return null}return p}
 var pSky=prog(VS_SKY,FS_SKY),pPart=gl&&prog(VS_P,FS_P);
 if(!gl||!pSky||!pPart)return fallback();
 var quad=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,quad);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);      // one big triangle
 var seeds=new Float32Array(MAXN*4),i;for(i=0;i<seeds.length;i++)seeds[i]=Math.random();
 var pb=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,pb);gl.bufferData(gl.ARRAY_BUFFER,seeds,gl.STATIC_DRAW);
 function U(p,n){return gl.getUniformLocation(p,n)}
 var u={sky:{res:U(pSky,"uRes"),time:U(pSky,"uTime"),day:U(pSky,"uDay"),fog:U(pSky,"uFog"),wind:U(pSky,"uWind"),pass:U(pSky,"uPass")},
  part:{time:U(pPart,"uTime"),aspect:U(pPart,"uAspect"),fall:U(pPart,"uFall"),wind:U(pPart,"uWind"),px:U(pPart,"uPx"),flake:U(pPart,"uFlake")}};
 var aP=gl.getAttribLocation(pSky,"p"),aS=gl.getAttribLocation(pPart,"aS");
 function drawSky(pass,t,c){gl.useProgram(pSky);gl.bindBuffer(gl.ARRAY_BUFFER,quad);gl.enableVertexAttribArray(aP);gl.vertexAttribPointer(aP,2,gl.FLOAT,false,0,0);
  gl.uniform2f(u.sky.res,w,hh);gl.uniform1f(u.sky.time,t);gl.uniform1f(u.sky.day,day);gl.uniform1f(u.sky.fog,c.fog);gl.uniform1f(u.sky.wind,c.wind);gl.uniform1f(u.sky.pass,pass);gl.drawArrays(gl.TRIANGLES,0,3);gl.disableVertexAttribArray(aP)}
 function frame(now){requestAnimationFrame(frame);if(document.hidden||now-last<33)return;var dt=Math.min(.25,(now-last)/1000);last=now;resize();
  var c=cfg(),tg=target(c);day+=(tg-day)*Math.min(1,dt*.6);      // the sky eases to the day / night it should have
  var t=(Date.now()-t0)/1000,n=Math.min(MAXN,Math.floor(c.n*Math.min(MAXN,w*hh/150)));
  gl.disable(gl.BLEND);drawSky(0,t,c);gl.enable(gl.BLEND);gl.blendFunc(gl.ONE,gl.ONE_MINUS_SRC_ALPHA);
  gl.useProgram(pPart);gl.bindBuffer(gl.ARRAY_BUFFER,pb);gl.enableVertexAttribArray(aS);gl.vertexAttribPointer(aS,4,gl.FLOAT,false,0,0);
  gl.uniform1f(u.part.time,t);gl.uniform1f(u.part.aspect,w/hh);gl.uniform1f(u.part.fall,.55+.5*c.wind);gl.uniform1f(u.part.wind,c.wind);gl.uniform1f(u.part.px,hh);
  gl.uniform3f(u.part.flake,1-.2*day,1-.14*day,1-.07*day);gl.drawArrays(gl.POINTS,0,n);gl.disableVertexAttribArray(aS);
  if(c.fog>0)drawSky(1,t,c);gl.disable(gl.BLEND)}
 requestAnimationFrame(frame);
 // no WebGL: a sky gradient and soft round flakes on a 2D canvas
 function fallback(){var n2=h("canvas",{id:"snowbg","aria-hidden":"true"});host.replaceChild(n2,cv);cv=n2;resize();var g=cv.getContext("2d");if(!g)return;var fl=[],k;for(k=0;k<260;k++)fl.push({x:Math.random(),y:Math.random(),z:Math.random(),p:Math.random()*6});
  function loop(now){requestAnimationFrame(loop);if(document.hidden||now-last<50)return;last=now;resize();var c=cfg();day+=(target(c)-day)*.03;
   var gr=g.createLinearGradient(0,0,0,hh),mix=function(a,b){return Math.round(a+(b-a)*day)};
   gr.addColorStop(0,"rgb("+mix(6,153,0)+","+mix(9,179,0)+","+mix(22,207,0)+")");gr.addColorStop(1,"rgb("+mix(22,230,0)+","+mix(29,237,0)+","+mix(47,245,0)+")");
   g.fillStyle=gr;g.fillRect(0,0,w,hh);var n=Math.floor(fl.length*c.n),tt=now/1000;
   for(k=0;k<n;k++){var f=fl[k],r=(1.5+4*(1-f.z))*(w/640),x=((f.x+Math.sin(tt*.5+f.p)*.02+tt*.02*c.wind*(1-f.z*.5))%1+1)%1*w,y=((f.y+tt*.05*(1.2-f.z*.6))%1)*hh,
    rg=g.createRadialGradient(x,y,0,x,y,r*2);rg.addColorStop(0,"rgba(255,255,255,"+(.7-.4*f.z)+")");rg.addColorStop(1,"rgba(255,255,255,0)");g.fillStyle=rg;g.fillRect(x-r*2,y-r*2,r*4,r*4)}}
  requestAnimationFrame(loop)}
});

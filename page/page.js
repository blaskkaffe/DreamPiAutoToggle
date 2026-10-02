
function $(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
// Hooks: how the optional modules (modules/*/page.js, appended to this script) take part. A module calls
// hook(name, fn); this page calls fire(name, arg) at the matching moment. fire() is true if a hook returned true.
//   api(d) every /api answer   settingsOpen / settingsClose   escape (true = handled)   buttons(r) button settings loaded
//   posted after a form post
var HOOKS={};
function hook(name,fn){(HOOKS[name]=HOOKS[name]||[]).push(fn)}
function fire(name,arg){var handled=false;(HOOKS[name]||[]).forEach(function(f){try{if(f(arg)===true)handled=true}catch(e){if(window.console)console.error(name,e)}});return handled}
function ago(t,now){if(!t)return"";var s=Math.max(0,now-t);
 if(s<60)return"("+s+"s ago)";if(s<3600)return"("+Math.floor(s/60)+" min ago)";return"("+Math.floor(s/3600)+" h ago)"}
function dot(el,state){el.className="dot "+(state||"")}
// Status dot preview of the LED effect: [keyframes, slow s, fast s, timing]
var DOT_FX={blink:["blink",1,.4,"steps(1)"],ping:["ping",1.5,.98,"linear"],breathe:["breathe",4,1.6,"ease-in-out"],rgb:["rgbc",20,10,"linear"],
 rainbow:["rgbc",20,10,"linear"],scanner:["breathe",3,1.2,"ease-in-out"],comet:["breathe",3,1.2,"ease-in-out"],
 chase:["blink",.6,.24,"steps(1)"],twinkle:["breathe",3,1.2,"ease-in-out"]};
function lookDot(el,look){if(!look){el.className="dot";el.style.background="#333";el.style.animation="none";return}
 var f=DOT_FX[look.effect];el.className="dot";el.style.background=look.color;
 el.style.animation=f?f[0]+" "+(look.speed=="fast"?f[2]:f[1])+"s "+f[3]+" infinite":"none"}
var favNet="dcnow";
function render(d){
 pinNeeded=!!d.pin;
 // Hang up only while in a call (or while a hang up is still running)
 $("hang-row").style.display=(d.dreampi.state.indexOf("call")==0||(d.hangup&&d.hangup.busy))?"":"none";
 if(d.hangup){var hb=$("hang-b");
  if(d.hangup.busy){hb.disabled=true;hb.className="pill-s";
   hb.textContent=d.hangup.text?d.hangup.text.charAt(0).toUpperCase()+d.hangup.text.slice(1):"Hanging up..."}
  else if(hb.disabled){hb.disabled=false;hb.textContent="Hang up"}}
 $("warnings").innerHTML=d.warnings.map(function(w){return '<div class="warnbox">'+esc(w)+'</div>'}).join("");
 window.lastDreampiState=d.dreampi.state; lookDot($("d-dot"),d.dreampi.look); $("d-text").textContent=d.dreampi.text;
 $("m-text").textContent=d.modem.text; $("m-since").textContent=ago(d.modem.since,d.now).replace(/[()]/g,"");
 dot($("i-dot"),d.internet.state); $("i-text").textContent=d.internet.text;
 dot($("p-dot"),d.pi.state);
 $("p-text").innerHTML=d.pi.line1?'<span class="nw">'+esc(d.pi.line1)+'</span><span class="sub blk">'+esc(d.pi.line2)+
  (d.pi.warn?'<br>'+esc(d.pi.warn):'')+'</span>':esc(d.pi.text||"...");
 $("net").className="now rows "+d.network+($("net").classList.contains("open")?" open":"");
 if(d.network!=favNet){favNet=d.network;$("fav").href="/static/favicon-"+d.network+".png";$("touch").href="/static/touch-"+d.network+".png"} $("net-name").textContent=d.network=="dcnet"?"DCNET":"DCNow!";
 fire("api",d);
}
function toggleNet(el){el.classList.toggle("open");el.setAttribute("aria-expanded",el.classList.contains("open"))}
$("net").onclick=function(e){if(e.target.closest&&e.target.closest(".hang"))return;toggleNet(this)};
$("net").onkeydown=function(e){if((e.key=="Enter"||e.key==" ")&&e.target===this){e.preventDefault();toggleNet(this)}};
// Hang up: tap once to arm, again within 4 s to confirm (a call in progress is easy to end by accident)
var hangArm=0;
$("hang-f").onsubmit=function(e){e.preventDefault();e.stopPropagation();var b=$("hang-b");
 if(b.disabled)return;
 if(Date.now()-hangArm>4000){hangArm=Date.now();b.textContent="Tap again to hang up";b.className="pill-s arm";
  setTimeout(function(){if(Date.now()-hangArm>=4000&&!b.disabled){b.textContent="Hang up";b.className="pill-s"}},4100);return}
 hangArm=0;b.disabled=true;b.textContent="Hanging up...";b.className="pill-s";
 var x=new XMLHttpRequest();x.open("POST","/hangup",true);x.setRequestHeader("X-Requested-With","netswitch");x.onload=refresh;x.send()};
function showSettings(open){$("settings").classList.toggle("open",open);
 if(!open)fire("settingsClose");
 document.body.classList.toggle("settings-open",open);
 if(open){fire("settingsOpen");loadButtons();loadModules();loadAbout();loadUpdate()}}
// Updates: GET /update (cached GitHub check), POST /update/check, POST /update/start (runs git pull + the installer on the Pi).
var updTimer=null;
// The PIN (when one is set with install.sh --pin) is asked for once per page load, before update / restart / Wi-Fi connect.
var pinNeeded=false,pinValue="";
function withPin(go){if(!pinNeeded||pinValue)return go();var p=prompt("Enter the PIN");if(p===null)return;pinValue=p;go()}
function xhrJson(method,url,cb,body){var x=new XMLHttpRequest();x.open(method,url,true);
 if(method=="POST"){x.setRequestHeader("X-Requested-With","netswitch");if(pinValue)x.setRequestHeader("X-Netswitch-Pin",pinValue);
  if(body!==undefined)x.setRequestHeader("Content-Type","application/json")}
 x.onload=function(){var r=null;try{r=JSON.parse(x.responseText)}catch(e){}
  if(x.status==401||x.status==429)pinValue="";   // asked again next time
  cb(x.status==200?r:null,x.status,r)};x.onerror=function(){cb(null,0,null)};x.send(body===undefined?undefined:JSON.stringify(body))}
function loadUpdate(){xhrJson("GET","/update",function(r){if(r)renderUpdate(r);else if(updRunning)$("upd-text").textContent="Restarting the services..."})}
var updRunning=false,updWatched=false;   // updWatched: this page started or saw the update, so it reloads once when it is done
// The update log as a small console: one line per row, errors red, success green, nothing wider than the card.
function renderUpdLog(r){
 var lg=$("upd-log"),lines=r.log||[];
 lg.style.display=(lines.length&&r.state!="idle")?"block":"none";
 var stick=lg.scrollTop+lg.clientHeight>=lg.scrollHeight-8;
 lg.innerHTML=lines.map(function(l,i){
  var c=/\b(fail|failed|error|fatal|denied|cannot|could not|not found)\b/i.test(l)?"lerr":
   /^(ok|done|updated|installed|.*\b(already up to date|fast-forward)\b)/i.test(l)?"lok":
   /^(updating|running)\b/i.test(l)?"lhd":/^(from|remote:|\s*\d+ file|\s*create mode|\s*delete mode)/i.test(l)?"ldim":"";
  return '<div'+(c?' class="'+c+'"':'')+'>'+esc(l.slice(0,300))+'</div>'}).join("");
 if(stick)lg.scrollTop=lg.scrollHeight}
function renderUpdate(r){var a=r.addon,d=r.dreampi,msg;
 updRunning=r.state=="running";if(updRunning)updWatched=true;
 if(r.state=="running")msg="Updating... the page is unavailable for a few seconds while the services restart.";
 else if(r.state=="ok")msg=updWatched?"Updated. Reloading...":"The add-on was updated a few minutes ago.";
 else if(r.state=="failed")msg="The update failed. Details below.";
 else if(r.checking)msg="Checking...";
 else if(!r.time)msg="Not checked yet";
 else if(r.error)msg=r.error;
 else if(a&&a.available)msg="A newer add-on version is available: "+a.latest+(a.latest_date?" ("+a.latest_date.slice(0,10)+")":"")+(a.behind?", "+a.behind+" new change"+(a.behind>1?"s":""):"")+". You have "+a.current+".";
 else if(a&&a.available===false)msg="The add-on is up to date ("+a.current+").";
 else msg=(a&&a.note)||"Couldn't tell if the add-on is current.";
 if(a&&a.note&&a.available!==null&&!updRunning&&r.state=="idle")msg+=" "+a.note;
 $("upd-text").textContent=msg;
 var dp=$("upd-dreampi");dp.style.display="none";
 if(d&&d.newer&&r.state=="idle"){dp.style.display="block";
  dp.textContent="DreamPi has newer scripts: "+d.files.filter(function(f){return f.newer}).map(function(f){return f.name+" "+f.current+" \u2192 "+f.latest}).join(", ")+
   (d.auto_updates?". It updates itself when the Pi restarts with internet.":". Automatic updates are off (/boot/noautoupdates.txt exists).")}
 var show=!!(a&&a.available&&r.can_update&&r.state=="idle");
 $("upd-do-row").style.display=show?"flex":"none";
 $("upd-do-sub").textContent="Fetches the new version from GitHub and installs it ("+(r.branch||"main")+" branch). Settings are kept.";
 $("upd-check").disabled=!!r.checking||updRunning;
 renderUpdLog(r);
 if(r.state=="ok"&&updWatched){updWatched=false;setTimeout(function(){location.reload()},3000)}
 clearTimeout(updTimer);
 if(r.state=="running"||r.checking)updTimer=setTimeout(loadUpdate,2000)}
$("upd-check").onclick=function(){$("upd-text").textContent="Checking...";xhrJson("POST","/update/check",function(r){if(r)renderUpdate(r.status);
 clearTimeout(updTimer);updTimer=setTimeout(loadUpdate,1500)})};
$("upd-do").onclick=function(){if(!confirm("Update the add-on now? It is fetched from GitHub and installed; this page is unavailable for a few seconds."))return;
 withPin(function(){
  updRunning=true;updWatched=true;$("upd-text").textContent="Starting the update...";
  xhrJson("POST","/update/start",function(r,st,body){
   if(st==401||st==429){updRunning=false;updWatched=false;$("upd-text").textContent=(body&&body.message)||"PIN refused";return}
   if(r&&r.message&&r.message!="Update started"){updRunning=false;updWatched=false;$("upd-text").textContent=r.message}
   clearTimeout(updTimer);updTimer=setTimeout(loadUpdate,2000)})})};
// Reboot the Pi: confirm, ask the server, then wait until the page answers again and reload it.
$("reboot-b").onclick=function(){
 var inCall=(window.lastDreampiState||"").indexOf("call")==0;
 if(!confirm((inCall?"A call is in progress and will be cut. ":"")+"Reboot the Raspberry Pi now? It is back in about a minute."))return;
 var b=this,sub=$("reboot-sub");
 withPin(function(){b.disabled=true;
 xhrJson("POST","/reboot",function(r,st,body){
  if(!r||!r.started){b.disabled=false;sub.textContent=(r&&r.message)||(body&&body.message)||"Could not reboot";return}
  sub.textContent="Rebooting... this page comes back by itself.";
  var down=false,tries=0;
  (function poll(){tries++;
   var x=new XMLHttpRequest();x.open("GET","/ping?"+Date.now(),true);x.timeout=3000;
   x.onload=function(){if(down||tries>60)location.reload();else setTimeout(poll,2000)};
   x.onerror=x.ontimeout=function(){down=true;setTimeout(poll,2000)};x.send()})()})})};
// Modules menu: every installed module with a switch. Switching reloads the page, because a module's parts are built into it.
function loadModules(){xhrJson("GET","/modules",function(r){if(!r)return;
 $("mod-list").innerHTML=r.modules.map(function(m){
  return '<div class="srow"><span>'+esc(m.title)+'<span class="sub">'+esc(m.description)+(m.note?'<br>'+esc(m.note):'')+
   (m.error?'<br><b class="modbad">Could not load: '+esc(m.error)+'</b>':'')+'</span></span>'+
   '<input type="checkbox" class="cbox dcnow" data-module="'+esc(m.name)+'" aria-label="'+esc(m.title)+'"'+(m.enabled?' checked':'')+'></div>'}).join("")||
  '<div class="sub" style="padding:12px 0">No modules installed.</div>';
 Array.prototype.forEach.call($("mod-list").querySelectorAll("input[data-module]"),function(c){c.onchange=function(){
  c.disabled=true;
  xhrJson("POST","/modules",function(res){
   if(!res){c.disabled=false;c.checked=!c.checked;return}
   try{sessionStorage.setItem("netswitch-reopen","1")}catch(e){}
   location.reload()},{name:c.dataset.module,enabled:c.checked})}})})}
function loadAbout(){var x=new XMLHttpRequest();x.open("GET","/about",true);
 x.onload=function(){if(x.status!=200)return;$("about").innerHTML=JSON.parse(x.responseText).map(function(r){
  return '<tr><td class="n">'+esc(r[0])+'</td><td>'+esc(r[1])+'</td></tr>'}).join("")};x.send()}
$("cog").onclick=function(){showSettings(true)};
$("close-settings").onclick=function(){showSettings(false)};
document.addEventListener("keydown",function(e){if(e.key=="Escape"){if(!fire("escape"))showSettings(false)}});
var wifiInstalled=false;
var btn=null,btnTimer=null;
// Button functions come as [name, label, group, needs Wi-Fi setup, description]: push buttons and
// toggle switches in two groups; the Wi-Fi switch functions only show once Wi-Fi setup is installed
// (or while one is already selected).
var btnFunctions=[];
function fillFunctions(id,current){var groups={},order=[];
 btnFunctions.forEach(function(f){if(f[3]&&!wifiInstalled&&f[0]!=current)return;
  if(!groups[f[2]]){groups[f[2]]=[];order.push(f[2])}
  groups[f[2]].push('<option value="'+f[0]+'">'+esc(f[1])+'</option>')});
 $(id).innerHTML=order.map(function(g){return '<optgroup label="'+esc(g)+'">'+groups[g].join("")+'</optgroup>'}).join("")}
function describeButtons(){[1,2].forEach(function(n){var name=btn["button"+n+"_function"],d="";
 btnFunctions.forEach(function(f){if(f[0]==name)d=f[4]});$("btn"+n+"-sub").textContent=d})}
function loadButtons(){var x=new XMLHttpRequest();x.open("GET","/buttonconfig",true);
 x.onload=function(){if(x.status!=200)return;var r=JSON.parse(x.responseText);
  btn=r.config;wifiInstalled=r.wifi;
  if(!$("btn1-gpio").options.length){var gOpts=r.gpios.map(function(g){return '<option value="'+g+'">GPIO'+g+'</option>'}).join("");
   $("btn1-gpio").innerHTML=gOpts;$("btn2-gpio").innerHTML=gOpts}
  btnFunctions=r.functions;fillFunctions("btn1-fn",btn.button1_function);fillFunctions("btn2-fn",btn.button2_function);
  $("btn1-gpio").value=btn.button1_gpio;$("btn1-fn").value=btn.button1_function;
  $("btn2-gpio").value=btn.button2_gpio;$("btn2-fn").value=btn.button2_function;describeButtons();
  fire("buttons",r)};x.send()}
function saveButtons(){clearTimeout(btnTimer);btnTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/buttonconfig",true);x.setRequestHeader("Content-Type","application/json");
 x.onload=function(){if(x.status!=200)return;var el=$("gpio-saved");el.classList.add("show");
  setTimeout(function(){el.classList.remove("show")},1200);loadButtons()};x.send(JSON.stringify(btn))},250)}
$("btn1-gpio").onchange=function(){btn.button1_gpio=parseInt(this.value,10);saveButtons()};
$("btn1-fn").onchange=function(){btn.button1_function=this.value;describeButtons();saveButtons()};
$("btn2-gpio").onchange=function(){btn.button2_gpio=parseInt(this.value,10);saveButtons()};
$("btn2-fn").onchange=function(){btn.button2_function=this.value;describeButtons();saveButtons()};
function refresh(){var x=new XMLHttpRequest();x.open("GET","/api",true);
 x.onload=function(){if(x.status==200)render(JSON.parse(x.responseText))};x.send()}
Array.prototype.forEach.call(document.forms,function(f){if(f.id=="hang-f")return;f.onsubmit=function(e){e.preventDefault();
 var x=new XMLHttpRequest();x.open("POST",f.getAttribute("action"),true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=function(){refresh();fire("posted")};x.send()}});
refresh(); setInterval(refresh,1000);
// back in Settings after switching a module (the page was reloaded)
setTimeout(function(){   // after the modules' scripts have registered their hooks
 try{if(sessionStorage.getItem("netswitch-reopen")){sessionStorage.removeItem("netswitch-reopen");showSettings(true)}}catch(e){}},0);

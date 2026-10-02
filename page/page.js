
function $(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
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
 var defName=d.default=="dcnet"?"DCNET":"DCNow!";
 $("default-b").className="switch "+d.default; $("default-l").textContent=d.default=="dcnet"?"DCNET":"DCNow!";
 $("reset-b").className="cbox "+d.default+(d.autoreset?" on":"");
 $("reset-note").textContent=" (Auto reset is "+(d.autoreset?"on, default: "+defName:"off")+")";
 $("debug-b").innerHTML=(d.debug?"&#9679; Recording":"Recording off");
 $("log-tools").style.display=d.debug?"inline":"none";
 $("log").style.display=(d.debug||logSize)?"block":"none";
 debugOn=d.debug;
 $("wifi-row").style.display=d.wifi.installed?"flex":"none";
 var wl=WIFI_LABELS[d.wifi.state]||WIFI_LABELS.idle;
 $("wifi-b").textContent=wl[0];
 $("wifi-sub").textContent=((d.wifi.demo&&d.wifi.state=="hosting")?"Pick a network below":wl[1].replace("%s",d.wifi.ssid||""))+(d.wifi.demo?" - DEMO: dummy networks, password \u201cdemo\u201d connects":"");
 $("wifi-b").disabled=d.wifi.state=="ok";
 var showNets=d.wifi.state=="hosting"||d.wifi.state=="scanning";
 $("wifi-networks").style.display=showNets?"block":"none";
 if(showNets&&d.wifi.networks){var key=JSON.stringify(d.wifi.networks);
  if(key!=wifiListKey){wifiListKey=key;renderWifiList(d.wifi.networks)}}
 else if(!showNets){wifiListKey=null;wifiChosen=null;$("wifi-form").style.display="none";$("wifi-list").innerHTML=""}
}
var WIFI_LABELS={
 idle:["Search","Search for a Wi-Fi network to connect the Pi to"],
 scanning:["Stop","Scanning for Wi-Fi networks..."],
 hosting:["Stop","Pick a network below, or connect to “DreamPi WiFi Config” and open http://192.168.4.1"],
 connecting:["Stop","Connecting to “%s”..."],
 ok:["Connected","Connected to “%s”"],
 failed:["Stop","Couldn't connect (%s)"]};
$("wifi-b").onclick=function(){
 var x=new XMLHttpRequest();x.open("POST","/wifitoggle",true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=refresh;x.send()};
// Wi-Fi network list, shown in Settings too while scanning/hosting (not just on the
// temporary "DreamPi WiFi Config" page) - useful when this page is still reachable,
// for example over Ethernet, while the Pi's Wi-Fi is being (re)configured.
var wifiListKey=null,wifiChosen=null;
function wifiBars(sig){if(sig==null)return"";var n=sig>=-55?4:sig>=-65?3:sig>=-75?2:1;return " "+"█".repeat(n)+"░".repeat(4-n)}
function renderWifiList(nets){
 $("wifi-list").innerHTML=nets.map(function(n,i){
  return '<button type="button" class="wnet" data-i="'+i+'">'+(n.secured?"🔒 ":"")+esc(n.ssid)+
   '<span class="sig">'+esc(wifiBars(n.signal))+'</span></button>'}).join("")||
  '<div class="sub" style="margin:4px 0 10px">No networks found. Enter one manually.</div>';
 Array.prototype.forEach.call($("wifi-list").querySelectorAll(".wnet"),function(b){
  b.onclick=function(){wifiSelect(nets[+b.dataset.i])}})}
function wifiSelect(n){wifiChosen=n;$("wifi-ssid").value=n.ssid;$("wifi-ssid").readOnly=true;
 $("wifi-pass").style.display=n.secured?"block":"none";$("wifi-pass").value="";
 $("wifi-connect-b").disabled=false;$("wifi-connect-b").textContent="Connect";$("wifi-form").style.display="block"}
$("wifi-manual").onclick=function(){wifiSelect({ssid:"",secured:true});$("wifi-ssid").readOnly=false;$("wifi-ssid").focus()};
$("wifi-connect-b").onclick=function(){
 var ssid=$("wifi-ssid").value.trim();if(!ssid)return;
 withPin(function(){
  $("wifi-connect-b").disabled=true;$("wifi-connect-b").textContent="Connecting...";
  xhrJson("POST","/wificonnect",function(r,st,body){
   if(st==401||st==429){$("wifi-connect-b").disabled=false;$("wifi-connect-b").textContent="Connect";alert((body&&body.message)||"PIN refused")}
   refresh()},{ssid:ssid,password:$("wifi-pass").value})})};
var logSize=0,debugOn=false,logBusy=false,debugOpen=false;
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
 if(!open){closePops();if(wbPreviewOn)setWbPreview(false)}
 document.body.classList.toggle("settings-open",open);if(open){loadLed();loadButtons();loadNumbers();loadAbout();loadUpdate()}}
// Phone numbers: five lists (one per action) kept in numbers.json; the hook matches what was dialed against their endings.
var numCfg=null,numTimer=null;
function loadNumbers(){var x=new XMLHttpRequest();x.open("GET","/numbers",true);
 x.onload=function(){if(x.status!=200)return;numCfg=JSON.parse(x.responseText);renderNumbers()};x.send()}
function renderNumbers(){if(!numCfg)return;
 $("num-list").innerHTML=numCfg.actions.map(function(a){var list=numCfg.numbers[a.key]||[];
  return '<div class="nrow" data-key="'+a.key+'"><b>'+esc(a.label)+'</b><span class="sub">'+esc(a.sub)+'</span>'+
   '<div class="nchips">'+(list.length?list.map(function(n,i){return '<span class="nchip">'+esc(n)+
    '<button type="button" data-key="'+a.key+'" data-i="'+i+'" aria-label="Remove '+esc(n)+'">&#10005;</button></span>'}).join(""):
    '<span class="nempty">No number: this action is off</span>')+'</div>'+
   '<div class="nadd"><input type="text" maxlength="'+numCfg.max+'" placeholder="Add a number" aria-label="Add a number for '+esc(a.label)+'" data-key="'+a.key+'">'+
   '<button type="button" class="pill-s" data-add="'+a.key+'">Add</button></div><div class="nmsg" data-msg="'+a.key+'"></div></div>'}).join("");
 Array.prototype.forEach.call($("num-list").querySelectorAll(".nchip button"),function(b){b.onclick=function(){
  numCfg.numbers[b.dataset.key].splice(+b.dataset.i,1);saveNumbers()}});
 Array.prototype.forEach.call($("num-list").querySelectorAll("button[data-add]"),function(b){b.onclick=function(){addNumber(b.dataset.add)}});
 Array.prototype.forEach.call($("num-list").querySelectorAll(".nadd input"),function(inp){inp.onkeydown=function(e){
  if(e.key=="Enter"){e.preventDefault();addNumber(inp.dataset.key)}}})}
function numMsg(key,text){var el=$("num-list").querySelector('[data-msg="'+key+'"]');if(el)el.textContent=text}
function addNumber(key){var inp=$("num-list").querySelector('.nadd input[data-key="'+key+'"]'),n=inp.value.replace(/[^0-9*#]/g,"");
 if(n.length<numCfg.min)return numMsg(key,"Needs at least "+numCfg.min+" digits, * or #");
 for(var i=0;i<numCfg.actions.length;i++){var a=numCfg.actions[i];
  if((numCfg.numbers[a.key]||[]).indexOf(n)>=0)return numMsg(key,n+" is already used by "+a.label)}
 if(numCfg.numbers[key].length>=numCfg.per_action)return numMsg(key,"At most "+numCfg.per_action+" numbers");
 numCfg.numbers[key].push(n);saveNumbers()}
function saveNumbers(){clearTimeout(numTimer);numTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/numbers",true);x.setRequestHeader("Content-Type","application/json");
 x.onload=function(){if(x.status!=200)return;numCfg=JSON.parse(x.responseText);renderNumbers();var el=$("num-saved");el.classList.add("show");
  setTimeout(function(){el.classList.remove("show")},1200)};x.send(JSON.stringify(numCfg.numbers))},100)}
$("num-defaults").onclick=function(){if(!numCfg)return;numCfg.numbers=JSON.parse(JSON.stringify(numCfg.defaults));saveNumbers()};
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
 else if(r.state=="failed")msg="The update failed. Details below; the guide shows how to update by hand.";
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
   (d.auto_updates?". It updates itself when the Pi restarts with internet.":". Automatic updates are off (/boot/noautoupdates.txt exists): see the guide below.")}
 var show=!!(a&&a.available&&r.can_update&&r.state=="idle");
 $("upd-do-row").style.display=show?"flex":"none";
 $("upd-do-sub").textContent="Fetches the new version from GitHub and installs it ("+(r.branch||"main")+" branch). Settings are kept.";
 $("upd-check").disabled=!!r.checking||updRunning;
 renderUpdLog(r);
 $("upd-cd").textContent="cd "+(r.src||"DreamPiAutoToggle");
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
function loadAbout(){var x=new XMLHttpRequest();x.open("GET","/about",true);
 x.onload=function(){if(x.status!=200)return;$("about").innerHTML=JSON.parse(x.responseText).map(function(r){
  return '<tr><td class="n">'+esc(r[0])+'</td><td>'+esc(r[1])+'</td></tr>'}).join("")};x.send()}
$("cog").onclick=function(){showSettings(true)};
$("close-settings").onclick=function(){showSettings(false)};
document.addEventListener("keydown",function(e){if(e.key=="Escape"){if(lvlCur||fxCur)closePops();else showSettings(false)}});
// Optional Dreamcast background (static/dc-background.js), remembered per browser
function bgWanted(){try{return localStorage.getItem("netswitch-bg")==="on"}catch(e){return false}}
function loadScript(src,done){var sc=document.createElement("script");sc.src=src;sc.onload=done;
 sc.onerror=function(){document.body.classList.remove("dcbg")};document.head.appendChild(sc)}
function setBg(on){
 try{localStorage.setItem("netswitch-bg",on?"on":"off")}catch(e){}
 $("bg-b").checked=on;document.body.classList.toggle("dcbg",on);document.documentElement.classList.toggle("dcbg",on);
 if(!on){if(window.DCBackground)DCBackground.stop();return}
 function go(){if(document.body.classList.contains("dcbg"))DCBackground.start($("dcbg"))}
 if(window.DCBackground)go();
 else if(window.THREE)loadScript("/static/dc-background.js",go);
 else loadScript("/static/three.min.js",function(){loadScript("/static/dc-background.js",go)})}
$("bg-b").onchange=function(){setBg(this.checked)};
if(bgWanted())setBg(true);
// Debug log menu: hidden unless switched on in settings, remembered per browser
function setDebugMenu(on){
 try{localStorage.setItem("netswitch-debug",on?"on":"off")}catch(e){}
 $("dbg-b").checked=on;$("debug-bar").style.display=on?"flex":"none";
 if(!on){debugOpen=false;$("debug").style.display="none";$("show-debug").classList.remove("open")}}
$("dbg-b").onchange=function(){setDebugMenu(this.checked)};
var led=null,ledDefaults=null,ledTimer=null,ledStates=[],ledGroups=[],ledEffects=[],ledCount=1,ledGpio=18;
var wbPreviewOn=false,wbHeartbeat=null;
var ledInstalled=false,ledHiddenFlag=false,wifiInstalled=false;
function updateGpioSection(){
 var ledOn=ledInstalled&&!ledHiddenFlag;
 $("gpio-led-row").style.display=ledOn?"flex":"none";
 $("gpio-wifi-row").style.display=wifiInstalled?"flex":"none"}
function loadLed(){var x=new XMLHttpRequest();x.open("GET","/ledconfig",true);
 x.onload=function(){if(x.status!=200)return;var r=JSON.parse(x.responseText);
  led=r.config;ledDefaults=r.defaults;ledStates=r.states;ledGroups=r.groups;ledEffects=r.effects;ledCount=r.count||1;ledGpio=r.gpio||18;
  $("led-section").style.display=(r.installed&&!r.hidden)?"block":"none";   // install.sh --led, not hidden
  ledInstalled=r.installed;ledHiddenFlag=r.hidden;updateGpioSection();
  $("led-count-t").textContent=ledCount>1?" ("+ledCount+" LEDs)":"";
  if(!$("led-order").options.length)$("led-order").innerHTML=r.orders.map(function(o){
   return '<option value="'+o+'">'+o+'</option>'}).join("");
  if(!$("led-gpio").options.length)$("led-gpio").innerHTML=r.gpios.map(function(g){
   return '<option value="'+g+'">GPIO'+g+'</option>'}).join("");
  $("led-count-i").value=ledCount;$("led-gpio").value=ledGpio;$("led-order").value=led.order;
  buildLed()};x.send()}
// Every message is one row of led.messages[key]: on/off, colour, effect + speed, level, LEDs.
function msgOf(st){return led.messages[st]}
function shortLabel(l){return l.split(" \u2014 ")[0]}   // the group heading already says DCNow! / DCNET / Netlink
function buildLed(){
 var html="";
 ledGroups.forEach(function(g){
  var items=ledStates.filter(function(s){return s[2]==g[0]});if(!items.length)return;
  var net=g[0].indexOf("call-")==0&&ledDefaults.messages[g[0]]?ledDefaults.messages[g[0]].color:"";
  html+='<tr class="grp"><td colspan="4">'+(net?'<span class="gdot" style="background:'+net+'"></span>':"")+esc(g[1])+'</td></tr>';
  items.forEach(function(s){var st=s[0];
   html+='<tr id="r-'+st+'"><td class="name"><input type="checkbox" class="cbox neutral" id="e-'+st+'" title="Show this message" aria-label="Show '+esc(s[1])+'"><span class="lbl-t">'+esc(shortLabel(s[1]))+
   (s[7]===false?'<small class="nd">not detected yet</small>':"")+'</span></td>'+
   '<td class="c"><input type="color" id="c-'+st+'" data-state="'+st+'" aria-label="Colour: '+esc(s[1])+'"></td>'+
   '<td class="c"><button type="button" class="chip fx" id="f-'+st+'" data-state="'+st+'" data-label="'+esc(s[1])+'" aria-label="Effect: '+esc(s[1])+'"></button></td>'+
   '<td class="c"><button type="button" class="chip lvl" id="l-'+st+'" data-state="'+st+'" data-label="'+esc(s[1])+'" aria-label="Level: '+esc(s[1])+'"></button></td></tr>'})});
 $("led-rows").innerHTML=html;
 ledStates.forEach(function(s){var st=s[0];
  $("c-"+st).addEventListener("input",function(){msgOf(st).color=this.value;showFx(st);saveLed()});
  $("e-"+st).onchange=function(){msgOf(st).enabled=this.checked;showRow(st);saveLed()};
  $("f-"+st).onclick=function(e){e.stopPropagation();openFx(this)};
  $("l-"+st).onclick=function(e){e.stopPropagation();openLvl(this)}});
 showLed()}
function effectName(e){for(var i=0;i<ledEffects.length;i++)if(ledEffects[i][0]==e)return ledEffects[i][1];return e}
function showLed(){$("led-bright").value=brightToSlider(led.max_brightness);$("led-bright-v").textContent=pct(led.max_brightness);
 $("led-order").value=led.order;
 showWb();
 ledStates.forEach(function(s){var st=s[0],c=msgOf(st);
  $("c-"+st).value=c.color;$("e-"+st).checked=c.enabled!==false;showRow(st);showFx(st);showLvl(st)})}
function showWb(){["r","g","b"].forEach(function(c){var v=Math.round(led.white_balance[c]*255);
 $("wb-"+c).value=v;$("wb-"+c+"-v").textContent=v})}
function showRow(st){$("r-"+st).className=msgOf(st).enabled===false?"dis":""}
function ledsText(L){return L[0]==L[1]?"LED "+L[0]:"LEDs "+L[0]+"-"+L[1]}
function showFx(st){var el=$("f-"+st);if(!el)return;var c=msgOf(st);
 var sub=[];if(c.effect!="solid")sub.push(c.speed);if(ledCount>1&&c.leds)sub.push(ledsText(c.leds));
 el.innerHTML=esc(effectName(c.effect))+(sub.length?"<small>"+sub.join(" \u00b7 ")+"</small>":"")}
function showLvl(st){var el=$("l-"+st);if(!el)return;var b=msgOf(st).brightness,own=b!==null&&b!==undefined;
 el.className="chip lvl"+(own?" on":"");el.textContent=pct(own?b:led.max_brightness)}
function placePop(pop,el){var box=pop.parentNode.getBoundingClientRect(),r=el.getBoundingClientRect();
 pop.classList.add("open");
 pop.style.left=Math.min(Math.max(r.right-box.left-pop.offsetWidth,0),box.width-pop.offsetWidth)+"px";
 pop.style.top=(r.bottom-box.top+6)+"px"}
var lvlCur=null,fxCur=null;
function closePops(){$("lvl-pop").classList.remove("open");$("fx-pop").classList.remove("open");
 lvlCur=fxCur=null}
var secMode="all";   // what the LEDs buttons of the open effect popup show: all | one | range
function openFx(el){closePops();var st=el.dataset.state,c=msgOf(st);fxCur=st;
 $("fx-t").textContent=el.dataset.label;
 $("fx-opts").innerHTML=ledEffects.filter(function(e){return !e[2]||ledCount>1||e[0]==c.effect}).map(function(e){
  return '<button type="button" class="pill-s" data-fx="'+e[0]+'">'+esc(e[1])+'</button>'}).join("");
 Array.prototype.forEach.call($("fx-opts").querySelectorAll("button"),function(b){b.onclick=function(){c.effect=b.dataset.fx;fxMark();saveLed()}});
 $("fx-sec").style.display=$("fx-sec-in").style.display=ledCount>1?"flex":"none";
 $("sec-a").max=$("sec-b").max=ledCount;
 secMode=!c.leds?"all":c.leds[0]==c.leds[1]?"one":"range";
 fxMark();placePop($("fx-pop"),el)}
function fxMark(){if(!fxCur)return;var c=msgOf(fxCur),fixed=c.effect=="solid";
 Array.prototype.forEach.call($("fx-opts").querySelectorAll("button"),function(b){b.className="pill-s"+(b.dataset.fx==c.effect?" sel":"")});
 Array.prototype.forEach.call($("fx-speed").querySelectorAll("button"),function(b){b.disabled=fixed;
  b.className="pill-s"+(!fixed&&b.dataset.speed==c.speed?" sel":"")});
 var L=c.leds;
 $("sec-all").className="pill-s"+(secMode=="all"?" sel":"");$("sec-one").className="pill-s"+(secMode=="one"?" sel":"");$("sec-range").className="pill-s"+(secMode=="range"?" sel":"");
 $("fx-sec-in").style.display=(ledCount>1&&secMode!="all")?"flex":"none";
 $("sec-b").style.display=$("sec-to").style.display=secMode=="range"?"":"none";
 $("sec-a").setAttribute("aria-label",secMode=="range"?"First LED":"LED");
 $("sec-a").value=L?L[0]:"";$("sec-b").value=L?L[1]:"";$("sec-a").placeholder="1";$("sec-b").placeholder=ledCount;
 showFx(fxCur)}
function setLeds(first,last){if(!fxCur)return;
 first=Math.max(1,Math.min(ledCount,first));last=Math.max(first,Math.min(ledCount,last));
 msgOf(fxCur).leds=[first,last];fxMark();saveLed()}
$("sec-all").onclick=function(){if(!fxCur)return;secMode="all";msgOf(fxCur).leds=null;fxMark();saveLed()};
$("sec-one").onclick=function(){if(!fxCur)return;var L=msgOf(fxCur).leds;secMode="one";setLeds(L?L[0]:1,L?L[0]:1)};
$("sec-range").onclick=function(){if(!fxCur)return;var L=msgOf(fxCur).leds;secMode="range";
 var a=L?L[0]:1,b=L&&L[1]>L[0]?L[1]:Math.min(ledCount,a+1);setLeds(a,b)};
function secInput(){if(!fxCur)return;var a=parseInt($("sec-a").value,10),b=parseInt($("sec-b").value,10);
 if(isNaN(a)&&isNaN(b))return;if(isNaN(a))a=1;if(isNaN(b))b=ledCount;
 if(secMode=="one")b=a;
 setLeds(Math.min(a,b),Math.max(a,b))}
$("sec-a").onchange=$("sec-b").onchange=secInput;
Array.prototype.forEach.call($("fx-speed").querySelectorAll("button"),function(b){b.onclick=function(){
 if(!fxCur)return;msgOf(fxCur).speed=b.dataset.speed;fxMark();saveLed()}});
$("fx-done").onclick=closePops;
function openLvl(el){closePops();var st=el.dataset.state,c=msgOf(st);
 if(c.brightness===null||c.brightness===undefined){c.brightness=led.max_brightness;showLvl(st);saveLed()}
 lvlCur=st;
 $("lvl-t").textContent=el.dataset.label;
 $("lvl-r").style.accentColor=c.color;$("lvl-r").value=brightToSlider(c.brightness);$("lvl-v").textContent=pct(c.brightness);
 placePop($("lvl-pop"),el)}
$("lvl-r").oninput=function(){if(!lvlCur)return;var b=Math.round(sliderToBright(this.value)*1000)/1000;
 msgOf(lvlCur).brightness=b;$("lvl-v").textContent=pct(b);showLvl(lvlCur);saveLed()};
$("lvl-base").onclick=function(){if(!lvlCur)return;msgOf(lvlCur).brightness=null;showLvl(lvlCur);saveLed();closePops()};
$("lvl-done").onclick=closePops;
$("lvl-pop").onclick=$("fx-pop").onclick=function(e){e.stopPropagation()};
$("settings").addEventListener("click",function(){if(lvlCur||fxCur)closePops()});
["r","g","b"].forEach(function(c){$("wb-"+c).oninput=function(){
 led.white_balance[c]=Math.round(this.value)/255;$("wb-"+c+"-v").textContent=Math.round(this.value);saveLed()}});
function setWbPreview(on){wbPreviewOn=on;$("wb-preview").classList.toggle("on",on);
 $("wb-preview").textContent=on?"Stop preview":"Preview on LED";
 clearInterval(wbHeartbeat);
 var x=new XMLHttpRequest();x.open("POST",on?"/wbtest":"/wbtestdone",true);x.setRequestHeader("X-Requested-With","netswitch");x.send();
 if(on)wbHeartbeat=setInterval(function(){
  var h=new XMLHttpRequest();h.open("POST","/wbtest",true);h.setRequestHeader("X-Requested-With","netswitch");h.send()},1000)}
$("wb-preview").onclick=function(){setWbPreview(!wbPreviewOn)};
$("wb-reset").onclick=function(){led.white_balance={r:1,g:1,b:1};showWb();saveLed()};
function saveLed(){clearTimeout(ledTimer);ledTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/ledconfig",true);x.setRequestHeader("Content-Type","application/json");
 led.count=ledCount;led.gpio=ledGpio;
 x.onload=function(){if(x.status!=200)return;var els=document.querySelectorAll(".led-saved");Array.prototype.forEach.call(els,function(e){e.classList.add("show")});
  setTimeout(function(){Array.prototype.forEach.call(els,function(e){e.classList.remove("show")})},1200);refresh()};x.send(JSON.stringify(led))},250)}
// Logarithmic slider: the left half covers 0-9 %, where an indicator LED is most useful.
var LOG_BASE=100;
function sliderToBright(p){return (Math.pow(LOG_BASE,p/1000)-1)/(LOG_BASE-1)}
function brightToSlider(b){return Math.round(1000*Math.log(1+b*(LOG_BASE-1))/Math.log(LOG_BASE))}
function pct(b){var v=b*100;return (v<10&&v>0?v.toFixed(1):Math.round(v))+"%"}
$("led-bright").oninput=function(){led.max_brightness=Math.round(sliderToBright(this.value)*1000)/1000;$("led-bright-v").textContent=pct(led.max_brightness);
 ledStates.forEach(function(s){showLvl(s[0])});saveLed()};
$("led-reset").onclick=function(){var order=led.order,wb=led.white_balance;   // wiring facts, not a look to reset
 led=JSON.parse(JSON.stringify(ledDefaults));led.order=order;led.white_balance=wb;showLed();saveLed()};
$("led-count-i").onchange=function(){var n=parseInt(this.value,10);
 if(isNaN(n))return;ledCount=Math.max(1,Math.min(300,n));this.value=ledCount;
 $("led-count-t").textContent=ledCount>1?" ("+ledCount+" LEDs)":"";saveLed()};
$("led-gpio").onchange=function(){ledGpio=parseInt(this.value,10);saveLed()};
$("led-order").onchange=function(){led.order=this.value;saveLed()};
$("led-hide-b").onclick=function(){
 if(!confirm("Hide the Status LED settings? This can only be undone on the Pi itself, by deleting led_hidden in /opt/dreampi-netswitch."))return;
 var x=new XMLHttpRequest();x.open("POST","/ledhide",true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=function(){$("led-section").style.display="none";ledHiddenFlag=true;updateGpioSection()};x.send()};
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
  if(!$("wifi-btn-sel").options.length)$("wifi-btn-sel").innerHTML=r.wifi_choices.map(function(c){
   return '<option value="'+c[0]+'">'+esc(c[1])+'</option>'}).join("");
  $("btn1-gpio").value=btn.button1_gpio;$("btn1-fn").value=btn.button1_function;
  $("btn2-gpio").value=btn.button2_gpio;$("btn2-fn").value=btn.button2_function;describeButtons();
  $("wifi-btn-sel").value=btn.wifi_button;
  updateGpioSection()};x.send()}
function saveButtons(){clearTimeout(btnTimer);btnTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/buttonconfig",true);x.setRequestHeader("Content-Type","application/json");
 x.onload=function(){if(x.status!=200)return;var el=$("gpio-saved");el.classList.add("show");
  setTimeout(function(){el.classList.remove("show")},1200);loadButtons()};x.send(JSON.stringify(btn))},250)}
$("btn1-gpio").onchange=function(){btn.button1_gpio=parseInt(this.value,10);saveButtons()};
$("btn1-fn").onchange=function(){btn.button1_function=this.value;describeButtons();saveButtons()};
$("btn2-gpio").onchange=function(){btn.button2_gpio=parseInt(this.value,10);saveButtons()};
$("btn2-fn").onchange=function(){btn.button2_function=this.value;describeButtons();saveButtons()};
$("wifi-btn-sel").onchange=function(){btn.wifi_button=this.value;saveButtons()};
$("show-debug").onclick=function(){debugOpen=!debugOpen;
 $("debug").style.display=debugOpen?"block":"none";
 this.classList.toggle("open",debugOpen);
 if(debugOpen){pollLog();var el=$("log");el.scrollTop=el.scrollHeight}};
setDebugMenu((function(){try{return localStorage.getItem("netswitch-debug")==="on"}catch(e){return false}})());
function cls(line){
 if(/modem: DTMF/.test(line))return"dtmf";
 if(/netswitch:|add-on:/.test(line))return"route";
 if(/web page:/.test(line))return"web";
 if(/underrun/.test(line))return"dim";
 if(/fail|error|Couldn't|Unable|No carrier|NO CARRIER/i.test(line))return"err";
 if(/modem/.test(line))return"modem";
 return"";
}
function pollLog(){
 if(!debugOpen||logBusy||(!debugOn&&logSize))return; logBusy=true;
 var x=new XMLHttpRequest();x.open("GET","/log?from="+logSize,true);
 x.onload=function(){logBusy=false;if(x.status!=200)return;var r=JSON.parse(x.responseText);
  var el=$("log");if(r.reset)el.innerHTML="";
  if(r.text){var html=r.text.split(/\r?\n/).filter(function(l){return l.length}).map(function(l){
    return '<div class="'+cls(l)+'">'+esc(l)+'</div>'}).join("");
   el.insertAdjacentHTML("beforeend",html);
   if($("follow").checked)el.scrollTop=el.scrollHeight;}
  logSize=r.size;};
 x.onerror=function(){logBusy=false};x.send();
}
function refresh(){var x=new XMLHttpRequest();x.open("GET","/api",true);
 x.onload=function(){if(x.status==200)render(JSON.parse(x.responseText))};x.send()}
Array.prototype.forEach.call(document.forms,function(f){if(f.id=="hang-f")return;f.onsubmit=function(e){e.preventDefault();
 var x=new XMLHttpRequest();x.open("POST",f.getAttribute("action"),true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=function(){refresh();pollLog()};x.send()}});
refresh(); setInterval(refresh,1000);
pollLog(); setInterval(pollLog,700);

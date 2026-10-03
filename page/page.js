
function $(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
// Hooks: how the optional modules (modules/*/page.js, appended to this script) take part. A module calls
// hook(name, fn); this page calls fire(name, arg) at the matching moment. fire() is true if a hook returned true.
//   api(d) every /api answer   settingsOpen / settingsClose   escape (true = handled)   buttons(r) button settings loaded
//   posted after a form post
var HOOKS={};
function hook(name,fn){(HOOKS[name]=HOOKS[name]||[]).push(fn)}
function fire(name,arg){var handled=false;(HOOKS[name]||[]).forEach(function(f){try{if(f(arg)===true)handled=true}catch(e){if(window.console)console.error(name,e)}});return handled}
// ===== The page kit (docs/modules.md, "The page kit"): what modules use to build their rows and pop-ups, so the look
// is decided here and in page.css only. =====
//   ui.row({title, sub, subHtml, control, below, id, cls})  one Settings row as HTML: title and subtitle on the left, the control
//                                                 (ui.btn / a checkbox / a select ...) on the right, `below` underneath
//   ui.btn(text, {attr: value, ...})              a small round button as HTML (attributes escaped)
//   ui.tag(text, {attr: value, ...})              a removable item (a number, say) with a x button, for a .tags list
//   ui.swatches(options, currentId, {attr: value})  a row of round colour choices as HTML ([{id, name, ui}] from the server)
//   ui.popup(el)                                  turns an element (inside a card or section) into a pop-up that opens under
//                                                 a button: p.toggle(button, event) / p.open(button) / p.close() / p.isOpen();
//                                                 set p.onclose to be told when it closes. Esc, a click elsewhere, opening
//                                                 another pop-up and closing Settings close it by themselves.
var ui={version:1,_pops:[]};   // keep in step with UI_KIT in netswitch_modules.py
ui.attrs=function(a){var s="";for(var k in a)if(a[k]!==undefined&&a[k]!==null)s+=" "+k+'="'+esc(a[k])+'"';return s};
ui.btn=function(text,a){a=a||{};var c="pill-s"+(a["class"]?" "+a["class"]:"");var b={};for(var k in a)b[k]=a[k];b["class"]=c;b.type=b.type||"button";
 return "<button"+ui.attrs(b)+">"+esc(text)+"</button>"};
ui.tag=function(text,a){var b={type:"button","aria-label":"Remove "+text};for(var k in a)b[k]=a[k];
 return '<span class="tag">'+esc(text)+"<button"+ui.attrs(b)+">&#10005;</button></span>"};
ui.row=function(o){o=o||{};
 return '<div class="srow'+(o.below!=null?" wrap":"")+(o.cls?" "+o.cls:"")+'"'+(o.id?' id="'+esc(o.id)+'"':"")+"><span>"+esc(o.title||"")+
  (o.subHtml!=null?'<span class="sub">'+o.subHtml+"</span>":o.sub!=null?'<span class="sub">'+esc(o.sub)+"</span>":"")+"</span>"+(o.control||"")+(o.below!=null?'<div class="below">'+o.below+"</div>":"")+"</div>"};
ui.swatches=function(options,current,a){
 return '<span class="swatches">'+options.map(function(o){var b={type:"button","class":"swatch"+(o.id===current?" sel":""),style:"--c:"+o.ui,"aria-label":o.name,"aria-pressed":o.id===current?"true":"false","data-id":o.id};
  for(var k in a)b[k]=a[k];return "<button"+ui.attrs(b)+"></button>"}).join("")+"</span>"};
ui.closePopups=function(except){ui._pops.forEach(function(p){if(p!==except)p.close()})};
ui.popup=function(el){
 var par=el.parentNode,p={el:el,anchor:null,onclose:null};
 el.classList.add("pop");el.setAttribute("role","dialog");
 if(window.getComputedStyle(par).position==="static")par.style.position="relative";   // the pop-up is placed inside it
 p.isOpen=function(){return el.classList.contains("open")};
 p.open=function(anchor){ui.closePopups(p);p.anchor=anchor;el.classList.add("open");
  var box=par.getBoundingClientRect(),r=anchor.getBoundingClientRect();
  el.style.left=Math.max(0,Math.min(r.right-box.left-el.offsetWidth,box.width-el.offsetWidth))+"px";
  el.style.top=(r.bottom-box.top+6)+"px"};
 p.close=function(){if(!p.isOpen())return;el.classList.remove("open");p.anchor=null;if(p.onclose)p.onclose()};
 p.toggle=function(anchor,e){if(e&&e.stopPropagation)e.stopPropagation();if(p.isOpen()&&p.anchor===anchor)p.close();else p.open(anchor)};
 el.addEventListener("click",function(e){e.stopPropagation()});
 ui._pops.push(p);return p};
document.addEventListener("click",function(){ui.closePopups()});
hook("escape",function(){if(ui._pops.some(function(p){return p.isOpen()})){ui.closePopups();return true}});
hook("settingsClose",function(){ui.closePopups()});
function ago(t,now){if(!t)return"";var s=Math.max(0,now-t);
 if(s<60)return"("+s+"s ago)";if(s<3600)return"("+Math.floor(s/60)+" min ago)";return"("+Math.floor(s/3600)+" h ago)"}
// The page is redrawn from /api every second: only touch the DOM when something actually changed (no flicker, less work on a slow phone)
function setText(el,t){t=String(t);if(el.textContent!==t)el.textContent=t}
function setHtml(el,h){if(el._html!==h){el._html=h;el.innerHTML=h}}
function setClass(el,c){if(el.className!==c)el.className=c}
function setStyle(el,prop,v){if(el.style[prop]!==v)el.style[prop]=v}
function dot(el,state){setClass(el,"dot "+(state||""))}
// Status dot preview of the LED effect: [keyframes, slow s, fast s, timing]
var DOT_FX={blink:["blink",1,.4,"steps(1)"]};   // solid has no animation; more effects come back here as the LED engine gets them
function lookDot(el,look){setClass(el,"dot");if(!look){setStyle(el,"background","#333");setStyle(el,"animation","none");return}
 var f=DOT_FX[look.effect];setStyle(el,"background",look.color);
 setStyle(el,"animation",f?f[0]+" "+(look.speed=="fast"?f[2]:f[1])+"s "+f[3]+" infinite":"none")}
var favNet="dcnow";
function render(d){
 pinNeeded=!!d.pin;
 // Hang up only while in a call (or while a hang up is still running)
 $("hang-row").style.display=(d.dreampi.state.indexOf("call")==0||(d.hangup&&d.hangup.busy))?"":"none";
 if(d.hangup){var hb=$("hang-b");
  if(d.hangup.busy){hb.disabled=true;hb.className="pill-s";
   hb.textContent=d.hangup.text?d.hangup.text.charAt(0).toUpperCase()+d.hangup.text.slice(1):"Hanging up..."}
  else if(hb.disabled){hb.disabled=false;hb.textContent="Hang up"}}
 applyColours(d.netcolours);
 setHtml($("warnings"),d.warnings.map(function(w){return '<div class="warnbox">'+esc(w)+'</div>'}).join(""));
 window.lastDreampiState=d.dreampi.state; lookDot($("d-dot"),d.dreampi.look); setText($("d-text"),d.dreampi.text);
 setText($("m-text"),d.modem.text); setText($("m-since"),ago(d.modem.since,d.now).replace(/[()]/g,""));
 dot($("i-dot"),d.internet.state); setText($("i-text"),d.internet.text);
 dot($("p-dot"),d.pi.state);
 setHtml($("p-text"),d.pi.line1?'<span class="nw">'+esc(d.pi.line1)+'</span><span class="sub blk">'+esc(d.pi.line2)+
  (d.pi.warn?'<br>'+esc(d.pi.warn):'')+'</span>':esc(d.pi.text||"..."));
 setClass($("net"),"now rows "+d.network+($("net").classList.contains("open")?" open":""));
 if(d.network!=favNet){favNet=d.network;$("fav").href="/static/favicon-"+d.network+".png";$("touch").href="/static/touch-"+d.network+".png"} setText($("net-name"),d.network=="dcnet"?"DCNET":"DCNow!");
 fire("api",d);
}
// Network colours: DCNow! and DCNET each have one colour, used by the whole page and the LEDs. The server builds the chosen ones
// into the page's CSS and /api reports them, so a change made on another device shows here without a reload.
var netColKey="";
function hexRgb(h){return parseInt(h.slice(1,3),16)+","+parseInt(h.slice(3,5),16)+","+parseInt(h.slice(5,7),16)}
function applyColours(c){if(!c)return;var key=JSON.stringify(c);if(key===netColKey)return;netColKey=key;
 var root=document.documentElement.style;
 ["dcnow","dcnet"].forEach(function(n){var x=c[n];if(!x)return;
  root.setProperty("--"+n,x.ui);root.setProperty("--"+n+"-l",x.ui_l);root.setProperty("--"+n+"-rgb",hexRgb(x.ui));root.setProperty("--"+n+"-l-rgb",hexRgb(x.ui_l))});
 if($("settings").classList.contains("open"))loadColours()}
var colourOpts=null;
function renderColours(cur){if(!colourOpts)return;
 $("colours-card").innerHTML=[["dcnow","DCNow!"],["dcnet","DCNET"]].map(function(n){
  return ui.row({title:n[1],control:ui.swatches(colourOpts,cur[n[0]],{"data-net":n[0]})})}).join("");
 Array.prototype.forEach.call($("colours-card").querySelectorAll(".swatch"),function(b){b.onclick=function(){
  xhrJson("POST","/netcolour",function(r){if(!r)return;renderColours(r.current);refresh();
   var el=$("colours-saved");el.classList.add("show");setTimeout(function(){el.classList.remove("show")},1200)},{network:b.dataset.net,colour:b.dataset.id})}})}
function loadColours(){xhrJson("GET","/colours",function(r){if(!r)return;colourOpts=r.options;renderColours(r.current)})}
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
 if(open){fire("settingsOpen");loadButtons();loadModules();loadAbout();loadColours()}}
// The PIN (when one is set with install.sh --pin) is asked for once per page load, before update / restart / Wi-Fi connect.
var pinNeeded=false,pinValue="";
function withPin(go){if(!pinNeeded||pinValue)return go();var p=prompt("Enter the PIN");if(p===null)return;pinValue=p;go()}
function xhrJson(method,url,cb,body){var x=new XMLHttpRequest();x.open(method,url,true);
 if(method=="POST"){x.setRequestHeader("X-Requested-With","netswitch");if(pinValue)x.setRequestHeader("X-Netswitch-Pin",pinValue);
  if(body!==undefined)x.setRequestHeader("Content-Type","application/json")}
 x.onload=function(){var r=null;try{r=JSON.parse(x.responseText)}catch(e){}
  if(x.status==401||x.status==429)pinValue="";   // asked again next time
  cb(x.status==200?r:null,x.status,r)};x.onerror=function(){cb(null,0,null)};x.send(body===undefined?undefined:JSON.stringify(body))}
// Modules menu: every installed module with a switch. Switching reloads the page, because a module's parts are built into it.
function loadModules(){xhrJson("GET","/modules",function(r){if(!r)return;
 $("mod-list").innerHTML=r.modules.map(function(m){
  return ui.row({title:m.title,
   subHtml:esc(m.description)+(m.note?'<br>'+esc(m.note):'')+(m.error?'<br><b class="modbad">Could not load: '+esc(m.error)+'</b>':''),
   control:'<input type="checkbox" class="cbox dcnow" data-module="'+esc(m.name)+'" aria-label="'+esc(m.title)+'"'+(m.enabled?' checked':'')+'>'})}).join("")||
  ui.row({title:"No modules installed."});
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

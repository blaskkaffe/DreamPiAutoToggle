
function $(id){return document.getElementById(id)}
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
// Hooks: how the optional modules (modules/*/page.js, appended to this script) take part. A module calls
// hook(name, fn); this page calls fire(name, arg) at the matching moment. fire() is true if a hook returned true.
//   api(d) every /api answer   settingsOpen / settingsClose   escape (true = handled)   buttons(r) button settings loaded
//   posted after a form post
var HOOKS={};
function hook(name,fn){(HOOKS[name]=HOOKS[name]||[]).push(fn)}
function fire(name,arg){var handled=false;(HOOKS[name]||[]).forEach(function(f){try{if(f(arg)===true)handled=true}catch(e){if(window.console)console.error(name,e)}});return handled}
// ===== The page kit (docs/modules.md, "The page kit"): the look is decided here and in page.css only. A module draws what it shows
// with the standard widgets of its layout.json (page/widgets.js); this is what is left for a module's own page.js:
//   ui.popup(el)   turns an element (inside a card) into a pop-up that opens under a button: p.toggle(button, event) / p.open(button) /
//                  p.close() / p.isOpen(); set p.onclose to be told when it closes. It moves into its card the first time it opens.
//                  Esc, a click elsewhere, opening another pop-up and closing Settings close it by themselves.
// =====
var ui={version:2,_pops:[]};   // keep in step with UI_KIT in netswitch_modules.py
ui.closePopups=function(except){ui._pops.forEach(function(p){if(p!==except)p.close()})};
ui.popup=function(el){
 var p={el:el,anchor:null,onclose:null};
 el.classList.add("pop");el.setAttribute("role","dialog");
 // the pop-up is placed inside the card it belongs to (the first time it opens it moves there, so it can use the card's whole width)
 function host(){var c=el.closest&&el.closest(".card");if(c&&el.parentNode!==c)c.appendChild(el);
  var par=el.parentNode;if(window.getComputedStyle(par).position==="static")par.style.position="relative";return par}
 p.isOpen=function(){return el.classList.contains("open")};
 p.open=function(anchor){ui.closePopups(p);p.anchor=anchor;var par=host();el.classList.add("open");
  var box=par.getBoundingClientRect(),r=anchor.getBoundingClientRect();
  var cs=window.getComputedStyle(par),padL=parseFloat(cs.paddingLeft)||0,padR=parseFloat(cs.paddingRight)||0;
  el.style.left=padL+"px";el.style.width=(box.width-padL-padR)+"px";     // every pop-up spans the card between its left and right padding
  el.style.top=(r.bottom-box.top+6)+"px";fit();
  if(window.ResizeObserver&&!p._ro){p._ro=new ResizeObserver(function(){if(p.isOpen())fit()});p._ro.observe(el)}};
 // A pop-up hangs below its row and may be taller than the card. In the multi-column settings view a box that sticks out of its
 // card is continued in the next column, so the card grows to hold the pop-up while it is open.
 function fit(){var par=el.parentNode;if(!par||!p.isOpen())return;par.style.minHeight="";
  var need=el.offsetTop+el.offsetHeight+8;if(need>par.offsetHeight)par.style.minHeight=need+"px"}
 p.close=function(){if(!p.isOpen())return;el.classList.remove("open");p.anchor=null;if(el.parentNode)el.parentNode.style.minHeight="";if(p.onclose)p.onclose()};
 p.toggle=function(anchor,e){if(e&&e.stopPropagation)e.stopPropagation();if(p.isOpen()&&p.anchor===anchor)p.close();else p.open(anchor)};
 el.addEventListener("click",function(e){e.stopPropagation()});
 ui._pops.push(p);return p};
document.addEventListener("click",function(){ui.closePopups()});
hook("escape",function(){if(ui._pops.some(function(p){return p.isOpen()})){ui.closePopups();return true}});
hook("settingsClose",function(){ui.closePopups()});
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
function render(d){
 pinNeeded=!!d.pin;
 for(var k in d)S[k]=d[k];       // S keeps the data sources' answers and the page's own state between /api answers
 NOTICES=d.notices||[];
 setHtml($("warnings"),d.warnings.map(function(w){return '<div class="warnbox">'+esc(w)+'</div>'}).join("")+
  NOTICES.map(function(n,i){return '<div class="notebox" role="status"><span>'+esc(n.text)+'</span>'+(n.post?'<button type="button" class="nx" data-n="'+i+'" title="Dismiss" aria-label="Dismiss">&#10005;</button>':'')+'</div>'}).join(""));
 window.lastDreampiState=d.dreampi&&d.dreampi.state;
 engineUpdate();
 fire("api",d);
}
// notices (/api "notices"): banners a module shows above the boxes; the cross POSTs {"id"} to the notice's "post" path
var NOTICES=[];
$("warnings").addEventListener("click",function(e){var b=e.target.closest&&e.target.closest(".nx");if(!b)return;var n=NOTICES[+b.getAttribute("data-n")];
 if(n&&n.post){b.disabled=true;xhrJson("POST",n.post,function(){refresh()},{id:n.id})}});
function showSettings(open){$("settings").classList.toggle("open",open);
 if(!open)fire("settingsClose");
 document.body.classList.toggle("settings-open",open);
 if(open)fire("settingsOpen")}
// The PIN (when one is set with install.sh --pin) is asked for once per page load, before update / restart / Wi-Fi connect.
var pinNeeded=false,pinValue="";
function withPin(go){if(!pinNeeded||pinValue)return go();var p=prompt("Enter the PIN");if(p===null)return;pinValue=p;go()}
function xhrJson(method,url,cb,body){var x=new XMLHttpRequest();x.open(method,url,true);
 if(method=="POST"){x.setRequestHeader("X-Requested-With","netswitch");if(pinValue)x.setRequestHeader("X-Netswitch-Pin",pinValue);
  if(body!==undefined)x.setRequestHeader("Content-Type","application/json")}
 x.onload=function(){var r=null;try{r=JSON.parse(x.responseText)}catch(e){}
  if(x.status==401||x.status==429)pinValue="";   // asked again next time
  cb(x.status==200?r:null,x.status,r)};x.onerror=function(){cb(null,0,null)};x.send(body===undefined?undefined:JSON.stringify(body))}
$("cog").onclick=function(){showSettings(true)};
$("close-settings").onclick=function(){showSettings(false)};
document.addEventListener("keydown",function(e){if(e.key=="Escape"){if(!fire("escape"))showSettings(false)}});
function refresh(){var x=new XMLHttpRequest();x.open("GET","/api",true);
 x.onload=function(){if(x.status==200)render(JSON.parse(x.responseText))};x.send()}

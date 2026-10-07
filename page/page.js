
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
  var box=par.getBoundingClientRect(),r=anchor.getBoundingClientRect(),f=par.offsetWidth?box.width/par.offsetWidth:1;   // f: how much bigger than its own pixels the card is drawn (Scale content)
  var cs=window.getComputedStyle(par),padL=parseFloat(cs.paddingLeft)||0,padR=parseFloat(cs.paddingRight)||0;
  el.style.left=padL+"px";el.style.width=(box.width/f-padL-padR)+"px";     // every pop-up spans the card between its left and right padding
  el.style.top=((r.bottom-box.top)/f+6)+"px";fit();
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
// Round icon buttons that are on or off: a bell (remind me) and a star (favourite). ui.iconButtonHtml(kind, on, what, attrs) is the markup
// (a module that builds its rows as HTML puts attrs, such as a data-id, on the button); ui.iconButton(kind, on, what) the element.
// The look is .ibtn in page.css; the state is .on and aria-pressed; what is the name of the thing it is about (a screen reader's label).
ui.icons={bell:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22a2.5 2.5 0 0 0 2.4-2h-4.8A2.5 2.5 0 0 0 12 22zm7-6V11a7 7 0 0 0-5.5-6.8V3a1.5 1.5 0 0 0-3 0v1.2A7 7 0 0 0 5 11v5l-2 2v1h18v-1z"/></svg>',
 star:'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2l3.1 6.6 7.2.9-5.3 5 1.4 7.1L12 17.9 5.6 21.6 7 14.5 1.7 9.5l7.2-.9z"/></svg>'};
ui.iconTexts={bell:["Reminder on: tap to clear","Remind me","Clear the reminder for ","Remind me of "],star:["Favorite: tap to remove","Add to favorites","Remove from favorites: ","Add to favorites: "]};
ui.iconButtonHtml=function(kind,on,what,attrs){var t=ui.iconTexts[kind];
 return '<button type="button" class="ibtn '+kind+(on?' on':'')+'" '+(attrs||'')+' aria-pressed="'+(on?'true':'false')+'" title="'+(on?t[0]:t[1])+'" aria-label="'+(on?t[2]:t[3])+esc(what||"")+'">'+ui.icons[kind]+'</button>'};
ui.iconButton=function(kind,on,what){var d=document.createElement("div");d.innerHTML=ui.iconButtonHtml(kind,on,what);return d.firstChild};
hook("escape",function(){if(ui._pops.some(function(p){return p.isOpen()})){ui.closePopups();return true}});
hook("settingsClose",function(){ui.closePopups()});
// The page is redrawn from /api every second: only touch the DOM when something actually changed (no flicker, less work on a slow phone)
function setText(el,t){t=String(t);if(el.textContent!==t)el.textContent=t}
function setHtml(el,h){if(el._html!==h){el._html=h;el.innerHTML=h}}
function setClass(el,c){if(el.className!==c)el.className=c}
function setStyle(el,prop,v){if(el.style[prop]!==v)el.style[prop]=v}
function dot(el,state){setClass(el,"dot "+(state||""))}
function render(d){
 pinNeeded=!!d.pin;
 for(var k in d)S[k]=d[k];       // S keeps the data sources' answers and the page's own state between /api answers
 NOTICES=d.notices||[];
 setHtml($("warnings"),d.warnings.map(function(w){return '<div class="warnbox">'+esc(w)+'</div>'}).join("")+
  NOTICES.map(function(n,i){return '<div class="notebox" role="status"><span>'+esc(n.text)+'</span>'+(n.post?'<button type="button" class="nx" data-n="'+i+'" title="Dismiss" aria-label="Dismiss">&#10005;</button>':'')+'</div>'}).join(""));
 engineUpdate();
 fire("api",d);
}
// notices (/api "notices"): banners a module shows above the boxes; the cross POSTs {"id"} to the notice's "post" path
var NOTICES=[];
$("warnings").addEventListener("click",function(e){var b=e.target.closest&&e.target.closest(".nx");if(!b)return;var n=NOTICES[+b.getAttribute("data-n")];
 if(n&&n.post){b.disabled=true;xhrJson("POST",n.post,function(){refresh()},{id:n.id})}});
function showSettings(open){$("settings").classList.toggle("open",open);
 if(!open){fire("settingsClose");if(S.settings_pin&&S.settings_pin.on)pinValue=""}       // a locked Settings asks again next time
 document.body.classList.toggle("settings-open",open);
 if(!open&&SCR.noscroll)window.scrollTo(0,0);
 if(open){$("settings").classList.add("settling");fire("settingsOpen");whenLoaded(function(){layoutColumns();$("settings").classList.remove("settling")},900)}}
// Settings is shown once what its boxes ask for has arrived (every GET in flight), or after limit ms, so the rows do not pop in one by one
// and the boxes do not move while they fill
var inflight=0;
function whenLoaded(done,limit){var t0=Date.now();(function check(){if((inflight===0&&Date.now()-t0>=40)||Date.now()-t0>limit)done();else setTimeout(check,30)})()}
// The settings boxes are placed in columns once (as many ~420px columns as fit, filled top to bottom in order, each as tall as the others)
// and stay where they are put when their content changes; only a change of the number of columns places them again.
var colN=0,colKey="";
function layoutColumns(force){var cols=$("set-boxes"),GAP=SGAP;applyScreen(true);var W=cols.clientWidth;if(!W)return;
 var n=colsFor(SCR.set_cols,W),z=scrZoom(n,W),key=n+"/"+z;if(key===colKey&&!force)return;colKey=key;
 var boxes=Array.prototype.slice.call(cols.querySelectorAll(".sec[data-box]")),i,w=(W-GAP*(n-1))/n,hs=[],total=0;
 cols.style.setProperty("--z",z);
 boxes.forEach(function(b){cols.appendChild(b)});
 Array.prototype.slice.call(cols.querySelectorAll(":scope > .col")).forEach(function(c){c.parentNode.removeChild(c)});
 cols.style.display="block";                                    // measured one under the other, each as wide as a column will be
 boxes.forEach(function(b){b.style.width=(w/z)+"px"});
 boxes.forEach(function(b){var h=b.offsetHeight?b.getBoundingClientRect().height+18:0;hs.push(h);total+=h});
 boxes.forEach(function(b){b.style.width=""});cols.style.display="";
 var target=total/n,colEls=[],col=0,used=0;
 for(i=0;i<n;i++){var c=document.createElement("div");c.className="col";cols.appendChild(c);colEls.push(c)}
 boxes.forEach(function(b,k){if(col<n-1&&used>0&&used+hs[k]/2>target*(col+1)){col++}used+=hs[k];colEls[col].appendChild(b)});
 colN=n}
window.addEventListener("resize",function(){applyScreen();if($("settings").classList.contains("open"))layoutColumns()});
// ---- the screen layout (Settings > Appearance; S.screen from /api): how many columns the dashboard and Settings use on a wide screen and
// whether they stretch. A column is about COLW px wide; there are as many as fit, up to the setting. Stretch: the columns share the whole width
// (the boxes are wider). Scale content: a stretched box is drawn bigger (CSS zoom) in step with its width, so it is taller too.
var SCR={dash_cols:1,set_cols:4,stretch:false,scale:false,drag:false,noscroll:false},COLW=428,SGAP=20,scrKey="";
function colsFor(max,W){return Math.max(1,Math.min(max,Math.floor((W+SGAP)/(COLW+SGAP))))}
function scrZoom(n,W){return SCR.stretch&&SCR.scale?Math.max(1,((W-SGAP*(n-1))/n)/COLW):1}
// The dashboard's boxes in dn columns: each box goes to the column that is shortest so far, in the order of the layout (so the first boxes are at
// the top); they stay where they are put when their content changes. Placed again when the number of columns or the set of shown boxes changes.
var dashKey="";
function dashTiles(){var kids=Array.prototype.slice.call($("dash").querySelectorAll(".dbox"));
 kids.forEach(function(b,i){if(b._ord===undefined)b._ord=i});
 return kids.sort(function(a,b){return a._ord-b._ord})}
function layoutDash(dn){var dash=$("dash"),kids=dashTiles();
 if(!kids.length)return;
 var key=dn+"/"+kids.map(function(b){return b.offsetHeight?1:0}).join("");if(key===dashKey)return;dashKey=key;
 Array.prototype.slice.call(dash.querySelectorAll(":scope > .dcol")).forEach(function(c){c.parentNode.removeChild(c)});
 kids.forEach(function(b){dash.appendChild(b)});
 if(dn<2)return;
 var cols=[],i,k=0;for(i=0;i<dn;i++){var c=document.createElement("div");c.className="dcol";dash.appendChild(c);cols.push(c)}
 kids.forEach(function(b){if(b.offsetHeight)cols[k++%dn].appendChild(b);else cols[0].appendChild(b)})}      // the shown tiles go round the columns in their order, so a place in a column means a place in the order
// ---- rearranging the main screen (Settings > Appearance): a handle on each tile, drag it before or after another; the modules follow the
// tiles' order (POST /modules/dashboard-order). While Settings is locked with the PIN this needs the PIN to have been given.
function tilesMovable(){return !!SCR.drag&&!(S.settings_pin&&S.settings_pin.on&&!pinValue)}
function shownTiles(){return dashTiles().filter(function(b){return b.offsetHeight||b===dragTile})}
var dragTile=null,dropBar=null;
function tileTitle(b){var t=b.querySelector("b,h2,.nlabel");return t?t.textContent.trim():b.getAttribute("data-box")}
function applyGrips(){var on=tilesMovable();$("dash").classList.toggle("movable",on);
 dashTiles().forEach(function(b){if(!b._grip){var g=h("button",{type:"button","class":"tilegrip keep",title:"Drag to move this tile (or use the arrow keys)",html:"&#8942;&#8942;"});b._grip=g;b.insertBefore(g,b.firstChild);gripEvents(b,g)}
  sh(b._grip,on);b._grip.setAttribute("aria-label","Move the "+tileTitle(b)+" tile: drag, or use the arrow keys")})}
// where a tile dropped at (x,y) goes: {tile, after} = next to the tile under or nearest to the point
function dropSpot(x,y,moving){var best=null,bd=1e9;
 shownTiles().forEach(function(t){if(t===moving)return;var r=t.getBoundingClientRect(),dx=x<r.left?r.left-x:(x>r.right?x-r.right:0),dy=y<r.top?r.top-y:(y>r.bottom?y-r.bottom:0),d=dx*dx+dy*dy;
  if(d<bd){bd=d;best={tile:t,after:y>r.top+r.height/2,r:r}}});return best}
function moveTile(tile,spot){var seq=shownTiles().filter(function(t){return t!==tile}),at=seq.indexOf(spot.tile)+(spot.after?1:0);seq.splice(at,0,tile);commitTiles(seq)}
function commitTiles(seq){var ords=shownTiles().map(function(b){return b._ord}).sort(function(a,b){return a-b}),moved=false;
 seq.forEach(function(b,i){if(b._ord!==ords[i]){moved=true;b._ord=ords[i]}});if(!moved)return;
 dashKey="";layoutDash(colsFor(SCR.dash_cols,document.documentElement.clientWidth-(SCR.stretch&&document.documentElement.clientWidth>=900?48:32)));
 fire("tiles-moved",seq);
 var names=[],boxes={};(LAY.dashboard||[]).forEach(function(b){boxes[b.id]=b});
 seq.forEach(function(b){((boxes[b.getAttribute("data-box")]||{}).mods||[]).forEach(function(m){if(names.indexOf(m)<0)names.push(m)})});
 post("/modules/dashboard-order",{order:names},function(r){if(!r){alert("The new order was not saved.");location.reload()}})}
function gripEvents(tile,grip){
 grip.addEventListener("click",function(e){e.stopPropagation()});
 grip.addEventListener("keydown",function(e){var back=e.key==="ArrowUp"||e.key==="ArrowLeft",fwd=e.key==="ArrowDown"||e.key==="ArrowRight";if(!back&&!fwd)return;e.preventDefault();
  var seq=shownTiles(),i=seq.indexOf(tile),j=i+(back?-1:1);if(j<0||j>=seq.length)return;seq.splice(i,1);seq.splice(j,0,tile);commitTiles(seq);grip.focus()});
 grip.addEventListener("pointerdown",function(e){if(e.pointerType==="mouse"&&e.button!==0)return;e.preventDefault();
  var pid=e.pointerId,spot=null;dragTile=tile;try{grip.setPointerCapture(pid)}catch(x){}
  tile.classList.add("tile-drag");document.body.classList.add("dragging");
  if(!dropBar){dropBar=h("div",{"class":"dropbar"});document.body.appendChild(dropBar)}
  function show(ev){spot=dropSpot(ev.clientX,ev.clientY,tile);if(!spot){dropBar.style.display="none";return}
   dropBar.style.display="block";dropBar.style.left=spot.r.left+"px";dropBar.style.width=spot.r.width+"px";dropBar.style.top=((spot.after?spot.r.bottom:spot.r.top)-3)+"px"}
  function move(ev){if(ev.pointerId===pid)show(ev)}
  function end(cancel){grip.removeEventListener("pointermove",move);grip.removeEventListener("pointerup",up);grip.removeEventListener("pointercancel",lost);document.removeEventListener("keydown",esc,true);
   try{grip.releasePointerCapture(pid)}catch(x){}
   tile.classList.remove("tile-drag");document.body.classList.remove("dragging");dropBar.style.display="none";dragTile=null;
   if(!cancel&&spot)moveTile(tile,spot)}
  function up(ev){if(ev.pointerId===pid)end(false)}
  function lost(ev){if(ev.pointerId===pid)end(true)}
  function esc(ev){if(ev.key==="Escape"){ev.stopPropagation();end(true)}}
  grip.addEventListener("pointermove",move);grip.addEventListener("pointerup",up);grip.addEventListener("pointercancel",lost);document.addEventListener("keydown",esc,true);show(e)})}
function applyScreen(fromSettings){var s=S.screen;if(s)SCR=s;
 var vw=document.documentElement.clientWidth,pad=SCR.stretch&&vw>=900?24:16,W=vw-2*pad,dn=colsFor(SCR.dash_cols,W),dz=scrZoom(dn,W),
  sn=colsFor(SCR.set_cols,W),key=[dn,dz,sn,pad,SCR.stretch,SCR.set_cols].join("/");
 var dash=$("dash"),b=document.body,inn=document.querySelector("#settings .in");
 document.documentElement.classList.toggle("noscroll",!!SCR.noscroll);
 b.style.maxWidth=SCR.stretch?"none":(dn*COLW+(dn-1)*SGAP+2*pad)+"px";b.style.paddingLeft=b.style.paddingRight=pad+"px";
 dash.style.setProperty("--z",dz);dash.classList.toggle("multi",dn>1);layoutDash(dn);applyGrips();
 if(inn){inn.style.maxWidth=SCR.stretch?"none":(sn*COLW+(sn-1)*SGAP+2*pad)+"px";inn.style.paddingLeft=inn.style.paddingRight=pad+"px"}
 if(key!==scrKey){scrKey=key;if(!fromSettings&&$("settings").classList.contains("open"))layoutColumns(true)}}
// The PIN (when one is set with install.sh --pin) is asked for once per page load, before update / restart / Wi-Fi connect.
var pinNeeded=false,pinValue="";
function withPin(go){if(!pinNeeded||pinValue)return go();var p=prompt("Enter the PIN");if(p===null)return;pinValue=p;go()}
function xhrJson(method,url,cb,body){var x=new XMLHttpRequest(),counted=method!=="POST";if(counted)inflight++;x.open(method,url,true);
 if(method=="POST"){x.setRequestHeader("X-Requested-With","netswitch");if(pinValue)x.setRequestHeader("X-Netswitch-Pin",pinValue);
  if(body!==undefined)x.setRequestHeader("Content-Type","application/json")}
 x.onload=function(){if(counted)inflight--;var r=null;try{r=JSON.parse(x.responseText)}catch(e){}
  if(x.status==401||x.status==429)pinValue="";   // asked again next time
  cb(x.status==200?r:null,x.status,r)};x.onerror=function(){if(counted)inflight--;cb(null,0,null)};x.send(body===undefined?undefined:JSON.stringify(body))}
// Settings locked with the PIN (Appearance > Ask for the PIN): the cog asks for it first; the server checks it (and counts wrong tries)
function unlockThen(go){if(!(S.settings_pin&&S.settings_pin.on)||pinValue)return go();
 var p=prompt("Enter the PIN to open Settings");if(p===null)return;pinValue=p;
 xhrJson("POST","/pin/check",function(r,st,b){if(r)return go();pinValue="";alert(b&&b.message?b.message:"Wrong PIN")},{})}
$("cog").onclick=function(){unlockThen(function(){showSettings(true)})};
$("close-settings").onclick=function(){showSettings(false)};
document.addEventListener("keydown",function(e){if(e.key=="Escape"){if(!fire("escape"))showSettings(false)}});
function refresh(){var x=new XMLHttpRequest();x.open("GET","/api",true);
 x.onload=function(){if(x.status==200)render(JSON.parse(x.responseText));bootDone("api")};x.onerror=function(){bootDone("api")};x.send()}
// The first draw waits for /api and for the data sources that have no kept answer from an earlier visit (at most BOOT_LIMIT ms), then every
// box is shown at once: nothing pops in one box after the other
var BOOT_LIMIT=1500,bootPending={api:1};
function bootDone(k){if(!(k in bootPending))return;delete bootPending[k];for(var x in bootPending)return;document.body.classList.remove("booting")}
setTimeout(function(){bootPending={};document.body.classList.remove("booting")},BOOT_LIMIT);

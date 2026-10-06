// ===== The layout engine and the standard widgets. A module's layout.json (docs/modules.md, "Layout") says which boxes it
// fills and with which widgets; this file draws them. Nothing in here knows about a particular module. =====
//   S            the page's state: the /api answer plus one entry per data source a module asked for (S.players ...)
//   "@a.b"       in a layout a string that starts with @ is read from S (live: the widget follows it); anything else is literal
//   custom(name, fn)  a module's page.js registers a custom widget; fn(host, ctx) fills the empty host element
var S={}, LAY=window.LAYOUT||{modules:[],dashboard:[],settings:[],backgrounds:[],data:{},primary:{},colours:{},palette:[]};
var UPD=[], CUSTOM={}, W={}, AFTER=[];
function custom(name,fn){CUSTOM[name]=fn}
function getPath(o,p){var parts=String(p).split("."),i;for(i=0;i<parts.length;i++){if(o==null)return undefined;o=o[parts[i]]}return o}
function isBind(v){return typeof v==="string"&&v.charAt(0)==="@"}
function val(v){return isBind(v)?getPath(S,v.slice(1)):v}
// bind(v, apply): apply(value) now, and again whenever S is refreshed and the value is a binding (apply decides if anything changed)
function bind(v,apply){if(v===undefined)return;apply(val(v));if(isBind(v))UPD.push(function(){apply(val(v))})}
function h(tag,attrs,kids){var el=document.createElement(tag),k;
 for(k in (attrs||{})){var v=attrs[k];if(v===undefined||v===null)continue;
  if(k==="class")el.className=v;else if(k==="text")el.textContent=v;else if(k==="html")el.innerHTML=v;
  else if(k.slice(0,2)==="on")el[k]=v;else el.setAttribute(k,v)}
 (kids||[]).forEach(function(c){if(c)el.appendChild(c)});return el}
function lines(t){return esc(t==null?"":t).replace(/\n/g,"<br>")}
function setLines(el,t){setHtml(el,lines(t))}
function sh(el,show){setStyle(el,"display",show?"":"none")}
// A colour reference: a palette id ("orange"), one of the module's own colour keys ("checkin") or "module.key" of another module
function colourId(ref,mod){if(!ref)return"";var c=S.colours||LAY.colours||{};
 if(ref.indexOf(".")>0){var p=ref.split(".");return (c[p[0]]||{})[p[1]]||""}
 return (c[mod]||{})[ref]||ref}
// Whether the background of a colour is coloured (the default) or neutral: the "Coloured background" box next to a colour pick
function tintOf(ref,mod){if(!ref)return true;var p=ref.indexOf(".")>0?ref.split("."):[mod,ref],t=(S.tints||LAY.tints||{})[p[0]]||{};return t[p[1]]!==false}
// An element with its own colour (a button of the module's colour key): it follows S.colours live and is not repainted with the
// module's primary colour, so the buttons keep the colours chosen in Settings.
function colourClass(el,ref,mod){el.setAttribute("data-own-colour","1");
 function apply(){var r=val(ref),id=colourId(r,mod),old=el._cc;el.classList.toggle("plain",!tintOf(r,mod));if(old===id)return;
  if(old)el.classList.remove("c-"+old);if(id)el.classList.add("c-"+id);el._cc=id}
 apply();UPD.push(apply)}
// ---- talking to the server
function post(url,body,done){xhrJson("POST",url,function(r,st,b){if(done)done(r,st,b)},body)}
// after a button's POST: "reload" the page, "wait" until the Pi is back (a reboot), or just look at the new state
function afterPost(s,r,el){
 if(r&&r.started===false){alert(r.message||"That did not start");return}
 if(s.then==="reload"){try{sessionStorage.setItem("netswitch-reopen",s.reopen?"1":"")}catch(e){}location.reload();return}
 if(s.then==="wait"){if(el){el.disabled=true;setText(el,"Restarting...")}waitForPi();return}
 refresh();if(s.reload)reloadData(s.reload);fire("posted")}   // only /api is asked for at once: a data source is read again only when the button says so ("reload": its name)
function reloadInSettings(){try{sessionStorage.setItem("netswitch-reopen","1")}catch(e){}location.reload()}   // modules come and go: the page is built again, Settings stays open
function waitForPi(){var down=false,tries=0;
 (function poll(){tries++;var x=new XMLHttpRequest();x.open("GET","/ping?"+Date.now(),true);x.timeout=3000;
  x.onload=function(){if(down||tries>60)location.reload();else setTimeout(poll,2000)};
  x.onerror=x.ontimeout=function(){down=true;setTimeout(poll,2000)};x.send()})()}
// ---- the engine
function build(s,ctx){var f=W[s.type];if(!f)return h("div");var el=f(s,ctx);
 if(s.mod)el.setAttribute("data-mod",s.mod);
 if(s.show!==undefined)bind(s.show,function(v){sh(el,!!v)});
 if(s.hide!==undefined)bind(s.hide,function(v){sh(el,!v)});
 return el}
function buildAll(list,ctx){return(list||[]).map(function(w){return build(w,ctx)})}
function box(section,b){var ctx={mod:b.mods[0],box:b.id,saved:function(){}},items=b.items;
 if(section==="settings"){
  var saved=h("span",{"class":"saved",text:"Saved ✓"}),
   tt=h("span"),head=b.title?h("h2",{},[tt,document.createTextNode(" "),saved]):null,
   card=h("div",{"class":"card"}),sec=h("section",{"class":"sec","data-box":b.id,"data-mod":b.mods[0]},[head,card]);
  bind(b.title,function(t){setText(tt,t==null?"":t)});
  ctx.saved=function(){saved.classList.add("show");setTimeout(function(){saved.classList.remove("show")},1200)};
  buildAll(items,ctx).forEach(function(el){card.appendChild(el)});return sec}
 var d=h("div",{"class":"dbox","data-box":b.id,"data-mod":b.mods[0]});
 if(b.title){var dt=h("h2");bind(b.title,function(t){setText(dt,t==null?"":t)});d.appendChild(dt)}
 buildAll(items,ctx).forEach(function(el){d.appendChild(el)});return d}
function renderLayout(){
 var dash=$("dash"),cols=$("set-boxes");
 (LAY.dashboard||[]).forEach(function(b){dash.appendChild(box("dashboard",b))});
 (LAY.settings||[]).forEach(function(b){cols.appendChild(box("settings",b))});
 buildPicker(cols);
 AFTER.forEach(function(f){f()});AFTER=[]}
function engineUpdate(){UPD.forEach(function(f){try{f()}catch(e){if(window.console)console.error(e)}});applyTheme();applyHighlight();hideEmptyBoxes()}
// ---- highlight (/api "highlight": {box id: why}): those dashboard boxes get the class "hl" (page.css draws it) and the reason as a
// tooltip; the look is global (/api theme.highlight: "rainbow" or a palette id)
var hlKey="";
function applyHighlight(){var hl=S.highlight||{},st=(S.theme&&S.theme.highlight)||"rainbow",key=st+JSON.stringify(hl);if(key===hlKey)return;hlKey=key;
 document.body.classList.toggle("hl-rainbow",st==="rainbow");
 document.body.style.setProperty("--hl-rgb",st==="rainbow"?"255,255,255":"var(--c-"+st+"-rgb)");
 Array.prototype.forEach.call(document.querySelectorAll("#dash [data-box]"),function(b){var why=hl[b.getAttribute("data-box")];
  b.classList.toggle("hl",!!why);if(why)b.setAttribute("title",String(why));else b.removeAttribute("title")})}
// a box whose widgets are all hidden (the LED settings while the LED count is 0) is hidden too
function hideEmptyBoxes(){var bs=document.querySelectorAll("[data-box]"),i,j;
 for(i=0;i<bs.length;i++){var b=bs[i],host=b.querySelector(":scope > .card")||b,any=false;
  for(j=0;j<host.children.length;j++){var c=host.children[j];if(c.tagName!=="H2"&&c.style.display!=="none"){any=true;break}}
  sh(b,any)}}
// ---- theme: every box and widget takes the primary colour its module gave (a palette id, set in module.json or while running
// in /api primary); the top module in the picker that has one also sets the page's own. A module below with another one
// only uses it for itself.
var themeKey="";
function applyTheme(){var p={},pk={},k;for(k in (LAY.primary||{}))p[k]=LAY.primary[k];for(k in (S.primary||{}))p[k]=S.primary[k];
 for(k in (LAY.primary_key||{}))pk[k]=LAY.primary_key[k];for(k in (S.primary_key||{}))pk[k]=S.primary_key[k];
 var key=JSON.stringify([p,pk,S.tints||LAY.tints||{},""]);if(key===themeKey)return;themeKey=key;
 var els=document.querySelectorAll("[data-mod]"),i,root="";
 for(i=0;i<(LAY.modules||[]).length&&!root;i++)root=p[LAY.modules[i]]||"";
 function paint(el,id){var old=el._pc;if(old===id)return;if(old)el.classList.remove("c-"+old);if(id)el.classList.add("c-"+id);el._pc=id}
 paint(document.body,root);
 for(i=0;i<els.length;i++)if(!els[i].hasAttribute("data-own-colour")){var m=els[i].getAttribute("data-mod");paint(els[i],p[m]||"");
  els[i].classList.toggle("plain",!!pk[m]&&!tintOf(m+"."+pk[m],m))}}   // a neutral background where the user switched the colour's background off
// ---- data sources a module asked for in its layout ("data": {"players": {"url": "/players", "every": 60}}): fetched into S.<name>
// every N seconds while the page is on screen (with "when": "settings", only while Settings is open); "retry_if": "busy" asks again
// after "retry" seconds while that field of the answer is true, and after a failed request
var DATA={};
function reloadData(name){for(var ns in DATA)if(!name||ns===name)DATA[ns]()}
// The last answer of every data source is kept in this browser and shown at once when the page opens again (with "busy": true until the
// new answer is there), so a page never starts with empty lists: what it knew stays until something newer replaces it.
function restoreData(){var ns;for(ns in (LAY.data||{})){try{var r=JSON.parse(localStorage.getItem("netswitch-data-"+ns));if(r&&typeof r==="object"){r.busy=true;S[ns]=r}}catch(e){}
 if(!S[ns]&&(LAY.data[ns].when!=="settings"))bootPending["data-"+ns]=1}}      // no kept answer: the first draw waits for it (page.js bootDone)
function keepData(ns,r){try{localStorage.setItem("netswitch-data-"+ns,JSON.stringify(r))}catch(e){}}
function startData(){var ns;for(ns in (LAY.data||{}))(function(ns,spec){
 var timer=null,seq=0,every=(spec.every||60)*1000,retry=(spec.retry||2)*1000,onlyInSettings=spec.when==="settings";
 function wanted(){return !document.hidden&&(!onlyInSettings||$("settings").classList.contains("open"))}
 function load(){clearTimeout(timer);if(!wanted())return;var mine=++seq;
  xhrJson("GET",spec.url,function(r){var again=every;
   if(mine!==seq)return;                      // a newer question was asked meanwhile: its answer counts, this older one must not overwrite it
   if(r){S[ns]=r;keepData(ns,r);engineUpdate();if(spec.retry_if&&getPath(r,spec.retry_if))again=retry}else again=retry;
   bootDone("data-"+ns);timer=setTimeout(load,again)})}
 DATA[ns]=load;
 document.addEventListener("visibilitychange",function(){if(!document.hidden)load()});
 if(onlyInSettings){hook("settingsOpen",load);hook("settingsClose",function(){clearTimeout(timer)})}
 load()})(ns,LAY.data[ns])}
// ---- text, rows, buttons, links
// "style": "log" = a few lines of small monospace text that never wrap (each is cut with an ellipsis); "center": true = centred
W.text=function(s){var el=h("div",{"class":"wtext"+(s.muted?" sub":"")+(s.center?" ctr":"")+(s.style==="log"?" log":"")+(s.cls?" "+s.cls:"")});bind(s.text,function(t){setLines(el,t)});return el};
W.row=function(s,ctx){var title=h("span"),sub=h("span",{"class":"sub"}),left=h("span",{},[title,sub]),
 el=h("div",{"class":"srow"+(s.below?" wrap":"")},[left]);
 bind(s.title,function(t){setText(title,t==null?"":t)});bind(s.sub,function(t){setLines(sub,t);sh(sub,!!t)});
 if(s.control)el.appendChild(build(Object.assign({mod:s.mod},s.control),ctx));
 if(s.below)el.appendChild(h("div",{"class":"below"},buildAll(s.below.map(function(w){return Object.assign({mod:s.mod},w)}),ctx)));return el};
W.link=function(s){var el=h("a",{"class":"pill-s",href:s.href,target:"_blank",rel:"noopener noreferrer"});
 bind(s.label,function(t){setText(el,t)});if(s.aria)el.setAttribute("aria-label",s.aria);return el};
var armTimers={};
W.button=function(s,ctx){var pill=s.style==="pill",
 el=h(s.href?"a":"button",{"class":(pill?"pill":"pill-s"+(s.style==="danger"?" danger":""))+(pill&&s.colour?" pri":"")});
 if(!s.href)el.type="button";else{el.href=s.href;el.target="_blank";el.rel="noopener noreferrer"}
 var label=s.label,busy=false,armed=0;
 function show(){var t=busy&&s.busy_label!==undefined?val(s.busy_label):(armed?s.arm:val(label));
  t=t==null?"":String(t);if(busy&&s.busy_label!==undefined&&t)t=t.charAt(0).toUpperCase()+t.slice(1);setText(el,t);
  setClass(el,el.className.replace(/ ?arm\b/,"")+(armed?" arm":""))}
 bind(s.label,show);
 if(s.busy!==undefined)bind(s.busy,function(v){busy=!!v;el.disabled=busy||!!val(s.disabled);show()});
 if(s.disabled!==undefined)bind(s.disabled,function(v){el.disabled=!!v||busy});
 if(s.aria)el.setAttribute("aria-label",s.aria);
 if(pill&&s.colour)colourClass(el,s.colour,s.mod);
 if(s.href)return el;
 el.onclick=function(e){e.stopPropagation();if(el.disabled)return;
  if(s.arm&&Date.now()-armed>4000){armed=Date.now();show();setTimeout(function(){if(Date.now()-armed>=4000){armed=0;show()}},4100);return}
  armed=0;
  if(s.confirm&&!confirm(isBind(s.confirm)?val(s.confirm):s.confirm))return;
  function go(){el.disabled=true;
   post(s.post,s.body,function(r,st,b){el.disabled=false;
    if(st==401||st==429){alert((b&&b.message)||"PIN refused");return}
    afterPost(s,r,el)})}
  if(s.pin)withPin(go);else go()};
 return el};
// a switch: bound to a value on the server and POSTed ({value: true/false}) on change, or kept only in this page with "local": "name" (S._local.name)
S._local={};
W.toggle=function(s,ctx){var box=h("input",{type:"checkbox","class":"cbox "+(s.look||"neutral"),"aria-label":s.label||""}),el=box;
 if(s.text){el=h("label",{"class":"sub tgl"},[box,document.createTextNode(s.text)])}
 if(s.colour)colourClass(box,s.colour,s.mod);
 if(s.local){S._local[s.local]=s["default"]!==false;box.checked=S._local[s.local];box.onchange=function(){S._local[s.local]=box.checked;engineUpdate()};return el}
 if(s.module){bind("@enabled."+s.module,function(v){box.checked=!!v});         // switches a whole module on or off (POST /modules), then the page is built again
  box.onchange=function(){box.disabled=true;post("/modules",{name:s.module,enabled:box.checked},function(r){
   if(!r){box.disabled=false;box.checked=!box.checked;return}reloadInSettings()})};return el}
 bind(s.bind,function(v){box.checked=!!v});
 box.onchange=function(){var want=box.checked;post(s.post,s.body?Object.assign({value:want},s.body):{value:want},function(){refresh();ctx.saved()})};return el};
// a row of widgets side by side (wraps)
W.bar=function(s,ctx){return h("div",{"class":"bar"},buildAll((s.items||[]).map(function(w){return Object.assign({mod:s.mod},w)}),ctx))};
// ---- the module's own colour choice: a "Colour" button in the chosen colour that opens a pop-up with the palette's colours;
// the pick is kept for the module (core.set_module_colour)
// the palette in the server's order, without the ids a pick leaves out ("exclude": palette ids a pick leaves out)
function paletteOrder(s){return (LAY.palette||[]).filter(function(c){return (s.exclude||[]).indexOf(c.id)<0})}
function colourOfId(id){var r=null;(LAY.palette||[]).forEach(function(p){if(p.id===id)r=p});return r}
function mixWhite(hex){var n=[1,3,5].map(function(i){var v=parseInt(hex.substr(i,2),16);return Math.round(v+(255-v)*0.45)});return "#"+n.map(function(v){return (v<16?"0":"")+v.toString(16)}).join("")}
function rgbOf(hex){return parseInt(hex.substr(1,2),16)+","+parseInt(hex.substr(3,2),16)+","+parseInt(hex.substr(5,2),16)}
// a palette colour changed on the page: every box that uses it follows at once (the next page load has it from the server)
function applyPaletteVars(c){var s=document.documentElement.style,l=mixWhite(c.ui);
 s.setProperty("--c-"+c.id,c.ui);s.setProperty("--c-"+c.id+"-l",l);s.setProperty("--c-"+c.id+"-rgb",rgbOf(c.ui));s.setProperty("--c-"+c.id+"-l-rgb",rgbOf(l));
 (LAY.palette||[]).forEach(function(p){if(p.id===c.id){p.ui=c.ui;p.ui_l=l}})}
// a colour picker for one palette colour (Global main): it changes the colour everywhere it is used. It looks like the other colour picks
// (a small Colour button in its own colour); the system's colour chooser is an input laid invisibly over the button, so a tap opens it.
W.colourpick=function(s,ctx){var inp=h("input",{type:"color","class":"cp-native","aria-label":(s.label||"Colour")}),timer=null,
 btn=h("button",{type:"button","class":"pill-s pri c-"+s.id,text:"Colour",tabindex:"-1","aria-hidden":"true"}),el=h("span",{"class":"colourpick cp-wrap"},[btn,inp]);
 (LAY.palette||[]).forEach(function(p){if(p.id===s.id)inp.value=p.ui});
 inp.oninput=function(){var ui=inp.value;applyPaletteVars({id:s.id,ui:ui});clearTimeout(timer);timer=setTimeout(function(){post("/palette",{id:s.id,ui:ui},function(r){if(r)ctx.saved()})},250)};
 return el};
// a colour well: a Colour button in a colour of any #rrggbb (the LED colour editor); the system's colour chooser lies over it, cb(value) is called on every change
function colourWell(value,label,cb){var inp=h("input",{type:"color","class":"cp-native",value:value,"aria-label":label}),
 btn=h("button",{type:"button","class":"pill-s well",text:"Colour",tabindex:"-1","aria-hidden":"true"}),el=h("span",{"class":"colourpick cp-wrap"},[btn,inp]);
 function paint(){btn.style.setProperty("--well",inp.value);btn.style.setProperty("--well-l",mixWhite(inp.value))}
 inp.oninput=function(){paint();cb(inp.value)};paint();return el}
W.swatches=function(s,ctx){var btn=h("button",{type:"button","class":"pill-s pri",text:s.label||"Colour","aria-haspopup":"dialog"}),
 grid=h("span",{"class":"swatches grid"}),pop=h("div",{"class":"colours"},[h("div",{"class":"t",text:s.title||"Pick a colour"}),grid]),
 tint=s.tint?h("input",{type:"checkbox","class":"cbox pri",title:"Highlight: a coloured background (off = a neutral one)","aria-label":(s.title||"Colour")+": highlight with a coloured background"}):null,
 el=h("span",{"class":"colourpick"},[tint,btn,pop]),btns={},names={},p=ui.popup(pop);
 if(tint)colourClass(tint,s.key,s.mod);          // the tick box has the colour of its pick
 if(tint)tint.onchange=function(){var want=tint.checked;post("/colour",{module:s.mod,key:s.key,tint:want},function(r){if(r){refresh();ctx.saved()}else tint.checked=!want})};
 paletteOrder(s).forEach(function(c){names[c.id]=c.name;
  var b=h("button",{type:"button","class":"swatch",style:"--c:"+c.ui+";--cl:"+c.ui_l,"aria-label":c.name,"data-id":c.id});btns[c.id]=b;
  b.onclick=function(e){e.stopPropagation();post("/colour",{module:s.mod,key:s.key,colour:c.id},function(r){if(r){p.close();refresh();ctx.saved()}})};grid.appendChild(b)});
 btn.onclick=function(e){p.toggle(btn,e)};
 function paint(){var cur=(((S.colours||{})[s.mod])||{})[s.key]||"",real=cur;
  if(btn._cc!==real){if(btn._cc)btn.classList.remove("c-"+btn._cc);if(real)btn.classList.add("c-"+real);btn._cc=real;
   btn.setAttribute("aria-label",(s.label||"Colour")+": "+(names[cur]||cur||"not set"))}
  for(var id in btns){var on=id===cur;btns[id].classList.toggle("sel",on);btns[id].setAttribute("aria-pressed",on?"true":"false")}}
 function paintTint(){if(tint)tint.checked=tintOf(s.key,s.mod)}
 UPD.push(paint);UPD.push(paintTint);paint();paintTint();hook("settingsClose",function(){p.close()});return el};
// ---- the status box: a label, a headline and rows that show when it is tapped open (the clock box, the System box)
function dotLook(el,v){dot(el,v)}
W.status=function(s){var d=h("span",{"class":"dot"}),t=h("span",{"class":"nw"}),sub=h("span",{"class":"sub blk"}),
 el=h("span",{"class":"status"},[s.dot!==undefined?d:null,h("span",{},[t,sub])]);
 if(s.dot!==undefined)bind(s.dot,function(v){dotLook(d,v)});
 bind(s.text,function(v){setText(t,v==null?"":v)});bind(s.sub,function(v){setLines(sub,v);sh(sub,!!v)});
 if(s.lines!==undefined)bind(s.lines,function(v){if(!v||!v.length){setHtml(t,"...");setHtml(sub,"");return}setText(t,v[0]);setHtml(sub,v.slice(1).map(esc).join("<br>"))});return el};
// The box's main title (the middle line): a line that scrolls round like the carousel's only when it does not fit the box (and is not
// open, and is not a large clock). ticker(host, mod).set(html) shows html; its coloured parts (.pln, data-c = a colour reference) take the colour
// of their reference, which paint() keeps up to date when the user changes it. The scrolling copy is only in the page while it scrolls.
function ticker(host,mod){var el=h("span",{"class":"carousel"}),trk=h("span",{"class":"trk"}),html="",scrolling=false;el.appendChild(trk);host.appendChild(el);
 var SP='<span class="sp">\u00a0\u00a0\u2022\u00a0\u00a0</span>';
 function paint(){Array.prototype.forEach.call(trk.querySelectorAll(".pln"),function(x){var c=colourId(x.getAttribute("data-c"),mod),v=c?"var(--c-"+c+"-l)":"";if(x._v!==v){x._v=v;x.style.color=v}})}
 function show(){var half='<span class="t">'+html+(scrolling?SP:"")+'</span>';
  setHtml(trk,scrolling?half+half.replace('class="t"','class="t dup" aria-hidden="true"'):half);paint()}
 var cv=document.createElement("canvas").getContext("2d"),lastBig="";
 function fitBig(){var cs=getComputedStyle(host),w=host.clientWidth,hh=host.clientHeight,t=host.textContent,key=[t.length,w,hh,cs.fontFamily].join("|");      // text as big as the rows and the width allow
  if(key===lastBig||!w||!hh)return;lastBig=key;cv.font="bold 100px "+cs.fontFamily;
  host.style.fontSize=Math.max(10,Math.min(hh*0.8,w*0.96*100/(cv.measureText(t).width||1)))+"px"}
 function fit(){var box=host.closest&&host.closest(".now"),t=trk.querySelector(".t"),need=false,big=!!box&&box.hasAttribute("data-title-rows")&&!box.classList.contains("open");
  if(big)fitBig();else if(host.style.fontSize){host.style.fontSize="";lastBig=""}
  if(t&&box&&!big){      // the line never wraps, closed or open (page.css), so its width says if it fits
   var sp=t.querySelector(".sp");need=t.offsetWidth-(sp?sp.offsetWidth:0)>host.clientWidth+1}
  if(need!==scrolling){scrolling=need;el.classList.toggle("sc",scrolling);if(scrolling)el.style.setProperty("--d",Math.max(10,Math.round((el.textContent||"").length*0.28))+"s");show()}}
 hook("layout",fit);window.addEventListener("resize",fit);UPD.push(function(){paint();fit()});AFTER.push(fit);      // measured again on every update (the first time the box may not be laid out yet, or its text may come from the data the page kept) and once the page is built
 if(document.fonts&&document.fonts.ready)document.fonts.ready.then(fit);
 watchSize(host,fit);      // and whenever the line's room changes or it is first shown (a hidden box has no width), so it never waits for a click
 return {set:function(next){if(next===html)return;html=next;show();fit();later(fit)},paint:paint,fit:fit}}
// Calls fn when el's size changes, which includes the moment it is first laid out (it had no size while hidden or not yet in the page).
function watchSize(el,fn){if(window.ResizeObserver)try{new ResizeObserver(function(){fn()}).observe(el)}catch(e){}}
// Once more after the next paint: a measurement taken right after the DOM changed can precede the final layout (fonts, scrollbars).
function later(fn){if(window.requestAnimationFrame)requestAnimationFrame(function(){requestAnimationFrame(fn)});else setTimeout(fn,50)}
// "title_rows": "@path" = "full" | "upper" | "lower": the main title takes more of the box's three rows (the top line, the title, the
// bottom row) instead of one - the large clock - and is sized to fill them (data-title-rows, page.css); "open_if": "@path" -
// while that is false the box has nothing to show when tapped, so it does not open (and is not a button)
W.infobox=function(s,ctx){
 var el=h("div",{"class":"now rows",title:"Show or hide details",role:"button",tabindex:"0","aria-expanded":"false"}),
  head=h("b",{"class":s.title_small?"small":""}),canOpen=true;      // title_small: the main title is as big as the rows' text (still bold)
 if(s.label!==undefined){var lab=h("div",{"class":"nlabel"});el.appendChild(lab);bind(s.label,function(t){setText(lab,t==null||t===""?"\u00a0":t)})}   // the top line: a text or a binding; empty keeps its height
 el.appendChild(head);
 var tk=(s.parts!==undefined||s.title!==undefined)?ticker(head,s.mod):null;      // no title and no parts: the line is empty and takes no room
 if(tk&&s.parts!==undefined)bind(s.parts,function(ps){tk.set((ps||[]).map(function(p){return '<span class="pln" data-c="'+esc(p.colour||"")+'">'+esc(p.text)+'</span>'}).join(""))});
 else if(tk)bind(s.title,function(t){tk.set(esc(t==null?"":t))});
 (s.rows||[]).forEach(function(r){
  // row options: "main" = shown closed and open (else only open); "only": "closed" = shown only while the box is closed; "full" = no label
  // column, the value takes the whole width; "bleed" = runs out to the box's edges; "tight" = no divider and little room above
  var row=h("div",{"class":"row "+(r.main?"main":"more")+(r.only==="closed"?" x-closed":"")+(r.full?" r-full":"")+(r.bleed?" r-bleed":"")+(r.tight?" r-tight":"")+(r.keep||(r.value&&(r.value.type==="console"||r.value.type==="bar"))?" keep":"")+(r.cls?" "+r.cls:"")});      // "keep": a tap in it does not close the box (buttons, a log you select text in)
  row.appendChild(h("span",{"class":"k",text:r.label||""}));
  var spec=r.value||{type:"text",text:""};
  if(r.main&&spec.type==="text"&&spec.style!=="log")spec=Object.assign({},spec,{type:"carousel"});      // the line that shows while the box is closed is one line: it scrolls like the title when it is too long (a log stays text)
  var v=h("span",{"class":"v"+(spec.type==="carousel"?" fill":"")});v.appendChild(build(Object.assign({mod:s.mod},spec),ctx));row.appendChild(v);
  // "busy": "@path" - a small spinner next to the row's title while it is true: the row is being refreshed, what it shows stays until the new data is there
  // (a row without a visible title, such as the main row of a closed box, has a second one at its start: page.css shows the right one)
  if(r.busy!==undefined){var sp=h("span",{"class":"spin",role:"status","aria-label":"Refreshing"}),sp2=h("span",{"class":"spin alt","aria-hidden":"true"});
   row.firstChild.appendChild(sp);row.appendChild(sp2);bind(r.busy,function(x){sh(sp,!!x);sh(sp2,!!x)})}
  if(r.show!==undefined)bind(r.show,function(x){sh(row,!!x)});
  el.appendChild(row)});
 if(s.actions&&s.actions.length){var act=h("div",{"class":"row more hang keep"});
  buildAll(s.actions.map(function(w){return Object.assign({mod:s.mod},w)}),ctx).forEach(function(a){act.appendChild(a)});
  if(s.actions_show!==undefined)bind(s.actions_show,function(x){sh(act,!!x)});el.appendChild(act)}
 function toggle(){if(!canOpen)return;el.classList.toggle("open");el.setAttribute("aria-expanded",el.classList.contains("open"));fire("layout")}
 var lastMode=null,lastCan=null;
 if(s.title_rows!==undefined)bind(s.title_rows,function(v){v=v||"";if(v===lastMode)return;lastMode=v;if(v)el.setAttribute("data-title-rows",v);else el.removeAttribute("data-title-rows");fire("layout")});
 if(s.open_if!==undefined)bind(s.open_if,function(v){v=!!v;if(v===lastCan)return;lastCan=v;canOpen=v;el.classList.toggle("noopen",!canOpen);
  if(!canOpen){el.classList.remove("open");["role","tabindex","title","aria-expanded"].forEach(function(a){el.removeAttribute(a)});fire("layout")}
  else{el.setAttribute("role","button");el.setAttribute("tabindex","0");el.setAttribute("title","Show or hide details");el.setAttribute("aria-expanded",el.classList.contains("open")?"true":"false")}});
 el.onclick=function(e){if(e.target.closest&&e.target.closest("a,button,.keep"))return;toggle()};
 el.onkeydown=function(e){if((e.key=="Enter"||e.key==" ")&&e.target===el){e.preventDefault();toggle()}};
 return el};
// ---- carousel: one line of text that scrolls round (like a news ticker) only when it does not fit
W.carousel=function(s){var el=h("span",{"class":"carousel"}),trk=h("span",{"class":"trk"}),cur=null;el.appendChild(trk);
 // items are texts, or {text, n}: the count n is shown after the text in the subtitle colour
 function items(){var v=val(s.items!==undefined?s.items:s.text);return Array.isArray(v)?v:(v==null||v===""?[]:[String(v)])}
 function one(i){return i&&typeof i==="object"?String(i.text==null?"":i.text)+(i.n!=null?" "+i.n:""):String(i)}
 function text(){return items().map(one).join("  \u2022  ")}
 function body(){return items().map(function(i){return i&&typeof i==="object"?esc(i.text==null?"":i.text)+(i.n!=null?' <span class="cn">'+esc(i.n)+'</span>':""):esc(i)}).join("  \u2022  ")}
 // Scrolls only when the line is wider than its row. While it fits it is centred like the status row above it;
 // when it scrolls its holder (.v.fill) takes the whole row so the line can run past the edges.
 function fit(){var t=trk.querySelector(".t"),scroll=false,par=el.parentNode,row=el.closest&&el.closest(".row");
  if(t&&cur&&par&&row){var k=row.querySelector(".k");scroll=t.offsetWidth>row.clientWidth-(k&&k.offsetParent?k.offsetWidth:0)-12}      // the room is the row without its label column (open boxes show the labels)
  if(scroll!==el.classList.contains("sc")){el.classList.toggle("sc",scroll);if(scroll)el.style.setProperty("--d",Math.max(12,Math.round(cur.length*0.28))+"s")}
  if(par)par.classList.toggle("scrolling",scroll)}
 function set(t){if(t===cur&&trk.firstChild){fit();return}cur=t;
  var half='<span class="t">'+body()+'<span class="sp">\u00a0\u00a0\u2022\u00a0\u00a0</span></span>';
  setHtml(trk,t?half+half.replace('class="t"','class="t dup" aria-hidden="true"'):"");el.classList.remove("sc");fit()}
 UPD.push(function(){set(text())});set(text());later(fit);
 hook("layout",function(){fit()});window.addEventListener("resize",fit);watchSize(el,fit);return el};
// ---- a map of the time zones: a hand-drawn world on 24 bands (one per hour), the hour it is in each band along the top and its UTC offset along
// the bottom, the band of the clock's own time zone highlighted and a dot for every city. "map": "@path" = {cities: [{name, lon, lat, text}],
// utc (unix time), here (the clock's offset in hours)}, "format": "@path" ("24h", or a 12-hour form).
var WORLD_LAND=[
 [-168,66,-162,70,-156,71,-140,70,-128,70,-115,68,-95,72,-85,68,-80,63,-93,60,-94,58,-85,55,-80,52,-78,62,-70,60,-62,58,-56,52,-60,47,-66,45,-70,43,-76,38,-81,31,-80,25,-82,27,-85,30,-90,29,-97,27,-97,22,-92,18,-87,21,-88,16,-83,15,-83,10,-79,9,-77,8,-82,8,-86,12,-92,14,-97,16,-105,20,-110,24,-113,31,-117,32,-121,35,-124,40,-124,47,-128,51,-135,58,-146,61,-152,59,-158,57,-165,55,-160,59,-165,62],
 [-77,8,-72,12,-62,10,-52,5,-50,0,-44,-2,-35,-6,-39,-14,-41,-22,-48,-26,-53,-34,-58,-38,-62,-40,-65,-45,-68,-52,-70,-55,-74,-50,-73,-40,-71,-30,-70,-18,-76,-14,-81,-5,-80,0,-77,4],
 [-73,78,-60,82,-30,83,-20,78,-20,70,-30,67,-43,60,-50,64,-55,70],
 [-10,36,-9,43,-1,46,-4,48,2,51,8,54,10,58,5,62,14,68,25,71,40,68,60,70,80,73,105,77,130,72,150,71,170,70,180,68,180,65,165,60,155,58,160,52,143,52,140,47,135,43,129,35,122,40,121,31,118,24,108,21,106,10,100,13,104,2,98,8,98,16,92,22,87,21,80,15,77,8,73,17,67,25,57,25,56,27,51,25,56,17,44,13,35,28,34,31,36,36,28,37,26,40,23,36,20,40,13,45,16,41,18,40,12,38,8,44,3,43,-5,36],
 [-17,21,-10,30,-6,36,10,37,11,33,20,32,32,31,35,28,43,12,51,12,41,-2,40,-15,35,-24,32,-29,25,-34,18,-34,12,-17,13,-8,9,-1,9,4,-8,4,-13,8,-17,14],
 [114,-22,122,-18,130,-12,137,-12,142,-11,146,-19,153,-26,150,-37,141,-38,135,-34,129,-32,116,-35,113,-26],
 [-5,50,1,51,2,53,-2,56,-3,58.5,-6,58,-5,54,-3,53],
 [130,31,133,34,140,35,141,41,142,45,140,41,136,36,131,34],
 [44,-13,50,-15,48,-25,44,-24],
 [95,5,105,-6,103,-5,98,0],
 [109,1,118,7,119,1,116,-4,110,-3],
 [172,-35,178,-38,174,-42,170,-46,167,-45,172,-40],
 [-24,64,-14,65,-14,66,-22,66]];
W.worldmap=function(s){
 var NS="http://www.w3.org/2000/svg",W_=360,TOP=11,BOT=11,MAPH=139,H_=TOP+MAPH+BOT,host=h("div",{"class":"worldmap"});
 function X(lon){return lon+180}
 function Y(lat){return Math.max(TOP,TOP+75-Math.min(75,lat))}
 function el(name,attrs,parent){var e=document.createElementNS(NS,name);for(var k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e}
 var svg=el("svg",{"class":"cmap",viewBox:"0 0 "+W_+" "+H_,role:"img","aria-label":"Time zone map"}),bands=[],hours=[];
 for(var o=-12;o<=12;o++){var x0=Math.max(0,X(o*15-7.5)),x1=Math.min(W_,X(o*15+7.5));
  bands.push(el("rect",{"class":"band"+(o%2?" alt":""),x:x0,y:TOP,width:x1-x0,height:MAPH},svg));
  hours.push(el("text",{"class":"hr",x:(x0+x1)/2,y:TOP-2.5},svg));                              // the hour in this band (top)
  var u=el("text",{"class":"hr",x:(x0+x1)/2,y:H_-2.5},svg);u.textContent=o>0?"+"+o:String(o)}   // its UTC offset (bottom)
 WORLD_LAND.forEach(function(p){var pts=[];for(var i=0;i<p.length;i+=2)pts.push(X(p[i])+","+Y(p[i+1]));el("polygon",{"class":"land",points:pts.join(" ")},svg)});
 var dots=el("g",{},svg),made="",me=el("circle",{"class":"here",r:3.8},svg);host.appendChild(svg);
 function paint(){var m=val(s.map),fmt=val(s.format);if(!m)return;
  // the clock's own band is the one its place is in (summer time does not move a place into the next band), and its hour is the clock's own
  var here=m.dot?Math.round(m.dot.lon/15):Math.round(m.here);
  for(var i=0;i<bands.length;i++){var off=i-12,hr=Math.floor((((m.utc+(off===here&&m.dot?m.here:off)*3600)%86400)+86400)%86400/3600);
   if(fmt!=="24h")hr=hr%12||12;
   setText(hours[i],String(hr));var cls="band"+(off%2?" alt":"")+(off===here?" here":"");if(bands[i].getAttribute("class")!==cls)bands[i].setAttribute("class",cls)}
  var key=JSON.stringify(m.cities.map(function(x){return[x.name,x.lon,x.lat]}));
  if(key!==made){made=key;dots.innerHTML="";m.cities.forEach(function(ci){
   var d=el("circle",{"class":"city",cx:X(ci.lon),cy:Y(ci.lat),r:3.4},dots);el("title",{},d)})}
  Array.prototype.forEach.call(dots.childNodes,function(d,i){var ci=m.cities[i];if(ci)setText(d.firstChild,ci.name+" "+ci.text)});
  if(m.dot){me.setAttribute("cx",X(m.dot.lon));me.setAttribute("cy",Y(m.dot.lat));if(!me.firstChild)el("title",{},me);setText(me.firstChild,m.dot.name+" (here) "+m.dot.text);me.style.display=""}
  else me.style.display="none"}
 UPD.push(paint);paint();return host};
// ---- a list of things from the server, each with a button that opens a small form (the Wi-Fi networks)
// "style": "buttons": the links as grey buttons, all in one row (as many columns as links)
W.links=function(s){var btn=s.style==="buttons",el=h("span",{"class":"links keep"+(btn?" btns":"")});
 bind(s.items,function(ls){ls=ls||[];if(btn)el.style.setProperty("--n",ls.length||1);
  var html=ls.map(function(l){return '<a'+(btn?' class="pill-s"':'')+(l[2]?' title="'+esc(l[2])+'" aria-label="'+esc(l[2])+'"':'')+' href="'+esc(l[1])+'" target="_blank" rel="noopener noreferrer">'+esc(l[0])+'</a>'}).join("");setHtml(el,html)});return el};
// Rows in a box ("style": "compact") or a grid of short name / value pairs ("style": "grid"). "row" says which fields of an item to show:
//   lead / lead_big  a small line over a bold one in a column at the left (a date and a time)   title, href (the title is a link)   sub   tag, tag_colour
//   icon  {kind: "star" | "bell", post, on: the item's field, data: the data source the answer replaces, body: fixed fields, fields: {key: item field}}:
//         a round on / off button at the end that POSTs {...body, ...fields, on} (a favourite, a reminder)
// A line that scrolls round like the carousel when it is wider than its room, and stands still (left-aligned) when it fits: the names in a compact list
// (a player's, a game's). node is what it shows (a text node or a link); it is measured when it is shown, resized or its fonts arrive.
function marquee(node){var el=h("span",{"class":"carousel mq"}),trk=h("span",{"class":"trk"}),sp=h("span",{"class":"sp",text:"\u00a0\u00a0\u2022\u00a0\u00a0"}),t=h("span",{"class":"t"},[node,sp]),on=false;
 trk.appendChild(t);el.appendChild(trk);
 function fit(){var need=t.offsetWidth-sp.offsetWidth>el.clientWidth+1;if(!el.clientWidth||need===on)return;on=need;el.classList.toggle("sc",need);
  while(trk.childNodes.length>1)trk.removeChild(trk.lastChild);
  if(need){var d=t.cloneNode(true);d.className="t dup";d.setAttribute("aria-hidden","true");trk.appendChild(d);el.style.setProperty("--d",Math.max(10,Math.round((t.textContent||"").length*0.28))+"s")}}
 watchSize(el,fit);later(fit);if(document.fonts&&document.fonts.ready)document.fonts.ready.then(fit);return el}
W.list=function(s,ctx){var el=h("div",{"class":"wlist"+(s.style==="compact"?" compact keep":s.style==="grid"?" grid keep":"")}),pop=h("div"),popT=h("div",{"class":"t"}),msg=h("div",{"class":"msg"}),
 fields=[],go=h("button",{type:"button","class":"pill-s"}),cur=null,key="";
 var P=s.popup||{};
 pop.appendChild(popT);
 (P.fields||[]).forEach(function(f){var inp=h("input",{type:f.type==="password"?"password":"text",placeholder:f.label||"","aria-label":f.label||f.key,autocomplete:"off"});
  inp.onkeydown=function(e){if(e.key=="Enter"){e.preventDefault();submit()}};fields.push({f:f,el:inp});pop.appendChild(inp)});
 pop.appendChild(msg);pop.appendChild(h("div",{"class":"bar end"},[go]));
 var inner=h("div"),p;el.appendChild(inner);el.appendChild(pop);p=ui.popup(pop);
 function compactRow(it){var R=s.row,tag=R.tag?it[R.tag]:"",c=h("span",{"class":"pw",text:tag}),title=it[R.title||"title"],
  tn=R.href&&it[R.href]?h("a",{href:it[R.href],target:"_blank",rel:"noopener noreferrer",text:title}):document.createTextNode(title),
  t=h("span",{"class":"pn"},s.style==="compact"?[marquee(tn),h("span",{"class":"pg"},[marquee(document.createTextNode(it[R.sub||"sub"]||""))])]
   :[tn,h("span",{"class":"pg",text:it[R.sub||"sub"]||""})]);      // long names scroll (not in the grid style, its pairs are short)
  if(R.tag_colour&&it[R.tag_colour]){var id=colourId(it[R.tag_colour],s.mod);if(id)c.style.color="var(--c-"+id+"-l)"}
  var kids=[R.lead?h("span",{"class":"pl"},[h("span",{text:it[R.lead]||""}),h("b",{text:it[R.lead_big]||""})]):null,t,R.tag?c:null],ic=R.icon;
  if(ic){var b=ui.iconButton(ic.kind,!!it[ic.on],title);
   b.onclick=function(e){e.stopPropagation();b.disabled=true;var body={},k;for(k in (ic.body||{}))body[k]=ic.body[k];for(k in (ic.fields||{}))body[k]=it[ic.fields[k]];body.on=b.getAttribute("aria-pressed")!=="true";
    post(ic.post,body,function(r){b.disabled=false;if(r){if(ic.data)S[ic.data]=r;engineUpdate()}})};kids.push(b)}
  return h("div",{"class":"p"},kids)}
 function rowFor(it,i,extra){if(s.style==="compact"||s.style==="grid")return compactRow(it);var info=extra?it.sub:it[s.row.sub||"sub"],
  title=extra?it.title:it[s.row.title||"title"],b=h("button",{type:"button","class":"pill-s",text:extra?it.button:(s.row.button||"Select"),"aria-label":(extra?it.button:(s.row.button||"Select"))+" "+title});
  var item=extra?it.item:it;
  b.onclick=function(e){open(item,b,e)};
  return h("div",{"class":"srow"},[h("span",{},[document.createTextNode(title),info?h("span",{"class":"sub",text:info}):null]),b])}
 function open(it,b,e){if(p.isOpen()&&p.anchor===b){p.close();return}cur=it;
  setText(popT,((it.other&&P.title_other)||P.title||"").replace(/\{(\w+)\}/g,function(m,k){return it[k]!=null?it[k]:""}));setText(msg,"");
  var first=null;fields.forEach(function(x){var f=x.f,showIt=!f.show_if||!!it[f.show_if];x.el.style.display=showIt?"block":"none";
   x.el.value=it[f.key]!=null&&!f.blank?it[f.key]:"";if(showIt&&!first&&(f.focus!==false&&x.el.value===""))first=x.el});
  p.toggle(b,e);(first||go).focus()}
 function submit(){var body={},missing=null;
  fields.forEach(function(x){if(x.el.style.display!=="none"){body[x.f.key]=x.el.value;if(x.f.required&&!String(x.el.value).trim())missing=x.f}else if(cur[x.f.key]!=null)body[x.f.key]=cur[x.f.key]});
  if(missing){setText(msg,missing.required_msg||"Fill in "+(missing.label||missing.key));return}
  withPin(function(){go.disabled=true;setText(go,P.busy||"Working...");
   post(P.post,body,function(r,st,b){go.disabled=false;setText(go,P.submit||"OK");
    if(st==401||st==429){setText(msg,(b&&b.message)||"PIN refused");return}
    p.close();refresh()})})}
 setText(go,P.submit||"OK");go.onclick=submit;
 function paint(){var raw=val(s.items);if(raw==null){if(key!==null){key=null;inner.innerHTML=""}return}      // null: not known yet, nothing is said about it (no "Nobody ...")
  var items=raw,k=JSON.stringify(items)+"";if(k===key)return;key=k;
  inner.innerHTML="";
  items.forEach(function(it,i){inner.appendChild(rowFor(it,i,false))});
  if(!items.length&&s.empty)inner.appendChild(s.style==="compact"||s.style==="grid"?h("span",{text:s.empty}):h("div",{"class":"srow"},[h("span",{text:s.empty})]));
  (s.extra||[]).forEach(function(x,i){inner.appendChild(rowFor(x,i,true))})}
 UPD.push(function(){var shown=s.when===undefined||!!val(s.when);if(!shown){if(key!==""){key="";inner.innerHTML="";p.close()}return}paint()});
 hook("settingsClose",function(){p.close()});return el};
// ---- the standard "edit row": the title and a grey line on the left, a small button on the right (Edit, Add ...), and - once there is
// something to show - a list of tags underneath. Forms, the phone number table and the colour picks all use this one look.
//   r.el the row   r.btn the button   r.setSub(text)   r.setList(items, onRemove(i))   (an empty or missing list takes no room)
function editRow(o){var sub=h("span",{"class":"sub"}),title=document.createTextNode(o.title||""),
 btn=h("button",{type:"button","class":"pill-s",text:o.button||"Edit"}),btn2=o.button2?h("button",{type:"button","class":"pill-s",text:o.button2}):null,
 below=h("div",{"class":"below"}),left=h("span",{},[title,sub]),
 row=h("div",{"class":"srow wrap edit"},[left,btn2?h("span",{"class":"btns"},[btn,btn2]):btn,below]);
 if(o.aria)btn.setAttribute("aria-label",o.aria);if(o.aria2&&btn2)btn2.setAttribute("aria-label",o.aria2);sh(below,false);sh(sub,false);
 return {el:row,btn:btn,btn2:btn2,
  setTitle:function(t){title.nodeValue=t},
  // the row's buttons and tags take a colour ({ui, ui_l}: the fill and its lighter border) and, for effect "blink", blink like the LED
  setLook:function(c,effect,speed){var rgb=function(x){return parseInt(x.slice(1,3),16)+","+parseInt(x.slice(3,5),16)+","+parseInt(x.slice(5,7),16)};
   if(typeof c==="string"){row.style.setProperty("--primary-rgb","var(--c-"+c+"-rgb)");row.style.setProperty("--primary-l-rgb","var(--c-"+c+"-l-rgb)")}      // a palette id: it follows the colour as it is changed
   else{row.style.setProperty("--primary-rgb",rgb(c.ui));row.style.setProperty("--primary-l-rgb",rgb(c.ui_l))}
   var fx=effect&&effect!=="solid"?"lk-"+effect:"";
   row.classList.add("lk");if(row._fx!==fx){if(row._fx){row.classList.remove(row._fx);row.classList.remove("lk-fx")}if(fx){row.classList.add(fx);row.classList.add("lk-fx")}row._fx=fx}
   row.classList.toggle("lk-fast",speed==="fast")},
  setSub:function(t){setLines(sub,t);sh(sub,!!t)},
  setList:function(items,onRemove){below.innerHTML="";items=items||[];sh(below,items.length>0);if(!items.length)return;below.appendChild(tagList(items,onRemove))}}}
// the tags of a list (phone numbers, LED messages): with onRemove(i) each has a remove button, without it they are only shown
function tagList(items,onRemove){var tags=h("div",{"class":"tags"});
 items.forEach(function(it,i){var t=h("span",{"class":"tag"},[document.createTextNode(it)]);
  if(onRemove){var x=h("button",{type:"button","aria-label":"Remove "+it,html:"&#10005;"});x.onclick=function(e){e.stopPropagation();onRemove(i)};t.appendChild(x)}
  else t.style.paddingRight="12px";
  tags.appendChild(t)});return tags}
// ---- the standard foot of a settings table: buttons on the left (Add, Restore ...), an (i) button on the right that opens a read-only
// pop-up with the information text (no Done button: nothing in it is saved). f.setInfo(text) sets or, when empty, hides it.
function footRow(buttons){var info=h("button",{type:"button","class":"infobtn",text:"i",title:"Information","aria-label":"Information"}),
 text=h("div",{"class":"infotext"}),pop=h("div",{},[text]),
 el=h("div",{"class":"srow foot"},[h("span",{"class":"btns"},buttons),info,pop]),p=ui.popup(pop);   // the pop-up sits in the row so it finds its card
 info.onclick=function(e){p.toggle(info,e)};hook("settingsClose",function(){p.close()});sh(info,false);
 return {el:el,setInfo:function(t){setLines(text,t);sh(info,!!t)}}}
// ---- a panel that opens and closes inside its pop-up (the same calls as ui.popup): the picker's Add area while it is in an Edit pop-up
function inlinePanel(el){var q={onclose:null,anchor:null};sh(el,false);
 q.isOpen=function(){return el.style.display!=="none"};
 q.open=function(a){q.anchor=a;sh(el,true)};
 q.close=function(){if(!q.isOpen())return;sh(el,false);q.anchor=null;if(q.onclose)q.onclose()};
 q.toggle=function(a,e){if(e&&e.stopPropagation)e.stopPropagation();if(q.isOpen()&&q.anchor===a)q.close();else q.open(a)};return q}
// ---- a table to pick values for: groups of short items (phone numbers) with an Add pop-up per group (reply of GET source).
// With "edit": true a group is one short row with an Edit button (top right); the pop-up under it holds the group's tags (remove), the
// Add button (which opens the search / pick area inside the same pop-up), Restore, the help text and Done.
W.picker=function(s,ctx){var el=h("div",{"class":"wpicker"}),cfg=null,timer=null,addKey=null,
 list=h("div"),restore=h("button",{type:"button","class":"pill-s"}),foot=footRow([restore]),
 pop=h("div"),popT=h("div",{"class":"t"}),inp=h("input",{type:"text","aria-label":"Value to add"}),addB=h("button",{type:"button","class":"pill-s",text:"Add"}),msg=h("div",{"class":"msg"}),choices=h("div",{"class":"choices"});
 pop.appendChild(popT);pop.appendChild(h("div",{"class":"fld"},[inp,addB]));pop.appendChild(choices);pop.appendChild(msg);
 el.appendChild(list);if(!s.edit)el.appendChild(foot.el);el.appendChild(pop);
 var p=s.edit?inlinePanel(pop):ui.popup(pop),editors={};p.onclose=function(){addKey=null};
 if(s.edit)pop.classList.add("addarea");
 function rules(){return cfg.rules||{}}
 function tagList(g){return g.items.map(function(n){return g.notes&&g.notes[n]?n+" ("+g.notes[n]+")":n})}
 // the Edit pop-up of a group (made once, filled again on every change)
 function editor(g){var ed=editors[g.key];if(ed)return ed;
  var box=h("div"),done=h("button",{type:"button","class":"pill-s",text:"Done"});
  ed={box:box,done:done,p:ui.popup(box)};done.onclick=function(){ed.p.close()};ed.p.onclose=function(){p.close()};
  el.appendChild(box);editors[g.key]=ed;return ed}
 function fillEditor(g){var ed=editor(g),R=rules(),r=editRow({title:g.label,button:R.add_label||"Add",aria:(R.add_label||"Add")+" to "+g.label});
  r.setSub(g.sub||"");r.setList(tagList(g),function(i){g.items.splice(i,1);save()});r.btn.onclick=function(e){openAdd(g,r.btn,e)};
  ed.box.innerHTML="";ed.box.appendChild(r.el);ed.box.appendChild(pop);
  sh(restore,!!R.restore);if(R.restore){setText(restore,R.restore);restore.onclick=function(){if(R.restore_confirm&&!confirm(R.restore_confirm))return;cfg.groups.forEach(function(x){x.items=(cfg.defaults[x.key]||[]).slice()});save()}}
  if(R.help)ed.box.appendChild(h("div",{"class":"sub",text:R.help}));
  ed.box.appendChild(h("div",{"class":"bar end"},[restore,ed.done]))}
 function paint(){if(!cfg)return;var R=rules();
  list.innerHTML="";
  cfg.groups.forEach(function(g){
   if(s.edit){var e=editRow({title:g.label,button:R.edit_label||"Edit",aria:(R.edit_label||"Edit")+" "+g.label});
    e.setSub(g.sub||"");e.btn.onclick=function(ev){editor(g).p.toggle(e.btn,ev)};list.appendChild(e.el);fillEditor(g);return}
   var r=editRow({title:g.label,button:R.add_label||"Add",aria:(R.add_label||"Add")+" to "+g.label});
   r.setSub(g.sub||"");r.setList(tagList(g),function(i){g.items.splice(i,1);save()});
   r.btn.onclick=function(e){openAdd(g,r.btn,e)};list.appendChild(r.el)});
  if(s.edit)return;
  foot.setInfo(R.help||"");
  sh(restore,!!R.restore);if(R.restore){setText(restore,R.restore);restore.onclick=function(){if(R.restore_confirm&&!confirm(R.restore_confirm))return;cfg.groups.forEach(function(g){g.items=(cfg.defaults[g.key]||[]).slice()});save()}}
  sh(foot.el,!!(R.restore||R.help))}
 function openAdd(g,b,e){if(p.isOpen()&&addKey===g.key){p.toggle(b,e);return}addKey=g.key;var R=rules();
  setText(popT,(R.add_title||"Add to {group}").replace("{group}",g.label));inp.value="";inp.maxLength=R.max||40;setText(msg,"");
  inp.placeholder=g.choices?(g.free?"Type a name or pick one":"Search"):"";sh(addB,!g.choices||!!g.free);paintChoices(g);p.toggle(b,e);inp.focus()}
 // a group with "choices" ([{value,label,sub,disabled}]) lets the user pick from the list; the input filters it ("free": it may also add a typed value)
 function paintChoices(g){choices.innerHTML="";sh(choices,!!g.choices);if(!g.choices)return;
  var q=inp.value.toLowerCase(),shown=0;
  g.choices.forEach(function(c){if(g.items.indexOf(c.value)>=0||(q&&(c.label+" "+c.value).toLowerCase().indexOf(q)<0)||(!q&&g.initial&&!c.now))return;shown++;
   var b=h("button",{type:"button","class":"choice",disabled:c.disabled?"disabled":null},[document.createTextNode(c.label||c.value)]);
   if(c.sub)b.appendChild(h("span",{"class":"sub",text:c.sub}));
   b.onclick=function(){g.items.push(c.value);p.close();save()};choices.appendChild(b)});
  if(!shown)choices.appendChild(h("div",{"class":"sub",text:(!q&&g.initial?g.initial:g.empty)||"Nothing to pick"}))}
 function addItem(){if(!addKey)return;var R=rules(),allowed=new RegExp("[^"+(R.allowed||"\\s\\S")+"]","g"),n=inp.value.replace(allowed,""),say=function(t){setText(msg,t)},g=null;
  cfg.groups.forEach(function(x){if(x.key===addKey)g=x});
  if(n.length<(R.min||1))return say(R.min_msg||"Too short");
  if(R.unique)for(var i=0;i<cfg.groups.length;i++)if(cfg.groups[i].items.indexOf(n)>=0)return say(n+" is already used by "+cfg.groups[i].label);
  if(R.per_group&&g.items.length>=R.per_group)return say("At most "+R.per_group);
  g.items.push(n);p.close();save()}
 addB.onclick=addItem;inp.onkeydown=function(e){if(e.key=="Enter"){e.preventDefault();addItem()}};
 inp.oninput=function(){var g=null;cfg.groups.forEach(function(x){if(x.key===addKey)g=x});if(g)paintChoices(g)};
 function load(){xhrJson("GET",s.source,function(r){if(r){cfg=r;paint()}})}
 function save(){clearTimeout(timer);paint();timer=setTimeout(function(){var body={};cfg.groups.forEach(function(g){body[g.key]=g.items});
  post(s.source,body,function(r){if(r){cfg=r;paint();ctx.saved();if(s.reload)reloadData(s.reload)}})},100)}      // the data source that shows this list ("reload": its name; the stars of the players box) follows what was saved
 hook("settingsOpen",load);hook("settingsClose",function(){p.close()});return el};
// ---- rows of "something to do + what triggers it" (phone numbers: an action and the numbers that start it; the LED rows: a look and the
// messages that show it). One short row per entry (its title, a grey line and its triggers as tags) with an Edit button; the pop-up under it has
// the action (a select, when the answer lists "actions"), the row's options (the same controls as a form: switch, choice, select, number, colour,
// slider, range), the triggers with an Add field (or, with "choices", a list to pick from) and Delete row, Done. "Add row" asks for the action first.
// With rules.sort each row has a drag handle and the top row has priority (the same drag as the module picker).
// GET source -> {rows:[{id, action, title, sub, look:{colour, effect, speed}, items:[text | {value,label}], opts:{key:value}}], actions:[{value,label,sub,group}],
//  options:[control specs: {key, type, label, sub, options: "list", disabled_if:{key,value}}], lists:{name:[{value,label}]}, choices:[{value,label,sub,group}],
//  new:{opts}, note, defaults:{rows}, rules:{min,max,allowed,per_row,max_rows,unique,free,sort,add_row,add_row_title,add_label,add_title,min_msg,help,restore,restore_confirm}};
// POST source {rows:[{id, action, items:[value], opts}]} answers the same. The server writes the texts (title, sub, note), the page only draws them.
var TRIGGERS={};
function reloadTriggers(source){if(TRIGGERS[source])TRIGGERS[source]()}
W.triggers=function(s,ctx){var el=h("div",{"class":"wtrig"}),cfg=null,timer=null,want=0,editors={},openNew=false,rowEls=[],list=h("div"),
 addB=h("button",{type:"button","class":"pill-s",text:"Add row"}),restore=h("button",{type:"button","class":"pill-s"}),foot=footRow([addB,restore]),note=h("div",{"class":"sub note"}),
 pick=h("div"),pickT=h("div",{"class":"t"}),choices=h("div",{"class":"choices"}),pp=null;
 pick.appendChild(pickT);pick.appendChild(choices);el.appendChild(list);el.appendChild(note);el.appendChild(foot.el);el.appendChild(pick);pp=ui.popup(pick);
 function rules(){return cfg.rules||{}}
 function val(it){return it&&typeof it==="object"?it.value:it}
 function label(it){return it&&typeof it==="object"?(it.label||it.value):it}
 function editor(row){var ed=editors[row.id];if(ed)return ed;
  var box=h("div");ed={box:box,p:ui.popup(box),row:row};el.appendChild(box);editors[row.id]=ed;return ed}
 function used(value){return cfg.rows.some(function(r){return r.items.some(function(it){return val(it)===value})})}
 // the choices that are not in a row yet (rules.unique) as a list under a heading per group, each with its grey line
 function choiceList(row,host){host.innerHTML="";var any=false,last=null;
  (cfg.choices||[]).forEach(function(c){if(row.items.some(function(it){return val(it)===c.value})||(rules().unique&&used(c.value)))return;any=true;
   if(c.group&&c.group!==last){last=c.group;host.appendChild(h("div",{"class":"cat",text:c.group}))}
   var r=editRow({title:c.label,button:rules().add_label||"Add",aria:(rules().add_label||"Add")+" "+c.label});r.setSub(c.sub||"");
   r.btn.onclick=function(){row.items.push({value:c.value,label:c.label});rebuild(row);save()};host.appendChild(r.el)});
  if(!any)host.appendChild(h("div",{"class":"sub",text:"Every message is in a row already."}))}
 function disabledFor(row,box){(cfg.options||[]).forEach(function(o,i){if(!o.disabled_if)return;var c=box._ctl[i],off=(row.opts||{})[o.disabled_if.key]===o.disabled_if.value;
  Array.prototype.forEach.call(c.querySelectorAll("button,input"),function(x){x.disabled=off})})}
 // the pop-up of a row: made when it is opened and again when the row's triggers or action change (not for its options: a slider being dragged stays)
 function rebuild(row){var ed=editors[row.id];if(ed)fillEditor(row)}
 function fillEditor(row){var ed=editor(row),R=rules(),box=ed.box,msg=h("div",{"class":"msg"}),inp=h("input",{type:"text","aria-label":R.add_title||"Add",maxLength:R.max||40}),
  addI=h("button",{type:"button","class":"pill-s",text:R.add_label||"Add"}),del=h("button",{type:"button","class":"pill-s danger",text:"Delete row"}),done=h("button",{type:"button","class":"pill-s",text:"Done"});
  ed.row=row;box.innerHTML="";box._ctl=[];box.appendChild(h("div",{"class":"t",text:row.title||""}));
  if(cfg.actions&&cfg.actions.length){var sel=h("select",{"class":"ord","aria-label":"Action"}),groups={},order=[],known=false;
   cfg.actions.forEach(function(a){var g=a.group||"";if(!groups[g]){groups[g]=[];order.push(g)}if(a.value===row.action)known=true;
    groups[g].push('<option value="'+esc(a.value)+'"'+(a.value===row.action?" selected":"")+">"+esc(a.label)+"</option>")});
   sel.innerHTML=(known?"":'<option value="'+esc(row.action)+'" selected>'+esc(row.title)+" (not available)</option>")+order.map(function(g){return order.length>1&&g?'<optgroup label="'+esc(g)+'">'+groups[g].join("")+"</optgroup>":groups[g].join("")}).join("");
   sel.onchange=function(){row.action=sel.value;save()};box.appendChild(h("div",{"class":"frow"},[h("span",{text:"Action"}),sel]))}
  var F={options:cfg.lists||{}};Object.defineProperty(F,"values",{get:function(){return row.opts=row.opts||{}}});      // always the row's current options (an answer from the server replaces the object)
  (cfg.options||[]).forEach(function(o,i){var spec=Object.assign({},o,{type:o.type||"toggle"}),c=control(spec,F,function(){disabledFor(row,box);soft(row);save()}),
   wide=spec.type==="colour"||spec.type==="slider"||spec.type==="range",lab=h("span",{},[document.createTextNode(o.label||o.key)]);
   if(o.sub)lab.appendChild(h("span",{"class":"sub",text:o.sub}));if(spec.type==="colour")c._labelEl=lab;
   box._ctl.push(c);c._paint();box.appendChild(h("div",{"class":"frow"+(wide?" stack":"")},[lab,c]))});
  disabledFor(row,box);
  if(row.items.length)box.appendChild(tagList(row.items.map(label),function(i){row.items.splice(i,1);rebuild(row);save()}));
  function say(t){setText(msg,t)}
  function add(){var allowed=new RegExp("[^"+(R.allowed||"\\s\\S")+"]","g"),n=inp.value.replace(allowed,"");
   if(n.length<(R.min||1))return say(R.min_msg||"Too short");
   if(row.items.some(function(it){return val(it)===n}))return say(n+" is already in this row");
   if(R.per_row&&row.items.length>=R.per_row)return say("At most "+R.per_row);
   row.items.push(n);rebuild(row);save()}
  if(cfg.choices){var tog=h("button",{type:"button","class":"pill-s",text:R.add_label||"Add","aria-expanded":ed.addOpen?"true":"false"}),pl=h("div",{"class":"poplist"});
   if(ed.addOpen)choiceList(row,pl);sh(pl,!!ed.addOpen);                       // the list stays open while messages are added one after the other
   tog.onclick=function(){ed.addOpen=!ed.addOpen;if(ed.addOpen)choiceList(row,pl);sh(pl,ed.addOpen);tog.setAttribute("aria-expanded",ed.addOpen?"true":"false")};
   box.appendChild(h("div",{"class":"frow"},[h("span",{"class":"sub",text:R.add_title||""}),tog]));box.appendChild(pl)}
  else{addI.onclick=add;inp.onkeydown=function(e){if(e.key=="Enter"){e.preventDefault();add()}};
   box.appendChild(h("div",{"class":"fld"},[inp,addI]));box.appendChild(msg)}
  del.onclick=function(){var i=cfg.rows.indexOf(row);ed.p.close();if(i>=0)cfg.rows.splice(i,1);paint();save()};done.onclick=function(){ed.p.close()};
  box.appendChild(h("div",{"class":"bar end"},[del,done]))}
 function lookOf(row){var l=row.look;if(!l)return;var id=colourId(l.colour,"");return id?[id,l.effect,l.speed]:null}
 // an option changed: the row's own look follows at once (the server writes its title and grey line when it has saved)
 function soft(row){var re=rowEls[cfg.rows.indexOf(row)];if(!re)return;var o=row.opts||{};
  if(row.look&&o.colour){row.look={colour:o.colour,effect:o.effect,speed:o.speed};var lk=lookOf(row);if(lk)re.setLook(lk[0],lk[1],lk[2])}}
 function paint(){if(!cfg)return;var R=rules(),ids={};
  list.innerHTML="";rowEls=[];
  cfg.rows.forEach(function(row){ids[row.id]=1;
   var e=editRow({title:row.title,button:R.edit_label||"Edit",aria:(R.edit_label||"Edit")+" "+row.title});rowEls.push(e);
   e.setSub(row.sub||"");e.setList(row.items.map(label));var lk=lookOf(row);if(lk)e.setLook(lk[0],lk[1],lk[2]);
   if(R.sort){var grip=h("button",{type:"button","class":"grip",title:"Drag to move (or use the up and down arrow keys)","aria-label":"Move "+row.title+": drag, or use the up and down arrow keys",html:"&#8942;&#8942;"});
    e.el.insertBefore(grip,e.el.firstChild);e.el.setAttribute("data-id",row.id)}
   e.btn.onclick=function(ev){ev.stopPropagation();var ed=editor(row);ed.row=row;if(ed.p.isOpen())ed.p.close();else{fillEditor(row);ed.p.open(e.btn)}};list.appendChild(e.el);
   var q=editors[row.id];if(q&&q.p.isOpen())q.p.open(e.btn);                       // an open editor follows its row (the row's height changes with its tags)
   else if(openNew&&row===cfg.rows[cfg.rows.length-1]&&row.id){openNew=false;fillEditor(row);editor(row).p.open(e.btn)}});
  Object.keys(editors).forEach(function(id){if(!ids[id]){editors[id].p.close();if(editors[id].box.parentNode)editors[id].box.parentNode.removeChild(editors[id].box);delete editors[id]}});
  if(R.sort)sortable(list,function(names){var by={};cfg.rows.forEach(function(r){by[r.id]=r});cfg.rows=names.map(function(n){return by[n]});paint();save()});
  setText(note,cfg.note||"");sh(note,!!cfg.note);
  sh(addB,!R.max_rows||cfg.rows.length<R.max_rows);setText(addB,R.add_row||"Add row");
  sh(restore,!!R.restore);if(R.restore){setText(restore,R.restore);restore.onclick=function(){if(R.restore_confirm&&!confirm(R.restore_confirm))return;cfg.rows=JSON.parse(JSON.stringify((cfg.defaults||{}).rows||[]));Object.keys(editors).forEach(function(id){editors[id].p.close()});paint();save()}}
  foot.setInfo(R.help||"")}
 // what the server answered replaces the rows, but the row objects an open pop-up is working on stay (their texts and ids are updated), so a slider being dragged is not interrupted
 function adopt(r){var old={};cfg.rows.forEach(function(x){if(x.id)old[x.id]=x});
  r.rows=r.rows.map(function(x){var o=old[x.id];if(!o)return x;Object.keys(o).forEach(function(k){delete o[k]});return Object.assign(o,x)});
  cfg=r;paint();Object.keys(editors).forEach(function(id){var ed=editors[id];if(ed.p.isOpen()&&!ed.box.contains(document.activeElement))fillEditor(ed.row)})}
 function newRow(action){var fresh=(cfg.new&&cfg.new.opts)||{};cfg.rows.push({id:"",action:action||"",title:"",sub:"",items:[],opts:JSON.parse(JSON.stringify(fresh))});openNew=true;pp.close();save(true)}
 addB.onclick=function(e){if(!cfg.actions||!cfg.actions.length){newRow("");return}
  setText(pickT,rules().add_row_title||"Choose an action");choices.innerHTML="";
  cfg.actions.forEach(function(a){var b=h("button",{type:"button","class":"choice"},[document.createTextNode(a.label)]);
   if(a.sub||a.group)b.appendChild(h("span",{"class":"sub",text:a.sub||a.group}));b.onclick=function(){newRow(a.value)};choices.appendChild(b)});
  pp.toggle(addB,e)};
 function load(){xhrJson("GET",s.source,function(r){if(r){cfg=r;paint()}})}
 function save(quiet){clearTimeout(timer);want++;if(!quiet)paint();timer=setTimeout(function(){var n=want,body={rows:cfg.rows.map(function(r){return{id:r.id,action:r.action,items:r.items.map(val),opts:r.opts}})};
  post(s.source,body,function(r){if(r){ctx.saved();if(n===want)adopt(r)}})},100)}      // an answer to an older save is not used while a newer change is waiting
 TRIGGERS[s.source]=function(){xhrJson("GET",s.source,function(r){if(r&&cfg)adopt(r)})};         // reloadTriggers(source): the texts have changed on the server (the global level of the LED rows)
 hook("settingsOpen",load);hook("settingsClose",function(){pp.close()});
 hook("api",function(){if(cfg)cfg.rows.forEach(function(row,i){var lk=lookOf(row);if(lk&&rowEls[i])rowEls[i].setLook(lk[0],lk[1],lk[2])})});
 return el};
// ---- a console: lines of text in a box. "lines": "@path" replaces them all; "tail": "/url" adds what is new (GET url?from=N -> {text, size, reset})
W.console=function(s,ctx){var el=h("div",{"class":"console"+(s.nowrap?" nowrap":""),role:"log","aria-label":s.label||"Log"}),size=0,busy=false,rules=(s.rules||[]).map(function(r){return[new RegExp(r[0],"i"),r[1]]}),
 follow=s.follow?val(s.follow):true;
 if(s.height)el.style.height=s.height;
 function cls(l){for(var i=0;i<rules.length;i++)if(rules[i][0].test(l))return rules[i][1];return""}
 function row(l){return '<div'+(cls(l)?' class="'+cls(l)+'"':'')+'>'+esc(l.slice(0,300))+'</div>'}
 if(s.lines!==undefined)bind(s.lines,function(ls){ls=ls||[];var stick=el.scrollTop+el.clientHeight>=el.scrollHeight-8;
  setHtml(el,ls.map(row).join(""));if(stick)el.scrollTop=el.scrollHeight;if(s.hide_empty)sh(el,!!ls.length)});
 if(s.tail){var has=false,xp=null;
  var on=function(){return s.active===undefined||!!val(s.active)},
   inside=function(){xp=xp||(el.closest&&el.closest(".now"));return !xp||xp.classList.contains("open")},    // a log in an infobox is only read while the box is open
   poll=function(){sh(el,on()||has);if(busy||!inside()||(!on()&&size))return;busy=true;
   xhrJson("GET",s.tail+"?from="+size,function(r){busy=false;if(!r)return;
    if(r.reset)el.innerHTML="";
    if(r.text){el.insertAdjacentHTML("beforeend",r.text.split(/\r?\n/).filter(function(l){return l.length}).map(row).join(""));
     if(!s.follow||val(s.follow))el.scrollTop=el.scrollHeight}
    size=r.size;has=has||size>0;sh(el,on()||has)})};
  var was=false;sh(el,false);UPD.push(poll);
  hook("layout",function(){var now=inside();if(now&&!was){poll();el.scrollTop=el.scrollHeight}was=now})}
 if(s.show_if!==undefined)bind(s.show_if,function(v){sh(el,!!v)});return el};
// ---- a read-only table of name / value pairs (the About rows); rows come from "@path" or the reply of "source" (fetched when Settings opens)
W.info=function(s){var el=h("table",{"class":"about"});
 function paint(rows){setHtml(el,(rows||[]).map(function(r){return '<tr><td class="n">'+esc(r[0])+'</td><td>'+esc(r[1])+'</td></tr>'}).join(""))}
 if(s.rows!==undefined)bind(s.rows,paint);
 if(s.source)hook("settingsOpen",function(){xhrJson("GET",s.source,function(r){if(r)paint(r)})});return el};
// ---- the roster: one box per group (department or building) with a row per person, after CheckinChicken.
// "source": "@checkin" (what the check-in module puts in /api: groups of people, the status menu, buildings). The INNE / UTE button at the right of a
// row switches in / out (POST s.toggle {id}); a tap on the row opens the status menu in the middle of the screen (POST s.status {id, code, detail}). A grey row is out,
// a coloured one is in (the colour of the person's department or building), a status colours it with its own colour and puts its name on it.
// Only the palette's ids are used for colour. With several buildings a row of chips picks which ones this screen shows (kept in this browser;
// ?location=A,B in the address sets it). "mode": "colours": the settings list of departments / buildings with a colour pick each (GET s.get, POST s.post).
function rosterLocations(){var sel=[],q=(window.location.search||"").match(/[?&]location=([^&]*)/),k="checkin:locations";
 try{if(q){sel=decodeURIComponent(q[1].replace(/\+/g," ")).split(",").map(function(x){return x.trim()}).filter(Boolean);localStorage.setItem(k,sel.join("|"))}
  else sel=(localStorage.getItem(k)||"").split("|").filter(Boolean)}catch(e){}return sel}
function rosterSaveLocations(sel){try{localStorage.setItem("checkin:locations",sel.join("|"))}catch(e){}}
var ROSTER_TONES=["blue","green","orange","purple","cyan","yellow","bright-pink","red"];
function rosterAvatar(p,cls){var h0=0,i,n=String(p.name||"");for(i=0;i<n.length;i++)h0=(h0*31+n.charCodeAt(i))>>>0;
 var parts=n.trim().split(/\s+/).filter(Boolean),ini=parts.length>1?(parts[0][0]+parts[parts.length-1][0]):(parts[0]||"?").slice(0,2);
 if(p.photo)return '<span class="rp-av '+cls+'" role="img" aria-label="'+esc(n)+'" style="background-image:url(\''+esc(p.photo)+'\')"></span>';
 return '<span class="rp-av '+cls+' c-'+ROSTER_TONES[h0%ROSTER_TONES.length]+'" aria-hidden="true">'+esc(ini.toUpperCase())+'</span>'}
W.roster=function(s,ctx){
 if(s.mode==="colours")return rosterColours(s,ctx);
 var el=h("div",{"class":"roster"}),chips=h("div",{"class":"rp-chips"}),list=h("div",{"class":"rp-list"}),
  modal=h("div",{"class":"rp-modal",style:"display:none"}),
  sel=rosterLocations(),last="",D=null,cur=null;
 el.appendChild(chips);el.appendChild(list);document.body.appendChild(modal);
 function visible(p){if(!sel.length)return !p.restrict;return sel.indexOf(p.building)>=0||(!p.building&&!p.restrict)}
 function person(id){var r=null;((D&&D.groups)||[]).forEach(function(g){g.people.forEach(function(p){if(p.id===id)r=p})});return r}
 function colourCls(p){return p.colour?" c-"+p.colour:""}
 function paintChips(){var b=(D&&D.buildings)||[],html=b.length<2?"":['<button type="button" class="pill-s'+(sel.length?"":" pri")+'" data-loc="">All</button>'].concat(b.map(function(n){
  return '<button type="button" class="pill-s'+(sel.indexOf(n)>=0?" pri":"")+'" data-loc="'+esc(n)+'">'+esc(n)+'</button>'})).join("");setHtml(chips,html)}
 // a row: tap it for the status menu; the button at its right is in (INNE, green) / out (UTE, red) and switches. With a status the name and the status scroll round like a carousel.
 function row(p){var text=p.name+(p.text?"  ·  "+p.text:""),state=p.text?p.text:(p.in?"in":"out"),
  inner=p.status?'<span class="rp-mq" style="--d:'+Math.max(8,Math.round(text.length*.45))+'s"><span class="rp-trk"><span>'+esc(text)+'</span><span>'+esc(text)+'</span></span></span>'
   :'<span class="rp-n">'+esc(p.name)+'</span><span class="rp-s">'+esc(p.role||"")+'</span>';
  return '<div class="rp-r '+(p.colour?"pri"+colourCls(p):"out")+'" data-id="'+esc(p.id)+'"><button type="button" class="rp-t" data-act="menu" aria-label="'+esc(p.name)+': '+esc(state)+', open the status menu">'+inner+'</button>'+
   '<button type="button" class="pill-s pri rp-io c-'+(p.in?"green":"red")+'" data-act="toggle" aria-label="'+esc(p.name)+': '+(p.in?"checked in, tap to check out":"checked out, tap to check in")+'">'+(p.in?"INNE":"UTE")+'</button></div>'}
 function paint(){if(!D)return;paintChips();var html="";
  if(!D.total){setHtml(list,'<div class="sub rp-empty">'+esc(D.text)+'</div>');return}
  D.groups.forEach(function(g){var ps=g.people.filter(visible);if(!ps.length)return;
   var n=ps.filter(function(p){return p.in}).length;
   html+='<div class="rp-box"><div class="rp-gh"><span class="rp-gt">'+esc(g.title)+'</span><span class="sub">'+n+'/'+ps.length+'</span></div>'+ps.map(row).join("")+'</div>'});
  setHtml(list,html||'<div class="sub rp-empty">Nobody to show for the chosen buildings.</div>')}
 chips.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest("[data-loc]");if(!b)return;var n=b.getAttribute("data-loc");
  if(!n)sel=[];else{var i=sel.indexOf(n);if(i>=0)sel.splice(i,1);else sel.push(n)}rosterSaveLocations(sel);paint()});
 function take(r){if(r&&r.checkin){S.checkin=D=r.checkin;last="";paint()}}
 list.addEventListener("click",function(e){var b=e.target.closest&&e.target.closest("[data-act]");if(!b)return;var r=b.closest(".rp-r"),id=r&&r.getAttribute("data-id");if(!id)return;
  if(b.getAttribute("data-act")==="menu"){openMenu(id);return}
  b.disabled=true;post(s.toggle,{id:id},function(r2){b.disabled=false;take(r2)})});
 // ---- the status menu: a pop-up in the middle of the screen (about 60 % of its width): who it is, the statuses three in a row, a cross in the corner
 function menuHtml(p){var st=D.statuses||[],who=[p.department,p.building].filter(Boolean).join(" · ");
  return '<div class="rp-sheet" role="dialog" aria-modal="true" aria-label="Status for '+esc(p.name)+'"><button type="button" class="rp-x" data-close="1" title="Close" aria-label="Close">&#10005;</button>'+
   '<div class="rp-who"><label class="rp-avl"'+((S.enabled||{}).contacts?' title="Change the photo"':'')+'>'+rosterAvatar(p,"rp-avb")+((S.enabled||{}).contacts?'<input type="file" accept="image/*" aria-label="Photo of '+esc(p.name)+'" data-photo="1">':'')+'</label>'+
   '<div class="rp-wt"><div class="rp-wn">'+esc(p.name)+'</div>'+(who?'<div class="rp-wl">'+esc(who)+'</div>':'')+(p.role?'<div class="rp-wl">'+esc(p.role)+'</div>':'')+(p.phone?'<div class="rp-wl">'+esc(p.phone)+'</div>':'')+'</div></div>'+
   '<div class="rp-opts">'+st.map(function(x){return '<button type="button" class="pill-s pri rp-so c-'+esc(x.colour)+(p.status===x.code?" on":"")+'" data-code="'+esc(x.code)+'" aria-pressed="'+(p.status===x.code?"true":"false")+'">'+esc(x.label)+'</button>'}).join("")+
   '<button type="button" class="pill-s rp-so" data-code="">Clear status</button></div><div class="rp-need" style="display:none"></div></div>'}
 function openMenu(id){var p=person(id);if(!p)return;cur=id;modal.innerHTML=menuHtml(p);modal.style.display="";var x=modal.querySelector(".rp-x");if(x&&x.focus)x.focus()}
 function closeMenu(){modal.style.display="none";modal.innerHTML="";cur=null}
 function send(code,detail){var id=cur;post(s.status,{id:id,code:code,detail:detail||""},function(r){take(r);closeMenu()})}
 modal.addEventListener("click",function(e){if(e.target===modal){closeMenu();return}
  var b=e.target.closest&&e.target.closest("button");if(!b)return;
  if(b.hasAttribute("data-close")){closeMenu();return}
  if(b.hasAttribute("data-set")){var inp=modal.querySelector(".rp-need input");send(b.getAttribute("data-set"),inp?inp.value:"");return}
  if(!b.hasAttribute("data-code"))return;var code=b.getAttribute("data-code"),st=null;(D.statuses||[]).forEach(function(x){if(x.code===code)st=x});
  if(!st||!st.needs){send(code);return}
  var need=modal.querySelector(".rp-need"),type=st.needs==="time"?"time":st.needs==="date"?"date":"text";
  need.style.display="";need.innerHTML='<label class="sub">'+esc(st.label)+(st.needs==="time"?" at":st.needs==="date"?" until":": ")+' <input type="'+type+'" value="'+esc(st.default||"")+'" maxlength="60" aria-label="'+esc(st.label)+'"></label> <button type="button" class="pill-s pri c-'+esc(st.colour)+'" data-set="'+esc(code)+'">Set</button>';
  var inp2=need.querySelector("input");if(inp2&&inp2.focus)inp2.focus()});
 // a photo chosen in the menu: cut to a 160 px square in the browser, kept by the contacts module
 modal.addEventListener("change",function(e){var f=e.target&&e.target.getAttribute&&e.target.getAttribute("data-photo")&&e.target.files&&e.target.files[0],id=cur;if(!f||!id)return;
  var img=new Image(),url=URL.createObjectURL(f);
  img.onload=function(){var c=document.createElement("canvas"),n=160,m=Math.min(img.width,img.height),g=c.getContext("2d");c.width=c.height=n;
   g.drawImage(img,(img.width-m)/2,(img.height-m)/2,m,m,0,0,n,n);URL.revokeObjectURL(url);
   post("/contacts/photo",{id:id,photo:c.toDataURL("image/jpeg",.82)},function(r,st,b){if(!r){alert((b&&b.message)||"The photo was not saved");return}
    refresh();setTimeout(function(){if(cur===id){var p=person(id);if(p)modal.querySelector(".rp-avl").innerHTML=rosterAvatar(p,"rp-avb")+'<input type="file" accept="image/*" aria-label="Photo of '+esc(p.name)+'" data-photo="1">'}},1300)})};
  img.onerror=function(){URL.revokeObjectURL(url);alert("That file is not a picture")};img.src=url});
 hook("escape",function(){if(cur!==null){closeMenu();return true}});
 bind(s.source,function(d){if(!d)return;var key=d.rev+"|"+d.groups.length;if(key===last)return;last=key;D=d;paint()});
 return el};
// the settings list: a department / building per row with a select of palette colours ("Automatic" = the module picks one)
function rosterColours(s,ctx){var el=h("div",{"class":"roster-cols"}),R=null;
 function paint(){if(!R)return;var html="";["department","building"].forEach(function(kind){var rows=(R.colours||{})[kind]||[];if(!rows.length)return;
  html+='<div class="t rp-ct">'+(kind==="department"?"Departments":"Buildings")+'</div>'+rows.map(function(r){
   var opts='<option value="">Automatic</option>'+(LAY.palette||[]).map(function(c){return '<option value="'+esc(c.id)+'"'+(r.own&&r.colour===c.id?" selected":"")+'>'+esc(c.name)+'</option>'}).join("");
   return '<div class="srow"><span><span class="dot c-'+esc(r.colour)+' rp-sw"></span>'+esc(r.name)+'</span><select class="ord" data-kind="'+kind+'" data-name="'+esc(r.key)+'" aria-label="Colour of '+esc(r.name)+'">'+opts+'</select></div>'}).join("")});
  setHtml(el,html||'<div class="sub">Import people to pick colours for their departments and buildings.</div>')}
 el.addEventListener("change",function(e){var sl=e.target;if(!sl.getAttribute||!sl.getAttribute("data-kind"))return;
  post(s.post,{kind:sl.getAttribute("data-kind"),name:sl.getAttribute("data-name"),colour:sl.value},function(r){if(r){R=r;paint();ctx.saved();refresh()}})});
 function load(){xhrJson("GET",s.get,function(r){if(r){R=r;paint()}})}
 hook("settingsOpen",load);load();return el}
// ---- a module's own widget: its page.js registered custom(name, fn); fn(host, ctx) fills the empty element
W.custom=function(s,ctx){var host=h("div",{"class":"wcustom"+(s.cls?" "+s.cls:""),html:s.html||""}),f=CUSTOM[s.name];
 if(f)AFTER.push(function(){f(host,ctx)});          // after the layout is in the page, so the module may look its elements up by id
 else if(window.console)console.error("no custom widget",s.name);return host};
// ---- controls that make up a form: select, number, text, slider (bound to one key of the form's values)
function optionList(spec,F){var o=spec.options;if(typeof o==="string")o=isBind(o)?val(o):(F.options||{})[o];return o||[]}
function control(spec,F,change){var key=spec.key,el,paint;
 // "choice": the options as a row of buttons, the chosen one in the module's colour; a tap picks (el._after, set by the form, then closes its pop-up)
 if(spec.type==="choice"){el=h("span",{"class":"optrow",role:"group","aria-label":spec.aria||spec.label||key});var lastc="",btns=[];
  paint=function(){var opts=optionList(spec,F),k=JSON.stringify(opts);
   if(k!==lastc){lastc=k;el.innerHTML="";btns=opts.map(function(o){var b=h("button",{type:"button","class":"pill-s",text:o.label});
    b.onclick=function(e){e.stopPropagation();F.values[key]=o.value;change();if(el._after)el._after()};el.appendChild(b);return b})}
   opts.forEach(function(o,i){var on=String(o.value)===String(F.values[key]);btns[i].classList.toggle("pri",on);btns[i].setAttribute("aria-pressed",on?"true":"false")})};
  el._paint=paint;return el}
 if(spec.type==="select"){el=h("select",{"class":"ord","aria-label":spec.aria||spec.label||key});var last="";
  paint=function(){var opts=optionList(spec,F),k=JSON.stringify(opts);
   if(k!==last){last=k;var groups={},order=[],html="";
    opts.forEach(function(o,i){var g=o.group||"";if(!groups[g]){groups[g]=[];order.push(g)}groups[g].push('<option value="'+i+'">'+esc(o.label)+'</option>')});
    el.innerHTML=order.map(function(g){return g?'<optgroup label="'+esc(g)+'">'+groups[g].join("")+'</optgroup>':groups[g].join("")}).join("")}
   var cur=F.values[key];opts.forEach(function(o,i){if(String(o.value)===String(cur))el.value=String(i)})};
  el.onchange=function(){var o=optionList(spec,F)[+el.value];if(o){F.values[key]=o.value;change()}};
  el._paint=paint;return el}
 if(spec.type==="number"){el=h("input",{type:"number",min:spec.min,max:spec.max,"aria-label":spec.aria||spec.label||key});
  paint=function(){if(document.activeElement!==el)el.value=F.values[key]==null?"":F.values[key]};
  el.onchange=function(){var n=parseInt(el.value,10);if(!isNaN(n)){F.values[key]=Math.max(spec.min!=null?spec.min:n,Math.min(spec.max!=null?spec.max:n,n));change()}};
  el._paint=paint;return el}
 // "colour": the options ([{value,label}], palette ids) as balls in the colour they have now; a tap picks
 if(spec.type==="colour"){el=h("span",{"class":"swatches grid",role:"group","aria-label":spec.aria||spec.label||key});var lastk="",bs=[];
  paint=function(){var opts=optionList(spec,F),k=JSON.stringify(opts),name="";
   if(k!==lastk){lastk=k;el.innerHTML="";bs=opts.map(function(o){var id=colourId(o.value,""),b=h("button",{type:"button","class":"swatch",title:o.label,"aria-label":o.label,style:"--c:var(--c-"+id+");--cl:var(--c-"+id+"-l)"});
    b.onclick=function(e){e.stopPropagation();F.values[key]=o.value;change()};el.appendChild(b);return b})}
   opts.forEach(function(o,i){var on=String(o.value)===String(F.values[key]);bs[i].classList.toggle("sel",on);if(on)name=o.label});
   if(el._labelEl)setText(el._labelEl,(spec.label||"")+": "+name)};
  el._paint=paint;return el}
 // "slider": a level 0..1 on a 0-1000 slider ("scale": "log100" = logarithmic, finer near the dark end); null = "uses the default" ("default": the
 // value shown then, "null_text" / "own_text" the grey line, "null_button" the button that goes back to it)
 if(spec.type==="slider"){el=h("div",{"class":"stackctl"});
  var sl=h("input",{type:"range",min:0,max:1000,step:1,"aria-label":spec.aria||spec.label||key}),rv=h("span",{"class":"rv"}),nt=h("span",{"class":"sub"}),nb=spec.null_button?h("button",{type:"button","class":"pill-s",text:spec.null_button}):null,
   log=spec.scale==="log100",toS=function(b){return log?Math.round(1000*Math.log(1+b*99)/Math.log(100)):Math.round(b*1000)},fromS=function(p){return log?(Math.pow(100,p/1000)-1)/99:p/1000},
   pct=function(b){var v=b*100;return (v<10&&v>0?String(parseFloat(v.toFixed(1))):Math.round(v))+"%"};
  el.appendChild(h("span",{"class":"rangev"},[sl,rv]));if(spec.null_text||nb)el.appendChild(h("div",{"class":"frow"},[nt,nb]));
  paint=function(){var v=F.values[key],own=v!==null&&v!==undefined,x=own?v:(spec.default||0);sl.value=toS(x);setText(rv,pct(x));setText(nt,own?(spec.own_text||""):(spec.null_text||""));if(nb)nb.disabled=!own};
  sl.oninput=function(){F.values[key]=Math.round(fromS(+sl.value)*1000)/1000;paint();change()};
  if(nb)nb.onclick=function(e){e.stopPropagation();F.values[key]=null;paint();change()};
  el._paint=paint;return el}
 // "range": which LEDs of a strip ("max": how many): all, one or a range [first, last]; null = all
 if(spec.type==="range"){el=h("div",{"class":"stackctl"});
  var max=spec.max||1,ra=h("input",{type:"number",min:1,max:max,"aria-label":"First LED"}),rb=h("input",{type:"number",min:1,max:max,"aria-label":"Last LED"}),seg=h("span",{"class":"optrow",role:"group","aria-label":spec.aria||spec.label||key}),
   segB={},line=h("div",{"class":"frow"}),lab=h("span",{"class":"sub"}),ctl=h("span",{"class":"ctls"}),
   mode=function(){var v=F.values[key];return !v?"all":v[0]===v[1]?"one":"range"};
  [["all","All"],["one","One"],["range","Range"]].forEach(function(m){var bt=h("button",{type:"button","class":"pill-s",text:m[1]});segB[m[0]]=bt;seg.appendChild(bt);
   bt.onclick=function(e){e.stopPropagation();var v=F.values[key],a0=v?v[0]:1,b0=v?v[1]:1;
    F.values[key]=m[0]==="all"?null:m[0]==="one"?[a0,a0]:[a0,b0>a0?b0:Math.min(max,a0+1)];paint();change()}});
  var setR=function(){var x=parseInt(ra.value,10),y=parseInt(rb.value,10);if(isNaN(x))x=1;if(isNaN(y)||mode()==="one")y=x;
   x=Math.max(1,Math.min(max,x));y=Math.max(x,Math.min(max,y));F.values[key]=[Math.min(x,y),Math.max(x,y)];paint();change()};
  ra.onchange=rb.onchange=setR;line.appendChild(lab);line.appendChild(ctl);el.appendChild(seg);el.appendChild(line);
  paint=function(){var m=mode(),v=F.values[key];Object.keys(segB).forEach(function(k){segB[k].classList.toggle("pri",k===m)});
   sh(line,m!=="all");ctl.innerHTML="";if(m==="all")return;ra.value=v[0];rb.value=v[1];setText(lab,m==="one"?"LED number":"From and to");ctl.appendChild(ra);if(m==="range")ctl.appendChild(rb)};
  el._paint=paint;return el}
 if(spec.type==="toggle"){el=h("input",{type:"checkbox","class":"cbox neutral","aria-label":spec.aria||spec.label||key});
  paint=function(){el.checked=!!F.values[key]};el.onchange=function(){F.values[key]=el.checked;change()};el._paint=paint;return el}
 el=h("input",{type:"text","aria-label":spec.aria||spec.label||key});
 paint=function(){if(document.activeElement!==el)el.value=F.values[key]==null?"":F.values[key]};
 el.onchange=function(){F.values[key]=el.value;change()};el._paint=paint;return el}
// ---- a form: rows of controls kept in one JSON object on the server (GET returns {values, options}, POST takes {values} and returns the same)
W.form=function(s,ctx){var el=h("div",{"class":"wform"}),F={values:{},options:{},texts:{},lists:{}},timer=null,ctls=[],subs=[];
 // one edit row per field; its controls are in a pop-up that opens under the row's Edit button (changes save as they are made)
 (s.fields||[]).forEach(function(f){
  var r=editRow({title:f.title,button:f.button||"Edit",aria:"Edit "+(f.title||"")}),done=h("button",{type:"button","class":"pill-s",text:"Done"}),pop=h("div"),p;
  pop.appendChild(h("div",{"class":"t",text:f.popup_title||f.title||""}));
  // a field with one "choice" control is a simple pick: its pop-up is just the buttons, a tap picks and closes (no Done)
  var one=(f.controls||[]).length===1&&f.controls[0].type==="choice";
  (f.controls||[]).forEach(function(c){var e=control(Object.assign({},c,{aria:(f.title||"")+": "+(c.label||c.key)}),F,save);ctls.push(e);
   if(one){e._after=function(){p.close()};pop.appendChild(e)}
   else pop.appendChild(h("div",{"class":"frow"},[h("span",{text:c.label||c.key}),e]))});
  if(!one)pop.appendChild(h("div",{"class":"bar end"},[done]));
  el.appendChild(r.el);el.appendChild(pop);p=ui.popup(pop);
  r.btn.onclick=function(e){p.toggle(r.btn,e)};done.onclick=function(){p.close()};hook("settingsClose",function(){p.close()});
  subs.push(function(){r.setSub(f.sub_text?(F.texts||{})[f.sub_text]:f.sub);if(f.list)r.setList((F.lists||{})[f.list])});
  if(f.show!==undefined)bind(f.show,function(v){sh(r.el,!!v)})});
 function paint(){ctls.forEach(function(c){c._paint()});subs.forEach(function(f){f()})}
 function take(r){F.values=r.values||F.values;F.options=r.options||F.options;F.texts=r.texts||F.texts;F.lists=r.lists||F.lists}
 function load(){xhrJson("GET",s.get,function(r){if(!r)return;take(r);paint()})}
 function save(){clearTimeout(timer);paint();timer=setTimeout(function(){post(s.post||s.get,{values:F.values},function(r){
  if(r){take(r);paint();ctx.saved()}})},250)}
 hook("settingsOpen",load);load();return el};
// ---- drag and drop ordering: rows of a container, each with a ".grip" handle. Grab the handle (mouse, finger or pen) and move the row;
// the others make room as it passes them and onDone(names) gets the new order of the rows' data-id values when it is dropped.
// The handle also takes the arrow keys (up / down move the row, then onDone), so it works without a pointer. Esc while dragging cancels.
function sortable(box,onDone){
 function hasId(el){return !!el&&el.hasAttribute&&el.hasAttribute("data-id")}
 function rows(){return Array.prototype.filter.call(box.children,hasId)}
 function names(){return rows().map(function(r){return r.getAttribute("data-id")})}
 function same(a,b){return a.join("\n")===b.join("\n")}
 function mid(el){var r=el.getBoundingClientRect();return r.top+r.height/2}
 rows().forEach(function(row){var grip=row.querySelector(".grip");if(!grip)return;
  grip.addEventListener("pointerdown",function(e){
   if(e.pointerType==="mouse"&&e.button!==0)return;
   e.preventDefault();var start=names(),grab=e.clientY-row.getBoundingClientRect().top,y=e.clientY,tx=0,done=false,pid=e.pointerId,scroller=$("settings");
   try{grip.setPointerCapture(pid)}catch(x){}
   row.classList.add("drag");box.classList.add("dragging");
   // The grabbed row itself is never taken out of the document and put back (iOS Safari ends a touch whose element is re-inserted):
   // when it passes a neighbour, the NEIGHBOUR moves to the other side of it.
   function place(){for(var guard=0;guard<30;guard++){
     var r=row.getBoundingClientRect(),nat=r.top-tx,want=y-grab;
     tx=want-nat;row.style.transform="translateY("+tx+"px)";
     var c=want+r.height/2,prev=row.previousElementSibling,next=row.nextElementSibling;
     if(hasId(prev)&&c<mid(prev))box.insertBefore(prev,row.nextSibling);
     else if(hasId(next)&&c>mid(next))box.insertBefore(next,row);
     else break}}
   function move(ev){if(ev.pointerId!==pid)return;y=ev.clientY;place()}
   var scroll=setInterval(function(){var hh=window.innerHeight;                        // near the top / bottom edge: scroll Settings along
    if(y<70)scroller.scrollTop-=14;else if(y>hh-70)scroller.scrollTop+=14;else return;place()},16);
   function finish(cancel){if(done)return;done=true;clearInterval(scroll);
    grip.removeEventListener("pointermove",move);grip.removeEventListener("pointerup",up);grip.removeEventListener("pointercancel",lost);
    grip.removeEventListener("lostpointercapture",lost);document.removeEventListener("keydown",esc,true);
    try{grip.releasePointerCapture(pid)}catch(x){}
    row.classList.remove("drag");box.classList.remove("dragging");row.style.transform="";
    if(cancel){start.forEach(function(n){box.appendChild(rows().filter(function(r){return r.getAttribute("data-id")===n})[0])});return}
    var now=names();if(!same(start,now))onDone(now)}
   function up(ev){if(ev.pointerId===pid)finish(false)}
   function lost(ev){if(ev.pointerId===pid)finish(false)}            // the system took the pointer (a call, a gesture): keep what was dropped so far
   function esc(ev){if(ev.key==="Escape"){ev.stopPropagation();finish(true)}}
   grip.addEventListener("pointermove",move);grip.addEventListener("pointerup",up);grip.addEventListener("pointercancel",lost);
   grip.addEventListener("lostpointercapture",lost);document.addEventListener("keydown",esc,true)});
  var keyTimer=null;
  grip.addEventListener("keydown",function(e){if(e.key!=="ArrowUp"&&e.key!=="ArrowDown")return;e.preventDefault();
   var other=e.key==="ArrowUp"?row.previousElementSibling:row.nextElementSibling;
   if(!hasId(other))return;
   if(e.key==="ArrowUp")box.insertBefore(row,other);else box.insertBefore(other,row);
   grip.focus();clearTimeout(keyTimer);keyTimer=setTimeout(function(){onDone(names())},900)})})}
// ---- the module picker (the loader's own row in System): an Edit button opens a pop-up with every module - drag a row by its handle to
// move it, tick or untick its switch (the always-on ones have none) - and nothing is applied until it is closed with Done (or Esc, or a
// click outside); then the changes are saved and the page is built again with Settings still open.
function buildPicker(cols){
 var card=cols.querySelector('[data-box="system"] .card'),
  btn=h("button",{type:"button","class":"pill-s",text:"Edit","aria-haspopup":"dialog"}),list=h("div",{"class":"mlist"}),
  done=h("button",{type:"button","class":"pill-s",text:"Done"}),
  pop=h("div",{},[h("div",{"class":"t",text:"Modules: tick to switch on or off, drag the handle to move. The top one has priority."}),list,h("div",{"class":"bar end"},[done])]),
  row=h("div",{"class":"srow edit","data-picker":"modules"},[h("span",{},[document.createTextNode("Modules"),h("span",{"class":"sub",text:"Switch modules on or off and set their priority"})]),btn]);
 if(!card){card=h("div",{"class":"card"});cols.appendChild(h("section",{"class":"sec","data-box":"system"},[h("h2",{text:"System"}),card]))}
 card.insertBefore(row,card.firstChild);card.appendChild(pop);
 var p=ui.popup(pop),mods=[],boxes={};
 function paint(list2){mods=list2;boxes={};list.innerHTML="";
  mods.forEach(function(m){var cb;
   if(m.visible===false)cb=h("span",{"class":"sub fixed",text:"Always on"});                     // can be moved, not switched off
   else{cb=h("input",{type:"checkbox","class":"cbox neutral","data-module":m.name,"aria-label":m.title});cb.checked=m.enabled;boxes[m.name]=cb}
   var grip=h("button",{type:"button","class":"grip",title:"Drag to move (or use the up and down arrow keys)","aria-label":"Move "+m.title+": drag, or use the up and down arrow keys",html:"&#8942;&#8942;"}),
    left=h("span",{},[document.createTextNode(m.title),h("span",{"class":"sub",html:esc(m.description)+(m.note?"<br>"+esc(m.note):"")+(m.error?'<br><b class="modbad">Could not load: '+esc(m.error)+"</b>":"")})]);
   list.appendChild(h("div",{"class":"srow","data-id":m.name},[grip,left,cb]))});
  sortable(list,function(){})}                                                                       // the order is read from the page when Done is pressed
 function apply(){var order=Array.prototype.map.call(list.children,function(r){return r.getAttribute("data-id")}),
   was=mods.map(function(m){return m.name}),changes=[];
  mods.forEach(function(m){var cb=boxes[m.name];if(cb&&cb.checked!==m.enabled)changes.push({name:m.name,enabled:cb.checked})});
  var reorder=order.length&&order.join()!==was.join();
  if(!reorder&&!changes.length)return;
  var steps=[];if(reorder)steps.push(["/modules/order",{order:order}]);changes.forEach(function(c){steps.push(["/modules",c])});
  (function next(i){if(i>=steps.length)return reloadInSettings();
   post(steps[i][0],steps[i][1],function(r){if(!r){alert("Could not save the module changes");return reloadInSettings()}next(i+1)})})(0)}
 p.onclose=apply;
 btn.onclick=function(e){e.stopPropagation();if(p.isOpen()){p.close();return}
  xhrJson("GET","/modules",function(r){if(!r)return;paint(r.modules);p.open(btn)})};
 done.onclick=function(){p.close()}}
// ---- backgrounds: the picker's top background module draws (a fullscreen one hides those below, a part one leaves them)
function startBackgrounds(){(LAY.backgrounds||[]).forEach(function(b){
 var host=h("div",{"class":"bgpart "+(b.type==="part"?"part "+(b.position||"bottom"):"fullscreen"),"data-bg":b.mod});$("bg").appendChild(host);
 if(BACKGROUNDS[b.mod])BACKGROUNDS[b.mod](host,b)})}
var BACKGROUNDS={};
function background(mod,fn){BACKGROUNDS[mod]=fn}

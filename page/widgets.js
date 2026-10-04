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
// A colour reference: a palette id ("orange"), one of the module's own colour keys ("dcnow") or "module.key" of another module
function colourId(ref,mod){if(!ref)return"";var c=S.colours||LAY.colours||{};
 if(ref.indexOf(".")>0){var p=ref.split(".");return realColour((c[p[0]]||{})[p[1]]||"")}
 return realColour((c[mod]||{})[ref]||ref)}
// "Selected network" is not a colour of its own: it is the colour DCNow! or DCNET has right now, so it follows the switch
function realColour(id){if(id!=="network")return id;var sw=(S.colours||LAY.colours||{}).switcher||{};return sw[S.network||"dcnow"]||"orange"}
// Whether the background of a colour is coloured (the default) or neutral: the "Coloured background" box next to a colour pick
function tintOf(ref,mod){if(!ref)return true;var p=ref.indexOf(".")>0?ref.split("."):[mod,ref],t=(S.tints||LAY.tints||{})[p[0]]||{};return t[p[1]]!==false}
// An element with its own colour (a button of the module's colour key): it follows S.colours live and is not repainted with the
// module's primary colour, so the network buttons keep the colours chosen in Settings whichever network is selected.
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
 refresh();reloadData();fire("posted")}
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
 buildWiring(cols);
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
 var key=JSON.stringify([p,pk,S.tints||LAY.tints||{},S.network||"",(S.colours||{}).switcher||""]);if(key===themeKey)return;themeKey=key;
 var els=document.querySelectorAll("[data-mod]"),i,root="";
 for(i=0;i<(LAY.modules||[]).length&&!root;i++)root=realColour(p[LAY.modules[i]]||"");
 function paint(el,id){var old=el._pc;if(old===id)return;if(old)el.classList.remove("c-"+old);if(id)el.classList.add("c-"+id);el._pc=id}
 paint(document.body,root);
 for(i=0;i<els.length;i++)if(!els[i].hasAttribute("data-own-colour")){var m=els[i].getAttribute("data-mod");paint(els[i],realColour(p[m]||""));
  els[i].classList.toggle("plain",!!pk[m]&&!tintOf(m+"."+pk[m],m))}}   // a neutral background where the user switched the colour's background off
// ---- data sources a module asked for in its layout ("data": {"players": {"url": "/players", "every": 60}}): fetched into S.<name>
// every N seconds while the page is on screen (with "when": "settings", only while Settings is open); "retry_if": "busy" asks again
// after "retry" seconds while that field of the answer is true, and after a failed request
var DATA={};
function reloadData(){for(var ns in DATA)DATA[ns]()}
function startData(){var ns;for(ns in (LAY.data||{}))(function(ns,spec){
 var timer=null,seq=0,every=(spec.every||60)*1000,retry=(spec.retry||2)*1000,onlyInSettings=spec.when==="settings";
 function wanted(){return !document.hidden&&(!onlyInSettings||$("settings").classList.contains("open"))}
 function load(){clearTimeout(timer);if(!wanted())return;var mine=++seq;
  xhrJson("GET",spec.url,function(r){var again=every;
   if(mine!==seq)return;                      // a newer question was asked meanwhile: its answer counts, this older one must not overwrite it
   if(r){S[ns]=r;engineUpdate();if(spec.retry_if&&getPath(r,spec.retry_if))again=retry}else again=retry;
   timer=setTimeout(load,again)})}
 DATA[ns]=load;
 document.addEventListener("visibilitychange",function(){if(!document.hidden)load()});
 if(onlyInSettings){hook("settingsOpen",load);hook("settingsClose",function(){clearTimeout(timer)})}
 load()})(ns,LAY.data[ns])}
// ---- text, rows, buttons, links
W.text=function(s){var el=h("div",{"class":"wtext"+(s.muted?" sub":"")+(s.cls?" "+s.cls:"")});bind(s.text,function(t){setLines(el,t)});return el};
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
// the palette in the server's order; the network switcher's own colours cannot be "Selected network" (that would be a circle)
function paletteOrder(mod){return (LAY.palette||[]).filter(function(c){return !(c.id==="network"&&mod==="switcher")})}
function colourOfId(id){var r=null;(LAY.palette||[]).forEach(function(p){if(p.id===id)r=p});return r}
function mixWhite(hex){var n=[1,3,5].map(function(i){var v=parseInt(hex.substr(i,2),16);return Math.round(v+(255-v)*0.45)});return "#"+n.map(function(v){return (v<16?"0":"")+v.toString(16)}).join("")}
function rgbOf(hex){return parseInt(hex.substr(1,2),16)+","+parseInt(hex.substr(3,2),16)+","+parseInt(hex.substr(5,2),16)}
// a palette colour changed on the page: every box that uses it follows at once (the next page load has it from the server)
function applyPaletteVars(c){var s=document.documentElement.style,l=mixWhite(c.ui);
 s.setProperty("--c-"+c.id,c.ui);s.setProperty("--c-"+c.id+"-l",l);s.setProperty("--c-"+c.id+"-rgb",rgbOf(c.ui));s.setProperty("--c-"+c.id+"-l-rgb",rgbOf(l));
 (LAY.palette||[]).forEach(function(p){if(p.id===c.id){p.ui=c.ui;p.ui_l=l}})}
// a colour picker for one palette colour (Global main): it changes the colour everywhere it is used
W.colourpick=function(s,ctx){var inp=h("input",{type:"color","aria-label":s.label||"Colour"}),timer=null;
 (LAY.palette||[]).forEach(function(p){if(p.id===s.id)inp.value=p.ui});
 inp.oninput=function(){var ui=inp.value;applyPaletteVars({id:s.id,ui:ui});clearTimeout(timer);timer=setTimeout(function(){post("/palette",{id:s.id,ui:ui},function(r){if(r)ctx.saved()})},250)};
 return inp};
W.swatches=function(s,ctx){var btn=h("button",{type:"button","class":"pill-s pri",text:s.label||"Colour","aria-haspopup":"dialog"}),
 grid=h("span",{"class":"swatches grid"}),pop=h("div",{"class":"colours"},[h("div",{"class":"t",text:s.title||"Pick a colour"}),grid]),
 tint=s.tint?h("input",{type:"checkbox","class":"cbox pri",title:"Highlight: a coloured background (off = a neutral one)","aria-label":(s.title||"Colour")+": highlight with a coloured background"}):null,
 el=h("span",{"class":"colourpick"},[tint,btn,pop]),btns={},names={},p=ui.popup(pop);
 if(tint)colourClass(tint,s.key,s.mod);          // the tick box has the colour of its pick
 if(tint)tint.onchange=function(){var want=tint.checked;post("/colour",{module:s.mod,key:s.key,tint:want},function(r){if(r){refresh();ctx.saved()}else tint.checked=!want})};
 paletteOrder(s.mod).forEach(function(c){names[c.id]=c.name;
  var b=h("button",{type:"button","class":"swatch",style:"--c:"+c.ui+";--cl:"+c.ui_l,"aria-label":c.name,"data-id":c.id});btns[c.id]=b;
  b.onclick=function(e){e.stopPropagation();post("/colour",{module:s.mod,key:s.key,colour:c.id},function(r){if(r){p.close();refresh();ctx.saved()}})};grid.appendChild(b)});
 btn.onclick=function(e){p.toggle(btn,e)};
 function paint(){var cur=(((S.colours||{})[s.mod])||{})[s.key]||"",real=realColour(cur);
  if(btn._cc!==real){if(btn._cc)btn.classList.remove("c-"+btn._cc);if(real)btn.classList.add("c-"+real);btn._cc=real;
   btn.setAttribute("aria-label",(s.label||"Colour")+": "+(names[cur]||cur||"not set"))}
  if(btns.network){var nw=colourOfId(realColour("network"));if(nw)btns.network.style.cssText="--c:"+nw.ui+";--cl:"+nw.ui_l}      // the ball shows the network's colour now
  for(var id in btns){var on=id===cur;btns[id].classList.toggle("sel",on);btns[id].setAttribute("aria-pressed",on?"true":"false")}}
 function paintTint(){if(tint)tint.checked=tintOf(s.key,s.mod)}
 UPD.push(paint);UPD.push(paintTint);paint();paintTint();hook("settingsClose",function(){p.close()});return el};
// ---- a block that opens and closes (the debug log bar)
W.expander=function(s,ctx){var open=false,body=h("div",{"class":"xbody"},buildAll((s.items||[]).map(function(w){return Object.assign({mod:s.mod},w)}),ctx)),
 b=h("button",{type:"button","class":"wide"},[h("span",{text:s.label}),h("span",{"class":"arrow",html:"&#9656;"})]),
 el=h("div",{"class":"xpand"},[h("div",{"class":"bar"},[b]),body]);sh(body,false);
 b.onclick=function(){open=!open;sh(body,open);b.classList.toggle("open",open);el.classList.toggle("open",open);fire(open?"expand":"collapse",s.id||s.label)};return el};
// ---- the status box: a label, a headline and rows that show when it is tapped open (network box, players box)
function dotLook(el,v){if(v===null||typeof v==="object")lookDot(el,v);else dot(el,v)}
W.status=function(s){var d=h("span",{"class":"dot"}),t=h("span",{"class":"nw"}),sub=h("span",{"class":"sub blk"}),
 el=h("span",{"class":"status"},[s.dot!==undefined?d:null,h("span",{},[t,sub])]);
 if(s.dot!==undefined)bind(s.dot,function(v){dotLook(d,v)});
 bind(s.text,function(v){setText(t,v==null?"":v)});bind(s.sub,function(v){setLines(sub,v);sh(sub,!!v)});
 if(s.lines!==undefined)bind(s.lines,function(v){if(!v||!v.length){setHtml(t,"...");setHtml(sub,"");return}setText(t,v[0]);setHtml(sub,v.slice(1).map(esc).join("<br>"))});return el};
W.infobox=function(s,ctx){
 var el=h("div",{"class":"now rows",title:"Show or hide details",role:"button",tabindex:"0","aria-expanded":"false"}),
  head=h("b");
 if(s.label!==undefined){var lab=h("div",{"class":"nlabel"});el.appendChild(lab);bind(s.label,function(t){setText(lab,t==null||t===""?"\u00a0":t)})}   // the top line: a text or a binding; empty keeps its height
 el.appendChild(head);
 if(s.parts!==undefined)bind(s.parts,function(ps){var html=(ps||[]).map(function(p){return '<span class="pln" data-c="'+esc(p.colour||"")+'">'+esc(p.text)+'</span>'}).join("");
  if(head._html!==html){setHtml(head,html);Array.prototype.forEach.call(head.querySelectorAll(".pln"),function(x){var c=colourId(x.getAttribute("data-c"),s.mod);if(c)x.style.color="var(--c-"+c+"-l)"})}});
 else bind(s.title,function(t){setText(head,t==null?"":t)});
 (s.rows||[]).forEach(function(r){
  var row=h("div",{"class":"row "+(r.main?"main":"more")+(r.cls?" "+r.cls:"")});
  row.appendChild(h("span",{"class":"k",text:r.label||""}));
  var v=h("span",{"class":"v"+(r.value&&r.value.type==="carousel"?" fill":"")});v.appendChild(build(Object.assign({mod:s.mod},r.value||{type:"text",text:""}),ctx));row.appendChild(v);
  if(r.main&&!(r.value&&r.value.type==="carousel"))row.appendChild(h("span",{"class":"arrow",html:"&#9656;"}));   // a scrolling line has no arrow: the box still opens on a tap
  if(r.show!==undefined)bind(r.show,function(x){sh(row,!!x)});
  el.appendChild(row)});
 if(s.actions&&s.actions.length){var act=h("div",{"class":"row more hang keep"});
  buildAll(s.actions.map(function(w){return Object.assign({mod:s.mod},w)}),ctx).forEach(function(a){act.appendChild(a)});
  if(s.actions_show!==undefined)bind(s.actions_show,function(x){sh(act,!!x)});el.appendChild(act)}
 function toggle(){el.classList.toggle("open");el.setAttribute("aria-expanded",el.classList.contains("open"));fire("layout")}
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
 // Scrolls only when the line is wider than its row (minus the arrow). While it fits it is centred like the status row above it;
 // when it scrolls its holder (.v.fill) takes the whole row so the line can run past the edges, and the arrow stays at the end.
 function fit(){var t=trk.querySelector(".t"),scroll=false,par=el.parentNode,row=el.closest&&el.closest(".row");
  if(t&&cur&&par&&row&&!(el.closest(".now.open"))){var arrow=row.querySelector(".arrow");
   scroll=t.offsetWidth>row.clientWidth-(arrow?arrow.offsetWidth+8:0)-12}
  if(scroll!==el.classList.contains("sc")){el.classList.toggle("sc",scroll);if(scroll)el.style.setProperty("--d",Math.max(12,Math.round(cur.length*0.28))+"s")}
  if(par)par.classList.toggle("scrolling",scroll)}
 function set(t){if(t===cur&&trk.firstChild){fit();return}cur=t;
  var half='<span class="t">'+body()+'<span class="sp">\u00a0\u00a0\u2022\u00a0\u00a0</span></span>';
  setHtml(trk,t?half+half.replace('class="t"','class="t dup" aria-hidden="true"'):"");el.classList.remove("sc");fit()}
 UPD.push(function(){set(text())});set(text());
 hook("layout",function(){fit()});window.addEventListener("resize",fit);return el};
// ---- a list of things from the server, each with a button that opens a small form (the Wi-Fi networks)
W.links=function(s){var el=h("span",{"class":"links keep"});
 bind(s.items,function(ls){var html=(ls||[]).map(function(l){return '<a href="'+esc(l[1])+'" target="_blank" rel="noopener noreferrer">'+esc(l[0])+'</a>'}).join("");setHtml(el,html)});return el};
W.list=function(s,ctx){var el=h("div",{"class":"wlist"+(s.style==="compact"?" compact keep":"")}),pop=h("div"),popT=h("div",{"class":"t"}),msg=h("div",{"class":"msg"}),
 fields=[],go=h("button",{type:"button","class":"pill-s"}),cur=null,key="";
 var P=s.popup||{};
 pop.appendChild(popT);
 (P.fields||[]).forEach(function(f){var inp=h("input",{type:f.type==="password"?"password":"text",placeholder:f.label||"","aria-label":f.label||f.key,autocomplete:"off"});
  inp.onkeydown=function(e){if(e.key=="Enter"){e.preventDefault();submit()}};fields.push({f:f,el:inp});pop.appendChild(inp)});
 pop.appendChild(msg);pop.appendChild(h("div",{"class":"bar end"},[go]));
 var inner=h("div"),p;el.appendChild(inner);el.appendChild(pop);p=ui.popup(pop);
 function compactRow(it){var tag=s.row.tag?it[s.row.tag]:"",c=h("span",{"class":"pw",text:tag}),
  t=h("span",{"class":"pn"},[document.createTextNode(it[s.row.title||"title"]),h("span",{"class":"pg",text:it[s.row.sub||"sub"]||""})]);
  if(s.row.tag_colour&&it[s.row.tag_colour]){var id=colourId(it[s.row.tag_colour],s.mod);if(id)c.style.color="var(--c-"+id+"-l)"}
  return h("div",{"class":"p"},[t,c])}
 function rowFor(it,i,extra){if(s.style==="compact")return compactRow(it);var info=extra?it.sub:it[s.row.sub||"sub"],
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
 function paint(){var items=val(s.items)||[],k=JSON.stringify(items);if(k===key)return;key=k;
  inner.innerHTML="";
  items.forEach(function(it,i){inner.appendChild(rowFor(it,i,false))});
  if(!items.length&&s.empty)inner.appendChild(s.style==="compact"?h("span",{text:s.empty}):h("div",{"class":"srow"},[h("span",{text:s.empty})]));
  (s.extra||[]).forEach(function(x,i){inner.appendChild(rowFor(x,i,true))})}
 UPD.push(function(){var shown=s.when===undefined||!!val(s.when);if(!shown){if(key!==""){key="";inner.innerHTML="";p.close()}return}paint()});
 hook("settingsClose",function(){p.close()});return el};
// ---- the standard "edit row": the title and a grey line on the left, a small button on the right (Edit, Add ...), and - once there is
// something to show - a list of tags underneath. Forms, the phone number table and the colour picks all use this one look.
//   r.el the row   r.btn the button   r.setSub(text)   r.setList(items, onRemove(i))   (an empty or missing list takes no room)
function editRow(o){var sub=h("span",{"class":"sub"}),title=document.createTextNode(o.title||""),
 btn=h("button",{type:"button","class":"pill-s",text:o.button||"Edit"}),btn2=o.button2?h("button",{type:"button","class":"pill-s",text:o.button2}):null,
 below=h("div",{"class":"below"}),left=h("span",{},[title,sub]),
 row=h("div",{"class":"srow wrap"},[left,btn2?h("span",{"class":"btns"},[btn,btn2]):btn,below]);
 if(o.aria)btn.setAttribute("aria-label",o.aria);if(o.aria2&&btn2)btn2.setAttribute("aria-label",o.aria2);sh(below,false);sh(sub,false);
 return {el:row,btn:btn,btn2:btn2,
  setTitle:function(t){title.nodeValue=t},
  // the row's buttons and tags take a colour ({ui, ui_l}: the fill and its lighter border) and, for effect "blink", blink like the LED
  setLook:function(c,effect,speed){var rgb=function(x){return parseInt(x.slice(1,3),16)+","+parseInt(x.slice(3,5),16)+","+parseInt(x.slice(5,7),16)};
   row.style.setProperty("--primary-rgb",rgb(c.ui));row.style.setProperty("--primary-l-rgb",rgb(c.ui_l));
   var fx=effect&&effect!=="solid"?"lk-"+effect:"";
   row.classList.add("lk");if(row._fx!==fx){if(row._fx){row.classList.remove(row._fx);row.classList.remove("lk-fx")}if(fx){row.classList.add(fx);row.classList.add("lk-fx")}row._fx=fx}
   row.classList.toggle("lk-fast",speed==="fast")},
  setSub:function(t){setLines(sub,t);sh(sub,!!t)},
  setList:function(items,onRemove){below.innerHTML="";items=items||[];sh(below,items.length>0);if(!items.length)return;
   var tags=h("div",{"class":"tags"});
   items.forEach(function(it,i){var t=h("span",{"class":"tag"},[document.createTextNode(it)]);
    if(onRemove){var x=h("button",{type:"button","aria-label":"Remove "+it,html:"&#10005;"});x.onclick=function(e){e.stopPropagation();onRemove(i)};t.appendChild(x)}
    else t.style.paddingRight="12px";
    tags.appendChild(t)});below.appendChild(tags)}}}
// ---- the standard foot of a settings table: buttons on the left (Add, Restore ...), an (i) button on the right that opens a read-only
// pop-up with the information text (no Done button: nothing in it is saved). f.setInfo(text) sets or, when empty, hides it.
function footRow(buttons){var info=h("button",{type:"button","class":"infobtn",text:"i",title:"Information","aria-label":"Information"}),
 text=h("div",{"class":"infotext"}),pop=h("div",{},[text]),
 el=h("div",{"class":"srow foot"},[h("span",{"class":"btns"},buttons),info,pop]),p=ui.popup(pop);   // the pop-up sits in the row so it finds its card
 info.onclick=function(e){p.toggle(info,e)};hook("settingsClose",function(){p.close()});sh(info,false);
 return {el:el,setInfo:function(t){setLines(text,t);sh(info,!!t)}}}
// ---- a table to pick values for: groups of short items (phone numbers) with an Add pop-up per group (reply of GET source)
W.picker=function(s,ctx){var el=h("div",{"class":"wpicker"}),cfg=null,timer=null,addKey=null,
 list=h("div"),restore=h("button",{type:"button","class":"pill-s"}),foot=footRow([restore]),
 pop=h("div"),popT=h("div",{"class":"t"}),inp=h("input",{type:"text","aria-label":"Value to add"}),addB=h("button",{type:"button","class":"pill-s",text:"Add"}),msg=h("div",{"class":"msg"}),choices=h("div",{"class":"choices"});
 pop.appendChild(popT);pop.appendChild(h("div",{"class":"fld"},[inp,addB]));pop.appendChild(choices);pop.appendChild(msg);
 el.appendChild(list);el.appendChild(foot.el);el.appendChild(pop);
 var p=ui.popup(pop);p.onclose=function(){addKey=null};
 function rules(){return cfg.rules||{}}
 function paint(){if(!cfg)return;var R=rules();
  list.innerHTML="";
  cfg.groups.forEach(function(g){
   var r=editRow({title:g.label,button:R.add_label||"Add",aria:(R.add_label||"Add")+" to "+g.label});
   r.setSub(g.sub||"");r.setList(g.items.map(function(n){return g.notes&&g.notes[n]?n+" ("+g.notes[n]+")":n}),function(i){g.items.splice(i,1);save()});
   r.btn.onclick=function(e){openAdd(g,r.btn,e)};list.appendChild(r.el)});
  foot.setInfo(R.help||"");
  sh(restore,!!R.restore);if(R.restore){setText(restore,R.restore);restore.onclick=function(){cfg.groups.forEach(function(g){g.items=(cfg.defaults[g.key]||[]).slice()});save()}}
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
  post(s.source,body,function(r){if(r){cfg=r;paint();ctx.saved()}})},100)}
 hook("settingsOpen",load);hook("settingsClose",function(){p.close()});return el};
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
   inside=function(){xp=xp||(el.closest&&el.closest(".xpand"));return !xp||xp.classList.contains("open")},
   poll=function(){sh(el,on()||has);if(busy||!inside()||(!on()&&size))return;busy=true;
   xhrJson("GET",s.tail+"?from="+size,function(r){busy=false;if(!r)return;
    if(r.reset)el.innerHTML="";
    if(r.text){el.insertAdjacentHTML("beforeend",r.text.split(/\r?\n/).filter(function(l){return l.length}).map(row).join(""));
     if(!s.follow||val(s.follow))el.scrollTop=el.scrollHeight}
    size=r.size;has=has||size>0;sh(el,on()||has)})};
  sh(el,false);UPD.push(poll);hook("expand",function(){poll();el.scrollTop=el.scrollHeight})}
 if(s.show_if!==undefined)bind(s.show_if,function(v){sh(el,!!v)});return el};
// ---- a read-only table of name / value pairs (the About rows); rows come from "@path" or the reply of "source" (fetched when Settings opens)
W.info=function(s){var el=h("table",{"class":"about"});
 function paint(rows){setHtml(el,(rows||[]).map(function(r){return '<tr><td class="n">'+esc(r[0])+'</td><td>'+esc(r[1])+'</td></tr>'}).join(""))}
 if(s.rows!==undefined)bind(s.rows,paint);
 if(s.source)hook("settingsOpen",function(){xhrJson("GET",s.source,function(r){if(r)paint(r)})});return el};
// ---- a module's own widget: its page.js registered custom(name, fn); fn(host, ctx) fills the empty element
W.custom=function(s,ctx){var host=h("div",{"class":"wcustom"+(s.cls?" "+s.cls:""),html:s.html||""}),f=CUSTOM[s.name];
 if(f)AFTER.push(function(){f(host,ctx)});          // after the layout is in the page, so the module may look its elements up by id
 else if(window.console)console.error("no custom widget",s.name);return host};
// ---- controls that make up a form: select, number, text, slider (bound to one key of the form's values)
function optionList(spec,F){var o=spec.options;if(typeof o==="string")o=isBind(o)?val(o):(F.options||{})[o];return o||[]}
function control(spec,F,change){var key=spec.key,el,paint;
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
  (f.controls||[]).forEach(function(c){var e=control(Object.assign({},c,{aria:(f.title||"")+": "+(c.label||c.key)}),F,save);ctls.push(e);
   pop.appendChild(h("div",{"class":"frow"},[h("span",{text:c.label||c.key}),e]))});
  pop.appendChild(h("div",{"class":"bar end"},[done]));
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
  row=h("div",{"class":"srow","data-picker":"modules"},[h("span",{},[document.createTextNode("Modules"),h("span",{"class":"sub",text:"Switch modules on or off and set their priority"})]),btn]);
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
// ---- connections (Settings > System > Connections > Edit): cables between modules' jacks (netswitch_bus.py).
// Every output and input is a simple on/off jack. An input is off until a cable from an output that is on (or another module, through
// the API) turns it on; "Inverted" makes a cable carry the opposite. An input's settings (knobs) belong to the input, not to a cable.
function buildWiring(cols){
 var card=cols.querySelector('[data-box="system"] .card');if(!card)return;
 var btn=h("button",{type:"button","class":"pill-s","aria-haspopup":"dialog","aria-label":"Edit the connections",text:"Edit"}),list=h("div",{"class":"wlinks"}),
  add=h("button",{type:"button","class":"pill-s",text:"Add cable"}),reset=h("button",{type:"button","class":"pill-s",text:"Restore standard"}),done=h("button",{type:"button","class":"pill-s",text:"Done"}),
  pop=h("div",{},[h("div",{"class":"t",text:"Connections: a cable carries “on” from an output of one module to an input of another. Inputs are off until something turns them on. A module works without any cable."}),list,h("div",{"class":"bar"},[add,reset,done])]),
  row=h("div",{"class":"srow","data-picker":"connections"},[h("span",{},[document.createTextNode("Connections"),h("span",{"class":"sub",text:"Cables from one module's outputs to another's inputs"})]),btn]),
  p=ui.popup(pop),state={outputs:[],inputs:[],links:[],defaults:[],knobs:{},levels:{outputs:{},inputs:{}}},timer=null;
 var first=card.querySelector('[data-picker="modules"]');card.insertBefore(row,first?first.nextSibling:card.firstChild);card.appendChild(pop);
 function find(items,id){for(var i=0;i<items.length;i++)if(items[i].id===id)return items[i];return null}
 function save(){clearTimeout(timer);timer=setTimeout(function(){post("/bus/links",{links:state.links,knobs:state.knobs},function(){})},300)}      // the rows keep their own objects: the server's cleaned copy is not put in their place
 function selectOf(items,value,onPick,label){var sel=h("select",{"class":"ord","aria-label":label}),groups={},order=[];
  if(value&&!find(items,value))items=items.concat([{id:value,module:"?",module_title:"Not loaded",label:value}]);
  items.forEach(function(it){if(!groups[it.module_title]){groups[it.module_title]=h("optgroup",{label:it.module_title});order.push(it.module_title);sel.appendChild(groups[it.module_title])}
   var o=h("option",{value:it.id,text:it.label});if(it.id===value)o.selected=true;groups[it.module_title].appendChild(o)});
  sel.onchange=function(){onPick(sel.value)};return sel}
 function knobsOf(id){var input=find(state.inputs,id);if(!input||!input.params.length)return null;
  var values=state.knobs[id]=state.knobs[id]||{};
  return input.params.map(function(q){var c,cur=values[q.key]===undefined?q.default:values[q.key];
   if(q.type==="select"){c=h("select",{"class":"ord","aria-label":q.label});q.options.forEach(function(o){var op=h("option",{value:o[0],text:o[1]});if(cur===o[0])op.selected=true;c.appendChild(op)});
    c.onchange=function(){values[q.key]=c.value;save()}}
   else{c=h("input",{type:q.type==="number"?"number":"text","class":"in","aria-label":q.label,value:cur===undefined?"":cur});
    c.onchange=function(){values[q.key]=q.type==="number"?parseFloat(c.value)||0:c.value;save()}}
   return h("div",{"class":"frow"},[h("span",{text:q.label}),c])})}
 function lamp(on){return h("span",{"class":"sub",text:on?"on now":"off now"})}
 function block(link){var b=h("div",{"class":"wlink"}),lv=state.levels||{outputs:{},inputs:{}};
  b.appendChild(h("div",{"class":"frow stack"},[h("span",{},[document.createTextNode("From (output) "),lamp(lv.outputs[link.from])]),selectOf(state.outputs,link.from,function(v){link.from=v;save();paint()},"From")]));
  b.appendChild(h("div",{"class":"frow stack"},[h("span",{},[document.createTextNode("To (input) "),lamp(lv.inputs[link.to])]),selectOf(state.inputs,link.to,function(v){link.to=v;save();paint()},"To")]));
  var inv=h("input",{type:"checkbox","aria-label":"Inverted: the input is on while the output is off"});inv.checked=!!link.invert;
  inv.onchange=function(){link.invert=inv.checked;save()};
  b.appendChild(h("label",{"class":"frow"},[h("span",{text:"Inverted (on while the output is off)"}),inv]));
  var kn=knobsOf(link.to);if(kn){b.appendChild(h("div",{"class":"sub",text:"Settings of this input"}));kn.forEach(function(k){b.appendChild(k)})}
  var rm=h("button",{type:"button","class":"pill-s danger",text:"Remove","aria-label":"Remove this cable"});
  rm.onclick=function(){state.links.splice(state.links.indexOf(link),1);save();paint()};
  b.appendChild(h("div",{"class":"bar end"},[rm]));return b}
 function paint(){list.innerHTML="";
  if(!state.links.length)list.appendChild(h("div",{"class":"sub",text:"No cables: every input stays off."}));
  state.links.forEach(function(l){list.appendChild(block(l))})}
 add.onclick=function(){if(!state.outputs.length||!state.inputs.length){alert("There is nothing to connect: no loaded module has outputs and inputs.");return}
  state.links.push({from:state.outputs[0].id,to:state.inputs[0].id,invert:false});save();paint()};
 reset.onclick=function(){if(!confirm("Put the cables back as they were when the add-on was installed?"))return;
  post("/bus/reset",{},function(r){if(r){state=r;paint()}})};
 done.onclick=function(){p.close()};
 btn.onclick=function(e){e.stopPropagation();if(p.isOpen()){p.close();return}xhrJson("GET","/bus",function(r){if(!r)return;state=r;paint();p.open(btn)})};
 hook("settingsClose",function(){p.close()})}
// ---- backgrounds: the picker's top background module draws (a fullscreen one hides those below, a part one leaves them)
function startBackgrounds(){(LAY.backgrounds||[]).forEach(function(b){
 var host=h("div",{"class":"bgpart "+(b.type==="part"?"part "+(b.position||"bottom"):"fullscreen"),"data-bg":b.mod});$("bg").appendChild(host);
 if(BACKGROUNDS[b.mod])BACKGROUNDS[b.mod](host,b)})}
var BACKGROUNDS={};
function background(mod,fn){BACKGROUNDS[mod]=fn}

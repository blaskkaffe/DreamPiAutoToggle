// Optional "Online players" box. Self-contained: it adds a button like the Debug log one (it
// opens a panel with the list and links), a show/hide checkbox to Settings, and its own styles,
// and talks only to GET /players. To drop the feature delete this file and netswitch_players.py
// (the page builds without them).
(function(){
 var anchor=document.getElementById("debug-bar"),dbg=document.getElementById("dbg-b");
 if(!anchor||!anchor.parentNode)return;
 var KEY="netswitch-players",EVERY=60000,RETRY=2000;
 function wanted(){try{return localStorage.getItem(KEY)!="off"}catch(e){return true}}
 var css=document.createElement("style");
 css.textContent=
  "#pl-box{margin:20px 0 0}#pl-box.off{display:none}#pl-box .bar{margin:0}#pl-box .pl-count{margin-left:8px;color:#999;font-size:.85em}"+
  "#pl-panel{display:none;margin-top:8px}#pl-panel.open{display:block}#pl-panel .card{padding:6px 16px}"+
  "#pl-rows{max-height:50vh;overflow-y:auto;overscroll-behavior:contain}"+
  "#pl-rows .p{display:flex;gap:10px;padding:9px 0;border-top:1px solid var(--line, #2a2a2a);font-size:.9em}#pl-rows .p:first-child{border-top:0}"+
  "#pl-rows .pn{flex:1;min-width:0;overflow-wrap:anywhere}#pl-rows .pg{display:block;color:#999;font-size:.9em;margin-top:2px}"+
  "#pl-rows .pw{flex:none;font-weight:bold;white-space:nowrap}.pl-net-dcnow{color:var(--dcnow-l)}.pl-net-dcnet{color:var(--dcnet-l)}"+
  "#pl-msg{color:#999;font-size:.85em;margin:8px 0}#pl-detail{color:#777;font-size:.78em;margin:8px 0 6px;overflow-wrap:anywhere}"+
  "#pl-links{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0}#pl-links a{text-decoration:none}";
 document.head.appendChild(css);
 var box=document.createElement("div");box.id="pl-box";
 box.innerHTML='<div class="bar"><button class="wide" id="pl-toggle" type="button" aria-expanded="false"><span>Online players<span class="pl-count" id="pl-count"></span></span><span class="arrow">&#9656;</span></button></div>'+
  '<div id="pl-panel"><div class="card"><div id="pl-msg"></div><div id="pl-rows"></div><div id="pl-detail"></div></div><div id="pl-links"></div></div>';
 anchor.parentNode.insertBefore(box,anchor);
 // setting: show or hide the box (this browser only), next to the debug log switch
 var srow=dbg&&dbg.closest?dbg.closest(".srow"):null;
 if(srow){var s=document.createElement("div");s.className="srow";
  s.innerHTML='<span>Online players<span class="sub">Show the online players box on the main page (this browser only)</span></span><input type="checkbox" class="cbox dcnow" id="pl-b" aria-label="Show online players">';
  srow.parentNode.insertBefore(s,srow.nextSibling)}
 var cb=document.getElementById("pl-b"),open=false,timer=null,again=EVERY;
 function esc(t){return String(t).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
 function netClass(n){return n=="DCNET"?"pl-net-dcnet":n=="DCNow!"?"pl-net-dcnow":""}
 function render(r){
  var msg=document.getElementById("pl-msg"),rows=document.getElementById("pl-rows");
  document.getElementById("pl-links").innerHTML=(r.links||[]).map(function(l){
   return '<a class="pill-s" href="'+esc(l[1])+'" target="_blank" rel="noopener noreferrer">'+esc(l[0])+'</a>'}).join("");
  if(!r.configured){msg.textContent="No player list source is set up. Add the JSON address of a status page to players_sources.json (see the README), or use the links below.";
   rows.innerHTML="";document.getElementById("pl-count").textContent="";return}
  if(!r.time){msg.textContent="Loading...";return}
  var players=r.players||[],bad=(r.sources||[]).filter(function(s){return !s.ok});
  document.getElementById("pl-count").textContent="("+players.length+")";
  msg.textContent=(players.length?"":"Nobody is listed as online right now. ")+bad.map(function(s){return s.name+": "+s.error}).join("; ");
  msg.style.display=msg.textContent?"block":"none";
  // what each source listed: "DC99: dreampi 3/340, dcnet 5" (shown/listed when some are offline)
  document.getElementById("pl-detail").textContent=(r.sources||[]).filter(function(s){return s.ok}).map(function(s){
   return s.name+": "+(s.sections&&s.sections.length?s.sections.map(function(x){
    return x.section+" "+x.shown+(x.listed!=x.shown?"/"+x.listed:"")+(x.offline?" (offline)":"")}).join(", "):s.count)}).join("  ·  ");
  rows.innerHTML=players.map(function(p){
   return '<div class="p"><span class="pn">'+esc(p.player)+'<span class="pg">'+esc(p.game||"(Idle)")+'</span></span><span class="pw '+netClass(p.network)+'">'+esc(p.network||"")+'</span></div>'}).join("")}
 function active(){return open&&wanted()}
 function load(){clearTimeout(timer);if(!active())return;
  var x=new XMLHttpRequest();x.open("GET","/players",true);
  function next(){clearTimeout(timer);if(active())timer=setTimeout(load,again)}
  x.onload=function(){again=EVERY;if(x.status==200){try{var r=JSON.parse(x.responseText);render(r);if(r.configured&&(!r.time||r.refreshing))again=RETRY}catch(e){}}next()};
  x.onerror=function(){again=EVERY;next()};x.send()}
 function setOpen(o){open=o;document.getElementById("pl-panel").classList.toggle("open",o);
  var t=document.getElementById("pl-toggle");t.classList.toggle("open",o);t.setAttribute("aria-expanded",o);
  if(o)load();else clearTimeout(timer)}
 function apply(){var on=wanted();box.classList.toggle("off",!on);if(cb)cb.checked=on;if(!on&&open)setOpen(false)}
 document.getElementById("pl-toggle").onclick=function(){setOpen(!open)};
 if(cb)cb.onchange=function(){try{localStorage.setItem(KEY,this.checked?"on":"off")}catch(e){}apply()};
 apply();
})();

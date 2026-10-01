// Optional "Online players" list for the main page. Self-contained: it adds its own
// button, panel and styles, and talks only to GET /players. To drop the feature
// delete this file and netswitch_players.py (the page builds without them).
(function(){
 var anchor=document.getElementById("debug-bar");
 if(!anchor||!anchor.parentNode)return;
 var css=document.createElement("style");
 css.textContent=
  "#pl-box{margin:12px 0 0}#pl-box .pl-count{margin-left:8px;color:#999;font-size:.85em}"+
  "#pl-panel{display:none;margin-top:8px}#pl-panel.open{display:block}"+
  "#pl-table{width:100%;border-collapse:collapse;font-size:.85em}#pl-table th{color:#999;font-weight:normal;font-size:.8em;text-align:left;padding:4px 6px 6px}"+
  "#pl-table td{padding:7px 6px;border-top:1px solid #2a2a2a;vertical-align:top;overflow-wrap:anywhere}"+
  "#pl-table td.pl-net{white-space:nowrap}"+
  ".pl-net-dcnow{color:var(--dcnow-l)}.pl-net-dcnet{color:var(--dcnet-l)}"+
  "#pl-msg{color:#999;font-size:.85em;margin:6px 4px}"+
  "#pl-links{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0 0}#pl-links a{text-decoration:none}";
 document.head.appendChild(css);
 var box=document.createElement("div");box.id="pl-box";
 box.innerHTML='<div class="bar" style="margin:0"><button class="wide" id="pl-toggle" type="button" aria-expanded="false"><span>Online players<span class="pl-count" id="pl-count"></span></span><span class="arrow">&#9656;</span></button></div>'+
  '<div id="pl-panel"><div class="card" style="padding:10px 14px"><div id="pl-msg"></div>'+
  '<table id="pl-table" style="display:none"><thead><tr><th>Player</th><th>Game</th><th>Network</th></tr></thead><tbody id="pl-rows"></tbody></table></div>'+
  '<div id="pl-links"></div></div>';
 anchor.parentNode.insertBefore(box,anchor);
 var open=false,timer=null;
 function esc(s){return String(s).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
 function netClass(n){return n=="DCNET"?"pl-net-dcnet":n=="DCNow!"?"pl-net-dcnow":""}
 function render(r){
  var msg=document.getElementById("pl-msg"),table=document.getElementById("pl-table");
  document.getElementById("pl-links").innerHTML=(r.links||[]).map(function(l){
   return '<a class="pill-s" href="'+esc(l[1])+'" target="_blank" rel="noopener noreferrer">'+esc(l[0])+'</a>'}).join("");
  if(!r.configured){msg.textContent="No player list source is set up. Add the JSON address of a status page to players_sources.json (see the README), or use the links below.";
   table.style.display="none";document.getElementById("pl-count").textContent="";return}
  if(!r.time){msg.textContent="Loading...";table.style.display="none";return}
  var bad=(r.sources||[]).filter(function(s){return !s.ok});
  var players=r.players||[];
  document.getElementById("pl-count").textContent="("+players.length+")";
  msg.textContent=(players.length?"":"Nobody is listed as online right now. ")+
   (bad.length?bad.map(function(s){return s.name+": "+s.error}).join("; "):"");
  msg.style.display=msg.textContent?"block":"none";
  table.style.display=players.length?"table":"none";
  document.getElementById("pl-rows").innerHTML=players.map(function(p){
   return '<tr><td>'+esc(p.player)+'</td><td>'+esc(p.game||"")+'</td><td class="pl-net '+netClass(p.network)+'">'+esc(p.network||"")+'</td></tr>'}).join("")}
 function load(){var x=new XMLHttpRequest(),again=15000;x.open("GET","/players",true);
  function next(){clearTimeout(timer);if(open)timer=setTimeout(load,again)}
  x.onload=function(){if(x.status==200){try{var r=JSON.parse(x.responseText);render(r);if(r.configured&&(!r.time||r.refreshing))again=2000}catch(e){}}next()};
  x.onerror=next;x.send()}
 document.getElementById("pl-toggle").onclick=function(){open=!open;
  document.getElementById("pl-panel").classList.toggle("open",open);this.classList.toggle("open",open);this.setAttribute("aria-expanded",open);
  if(open)load();else clearTimeout(timer)};
})();

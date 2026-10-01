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
  "#pl-box{margin:0 0 14px;padding:14px 24px 10px;border-radius:var(--r);text-align:center;background:#9e4f10;border:var(--bw) solid #c9793a;line-height:1.35;cursor:pointer;user-select:none}#pl-box.dcnet{background:#1c4f9e;border-color:#5a86cf}#pl-box.off{display:none}"+
  "#pl-box .nlabel{display:block;margin:0 0 6px;padding:0 0 2px;font-size:1.08em;font-weight:600;color:rgba(255,255,255,.8);text-align:center;letter-spacing:.01em}"+
  "#pl-box .row{font-size:.62em;line-height:1.35;padding:9px 0;border-top:1px solid rgba(255,255,255,.18);text-align:left}#pl-box .row.main{justify-content:center;border-top:0;padding:8px 0 4px}#pl-box .row.main .k{display:none}#pl-box .row.main .v{width:100%;display:flex;align-items:center;justify-content:center;gap:14px;flex-wrap:wrap;font-size:1.25em}#pl-box .row .k{color:rgba(255,255,255,.65);width:90px;flex:none}#pl-box .row .v{min-width:0;display:flex;align-items:baseline;flex-wrap:wrap;gap:8px}#pl-box .more{display:none}#pl-box:not(.open) #pl-games-row{display:flex}#pl-box.open .more{display:flex}#pl-box .arrow{color:rgba(255,255,255,.7);font-size:.9em;transition:transform .15s;flex:none;margin-left:8px}#pl-box.open .arrow{transform:rotate(90deg)}"+
  "#pl-box .pl-net{display:inline-block;white-space:nowrap;font-size:1.25em;font-weight:700;color:inherit}#pl-box .pl-net-dcnow{color:var(--dcnow-l)}#pl-box .pl-net-dcnet{color:var(--dcnet-l)}"+
  "#pl-box #pl-games,#pl-box #pl-players,#pl-box #pl-msg,#pl-box #pl-links{display:block;white-space:normal;overflow-wrap:anywhere}#pl-box #pl-games{display:block;overflow:hidden;white-space:nowrap;width:100%;padding:2px 0}#pl-box .pl-games-track{display:inline-block;white-space:nowrap;padding-left:100%;animation:pl-scroll 16s linear infinite;will-change:transform}#pl-box #pl-links{display:flex;flex-wrap:wrap;gap:6px}#pl-box #pl-links a{text-decoration:none}#pl-box #pl-players{display:flex;flex-direction:column;gap:4px}#pl-box .pl-row{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1.4fr) auto;gap:8px;align-items:center;padding:5px 0;border-top:1px solid rgba(255,255,255,.12)}#pl-box .pl-row:first-child{border-top:0}#pl-box .pl-name{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600}#pl-box .pl-game{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;opacity:.82}#pl-box .pl-network{justify-self:end;white-space:nowrap;font-size:.78em;font-weight:700;letter-spacing:.04em;text-transform:uppercase}#pl-box .pl-network.dcnow{color:var(--dcnow-l)}#pl-box .pl-network.dcnet{color:var(--dcnet-l)}@keyframes pl-scroll{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}";
 document.head.appendChild(css);
 var box=document.createElement("div");box.id="pl-box";box.className="now rows";box.title="Show or hide details";box.setAttribute("role","button");box.setAttribute("tabindex","0");box.setAttribute("aria-expanded","false");
 box.innerHTML='<div class="nlabel">Online players:</div>'+ 
  '<div class="row main" id="pl-toggle" aria-expanded="false">'+
   '<span class="k">Players</span><span class="v"><span class="pl-net pl-net-dcnow">DCNow!: <span id="pl-dcnow-count">0</span></span><span class="pl-net pl-net-dcnet">DCNET: <span id="pl-dcnet-count">0</span></span></span><span class="arrow">&#9656;</span></div>'+ 
  '<div class="row more" id="pl-games-row"><span class="k">Games</span><span class="v"><span id="pl-games">...</span></span></div>'+ 
  '<div class="row more" id="pl-players-row"><span class="k">Players</span><span class="v"><span id="pl-players">...</span></span></div>'+ 
  '<div class="row more" id="pl-msg-row"><span class="k">Status</span><span class="v"><span id="pl-msg"></span></span></div>'+ 
  '<div class="row more" id="pl-links-row"><span class="k">Links</span><span class="v"><span id="pl-links"></span></span></div>';
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
  var msg=document.getElementById("pl-msg"),games=document.getElementById("pl-games"),playersbox=document.getElementById("pl-players"),links=document.getElementById("pl-links");
  links.innerHTML=(r.links||[]).map(function(l){return '<a class="pill-s" href="'+esc(l[1])+'" target="_blank" rel="noopener noreferrer">'+esc(l[0])+'</a>'}).join("");
  var players=r.players||[];
  var dcnow=players.filter(function(p){return p.network=="DCNow!"}).length;
  var dcnet=players.filter(function(p){return p.network=="DCNET"}).length;
  document.getElementById("pl-dcnow-count").textContent=dcnow;
  document.getElementById("pl-dcnet-count").textContent=dcnet;
  if(!r.configured){msg.textContent="No player list source is set up. Add the JSON address of a status page to players_sources.json (see the README), or use the links below.";games.textContent="";playersbox.textContent="";return}
  if(!r.time){msg.textContent="Loading...";games.textContent="";playersbox.textContent="";return}
  var bad=(r.sources||[]).filter(function(s){return !s.ok});
  msg.textContent=bad.map(function(s){return s.name+": "+s.error}).join("; ");
  if(players.length){
   var seen={};
   var gameNames=[];
   players.forEach(function(p){
    if(!p.game)return;
    if(!seen[p.game]){seen[p.game]=0}
    seen[p.game]+=1;
   });
   Object.keys(seen).forEach(function(name){
    gameNames.push({name:name,count:seen[name]});
   });
   if(gameNames.length){
    var gamesText=gameNames.slice(0,12).map(function(g){return g.name+(g.count>1?" ("+g.count+")":"");}).join(" • ");
    var scrollText=gamesText.length>36?gamesText+" • "+gamesText:"";
    games.innerHTML=scrollText?'<span class="pl-games-track">'+esc(scrollText)+'</span>':esc(gamesText);
   }else{
    games.textContent="Nobody is listed as online right now.";
   }
   playersbox.innerHTML=players.map(function(p){
    var net=(p.network||"DCNow!")=='DCNET'?'dcnet':'dcnow';
    return '<div class="pl-row"><span class="pl-name">'+esc(p.player||'Unknown')+'</span><span class="pl-game">'+esc(p.game||'—')+'</span><span class="pl-network '+net+'">'+esc(p.network||'DCNow!')+'</span></div>';
   }).join("");
  }else{
   games.textContent="Nobody is listed as online right now.";
   playersbox.textContent="Nobody is listed as online right now.";
  }
  msg.style.display=msg.textContent?"block":"none";
 }
 function active(){return open&&wanted()}
 function load(){clearTimeout(timer);if(!active())return;
  var x=new XMLHttpRequest();x.open("GET","/players",true);
  function next(){clearTimeout(timer);if(active())timer=setTimeout(load,again)}
  x.onload=function(){again=EVERY;if(x.status==200){try{var r=JSON.parse(x.responseText);render(r);if(r.configured&&(!r.time||r.refreshing))again=RETRY}catch(e){}}next()};
  x.onerror=function(){again=EVERY;next()};x.send()}
 function setOpen(o){open=o;box.classList.toggle("open",o);box.setAttribute("aria-expanded",o);var toggle=document.getElementById("pl-toggle");if(toggle)toggle.setAttribute("aria-expanded",o);if(o)load();else clearTimeout(timer)}
 function apply(){var on=wanted();box.classList.toggle("off",!on);if(cb)cb.checked=on;if(!on&&open)setOpen(false)}
 box.onclick=function(e){if(e&&e.target&&e.target.closest&&e.target.closest("a"))return;setOpen(!open)};
 box.onkeydown=function(e){if(e.key=="Enter"||e.key==" "){e.preventDefault();setOpen(!open)}};
 if(cb)cb.onchange=function(){try{localStorage.setItem(KEY,this.checked?"on":"off")}catch(e){}apply()};
 apply();
})();

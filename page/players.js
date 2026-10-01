// Optional "Online players" list. Self-contained: it adds its rows to the Selected-network box
// (shown when the box is opened), a show/hide checkbox to Settings, and its own styles, and talks
// only to GET /players. To drop the feature delete this file and netswitch_players.py (the page
// builds without them).
(function(){
 var net=document.getElementById("net"),hang=document.getElementById("hang-row"),dbg=document.getElementById("dbg-b");
 if(!net||!hang)return;
 var KEY="netswitch-players",EVERY=60000,RETRY=2000;
 function wanted(){try{return localStorage.getItem(KEY)!="off"}catch(e){return true}}
 var css=document.createElement("style");
 css.textContent=
  "#net.pl-off .pl-r{display:none!important}"+
  ".now.open .pl-list{display:block;max-height:34vh;overflow-y:auto;overscroll-behavior:contain;padding:4px 0}"+
  ".now .pl-list .p{display:flex;gap:8px;padding:5px 0;border-top:1px solid rgba(255,255,255,.12)}.now .pl-list .p:first-child{border-top:0}"+
  ".now .pl-list .pn{flex:1;min-width:0;overflow-wrap:anywhere}.now .pl-list .pg{display:block;color:rgba(255,255,255,.65)}"+
  ".now .pl-list .pw{flex:none;font-weight:bold;white-space:nowrap}"+
  ".now .pl-links{flex-wrap:wrap;gap:0 14px}.now .pl-links a{color:#fff;opacity:.85;display:inline-block;padding:9px 0;min-height:24px;box-sizing:border-box}"+
  ".now .pl-detail{display:block;color:rgba(255,255,255,.55);overflow-wrap:anywhere;margin-top:3px}";
 document.head.appendChild(css);
 function row(cls,html){var d=document.createElement("div");d.className="row more pl-r "+cls;d.innerHTML=html;hang.parentNode.insertBefore(d,hang);return d}
 row("pl-head","<span class=\"k\">Players</span><span class=\"v\"><span><span class=\"nw\" id=\"pl-count\">...</span><span class=\"sub blk\" id=\"pl-msg\"></span></span></span>");
 row("pl-list keep","<div id=\"pl-rows\"></div>")
 var links=row("pl-links keep","");
 var list=document.getElementById("pl-rows").parentNode;
 // setting: show or hide the list (this browser only), next to the debug log switch
 var srow=dbg&&dbg.closest?dbg.closest(".srow"):null;
 if(srow){var s=document.createElement("div");s.className="srow";
  s.innerHTML='<span>Online players<span class="sub">Show who is online in the network box on the main page (this browser only)</span></span><input type="checkbox" class="cbox dcnow" id="pl-b" aria-label="Show online players">';
  srow.parentNode.insertBefore(s,srow.nextSibling)}
 var cb=document.getElementById("pl-b"),timer=null,again=EVERY;
 function esc(t){return String(t).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
 function render(r){
  var msg=document.getElementById("pl-msg"),cnt=document.getElementById("pl-count");
  links.innerHTML=(r.links||[]).map(function(l){return '<a href="'+esc(l[1])+'" target="_blank" rel="noopener noreferrer">'+esc(l[0])+'</a>'}).join("");
  if(!r.configured){cnt.textContent="No source set up";msg.textContent="Add a status page to players_sources.json (see the README).";document.getElementById("pl-rows").innerHTML="";return}
  if(!r.time){cnt.textContent="Loading...";msg.textContent="";return}
  var players=r.players||[],bad=(r.sources||[]).filter(function(s){return !s.ok});
  cnt.textContent=players.length?players.length+" online":"Nobody online";
  // what each source listed: "DC99: dreampi 3/340, dcnet 5" (shown/listed when some are offline)
  var detail=(r.sources||[]).filter(function(s){return s.ok}).map(function(s){
   return s.name+": "+(s.sections&&s.sections.length?s.sections.map(function(x){
    return x.section+" "+x.shown+(x.listed!=x.shown?"/"+x.listed:"")+(x.offline?" (offline)":"")}).join(", "):s.count)}).join("  ·  ");
  msg.innerHTML=esc(bad.map(function(s){return s.name+": "+s.error}).join("; "))+(detail?'<span class="sub pl-detail">'+esc(detail)+'</span>':"");
  document.getElementById("pl-rows").innerHTML=players.map(function(p){
   return '<div class="p"><span class="pn">'+esc(p.player)+'<span class="pg">'+esc(p.game||"(Idle)")+'</span></span><span class="pw">'+esc(p.network||"")+'</span></div>'}).join("")}
 function visible(){return wanted()&&net.classList.contains("open")}
 function load(){clearTimeout(timer);if(!visible())return;
  var x=new XMLHttpRequest();x.open("GET","/players",true);
  function next(){clearTimeout(timer);if(visible())timer=setTimeout(load,again)}
  x.onload=function(){again=EVERY;if(x.status==200){try{var r=JSON.parse(x.responseText);render(r);if(r.configured&&(!r.time||r.refreshing))again=RETRY}catch(e){}}next()};
  x.onerror=function(){again=EVERY;next()};x.send()}
 function apply(){net.classList.toggle("pl-off",!wanted());if(cb)cb.checked=wanted();load()}
 if(cb)cb.onchange=function(){try{localStorage.setItem(KEY,this.checked?"on":"off")}catch(e){}apply()};
 // poll only while the box is open (and the list is switched on)
 var was=net.classList.contains("open");
 new MutationObserver(function(){var o=net.classList.contains("open");if(o!=was){was=o;if(o)load();else clearTimeout(timer)}}).observe(net,{attributes:true,attributeFilter:["class"]});
 apply();
})();

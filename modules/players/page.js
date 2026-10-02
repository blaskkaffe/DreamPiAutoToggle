// Online players module, page side: a box with the same markup and classes as the Selected-network box (so it looks
// exactly like it and follows the same colours; its extra styles are in page.css). Always shown while the module is on.
// Talks only to GET /players.
(function(){
 var slot=document.getElementById("main-slot"),net=document.getElementById("net");
 if(!slot)return;
 var EVERY=60000,RETRY=2000;
 var box=document.createElement("div");box.id="pl-box";box.className="now rows";box.title="Show or hide details";
 box.setAttribute("role","button");box.setAttribute("tabindex","0");box.setAttribute("aria-expanded","false");
 box.innerHTML='<div class="nlabel">Online players:</div>'+
  '<b id="pl-counts"><span class="pln dcnow">DCNow! <span id="pl-dcnow-count">-</span></span><span class="pln dcnet">DCNET <span id="pl-dcnet-count">-</span></span></b>'+
  '<div class="row main" id="pl-toggle"><span class="k">Games</span><span class="v"><span class="mq" id="pl-games"></span></span><span class="arrow">&#9656;</span></div>'+
  '<div class="row more"><span class="k">Players</span><span class="v"><span class="list keep" id="pl-players"></span></span></div>'+
  '<div class="row more" id="pl-status-row"><span class="k">Status</span><span class="v"><span class="st" id="pl-msg"></span></span></div>'+
  '<div class="row more"><span class="k">Links</span><span class="v"><span class="links keep" id="pl-links"></span></span></div>';
 var after=document.getElementById("debug-bar");
 slot.insertBefore(box,after&&after.parentNode===slot?after:null);   // above the debug log bar when there is one
 // the same colour as the network box (which follows the selected network)
 function syncColour(){box.classList.toggle("dcnet",!!(net&&net.classList.contains("dcnet")))}
 if(net){syncColour();new MutationObserver(syncColour).observe(net,{attributes:true,attributeFilter:["class"]})}
 var open=false,timer=null,again=EVERY,gamesText="";
 function esc(t){return String(t).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]})}
 // "Game (3) • Other game (1)", most played first
 function gamesLine(players){
  var n={},order=[];
  players.forEach(function(p){if(!p.game)return;if(!n[p.game]){n[p.game]=0;order.push(p.game)}n[p.game]++});
  order.sort(function(a,b){return n[b]-n[a]});
  return order.map(function(g){return g+" ("+n[g]+")"}).join("  •  ");
 }
 // Scroll the games line only when it doesn't fit. The line is two identical halves (text + separator) in one track that
// slides left by exactly one half and starts over, so it loops without a gap, like a carousel. A resize that changes
// nothing must not restart it, so the class is only touched when the answer changes.
 function fitGames(){
  var mq=document.getElementById("pl-games"),t=mq.querySelector(".t"),scroll=false;
  if(t&&!open&&gamesText){
   var row=document.getElementById("pl-toggle"),arrow=row.querySelector(".arrow");
   scroll=t.offsetWidth>row.clientWidth-arrow.offsetWidth-12;
  }
  if(scroll!==box.classList.contains("sc")){
   box.classList.toggle("sc",scroll);
   if(scroll)mq.style.setProperty("--d",Math.max(12,Math.round(gamesText.length*0.28))+"s");
  }
 }
 function setGames(text){
  if(text===gamesText&&document.getElementById("pl-games").firstChild){return}
  gamesText=text;
  var mq=document.getElementById("pl-games");
  var half='<span class="t">'+esc(text)+'<span class="sp">\u00a0\u00a0\u2022\u00a0\u00a0</span></span>';
  mq.innerHTML=text?'<span class="trk">'+half+half.replace('class="t"','class="t dup" aria-hidden="true"')+'</span>':"";
  box.classList.remove("sc");fitGames();
 }
 var lastKey="";
 function render(r){
  var key=JSON.stringify([r.configured,r.time,r.players,r.sources,r.links]);   // not "refreshing": the same answer changes nothing on screen
  if(key===lastKey)return;lastKey=key;
  var msg=document.getElementById("pl-msg"),list=document.getElementById("pl-players");
  document.getElementById("pl-links").innerHTML=(r.links||[]).map(function(l){return '<a href="'+esc(l[1])+'" target="_blank" rel="noopener noreferrer">'+esc(l[0])+'</a>'}).join("");
  var players=r.players||[],bad=(r.sources||[]).filter(function(s){return !s.ok});
  if(!r.configured){
   document.getElementById("pl-dcnow-count").textContent=document.getElementById("pl-dcnet-count").textContent="-";
   setGames("No player list source is set up");list.textContent="";
   msg.textContent="Add the JSON address of a status page to players_sources.json (see the README), or use the links.";return}
  if(!r.time){setGames("Loading...");return}
  document.getElementById("pl-dcnow-count").textContent=players.filter(function(p){return p.network=="DCNow!"}).length;
  document.getElementById("pl-dcnet-count").textContent=players.filter(function(p){return p.network=="DCNET"}).length;
  setGames(gamesLine(players)||(players.length?"Nobody is in a game":"Nobody is online"));
  list.innerHTML=players.length?players.map(function(p){
   return '<span class="p"><span class="pn">'+esc(p.player)+'<span class="pg">'+esc(p.game||"(Idle)")+'</span></span><span class="pw '+
    (p.network=="DCNET"?"dcnet":p.network=="DCNow!"?"dcnow":"")+'">'+esc(p.network||"")+'</span></span>'}).join(""):"Nobody is online";
  // what each source listed: "DC99: dreampi 3/340, dcnet 5" (shown/listed when some are offline), and any errors
  var detail=(r.sources||[]).filter(function(s){return s.ok}).map(function(s){
   return s.name+": "+(s.sections&&s.sections.length?s.sections.map(function(x){
    return x.section+" "+x.shown+(x.listed!=x.shown?"/"+x.listed:"")+(x.offline?" (offline)":"")}).join(", "):s.count)}).join("  ·  ");
  msg.textContent=bad.map(function(s){return s.name+": "+s.error}).join("; ")+(bad.length&&detail?"  ·  ":"")+detail;
 }
 function active(){return !document.hidden}   // the games line is on screen even when the box is closed
 function load(){clearTimeout(timer);if(!active())return;
  var x=new XMLHttpRequest();x.open("GET","/players",true);
  function next(){clearTimeout(timer);if(active())timer=setTimeout(load,again)}
  x.onload=function(){again=EVERY;if(x.status==200){try{var r=JSON.parse(x.responseText);render(r);if(r.configured&&(!r.time||r.refreshing))again=RETRY}catch(e){}}next()};
  x.onerror=function(){again=EVERY;next()};x.send()}
 // fetched whenever the page is on screen (the closed box shows the games), at most once a minute
 function setOpen(o){open=o;box.classList.toggle("open",o);box.setAttribute("aria-expanded",o);fitGames()}
 box.onclick=function(e){if(e&&e.target&&e.target.closest&&e.target.closest("a,.keep"))return;setOpen(!open)};
 box.onkeydown=function(e){if((e.key=="Enter"||e.key==" ")&&e.target===box){e.preventDefault();setOpen(!open)}};
 window.addEventListener("resize",fitGames);
 document.addEventListener("visibilitychange",function(){if(!document.hidden)load()});
 load();
})();

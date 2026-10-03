// Reboot and Update module, page side: the Updates rows at the end of the System card and the Reboot card below it
// (markup in page.html). Uses the base page's xhrJson() and withPin() (the PIN is asked for before an update or a reboot).
// Updates: GET /update (cached GitHub check), POST /update/check, POST /update/start (runs git pull + the installer on the Pi).
var updTimer=null;
function loadUpdate(){xhrJson("GET","/update",function(r){if(r)renderUpdate(r);else if(updRunning)$("upd-text").textContent="Restarting the services..."})}
var updRunning=false,updWatched=false;   // updWatched: this page started or saw the update, so it reloads once when it is done
// The update log as a small console: one line per row, errors red, success green, nothing wider than the card.
function renderUpdLog(r){
 var lg=$("upd-log"),lines=r.log||[];
 lg.style.display=(lines.length&&r.state!="idle")?"block":"none";
 var stick=lg.scrollTop+lg.clientHeight>=lg.scrollHeight-8;
 lg.innerHTML=lines.map(function(l,i){
  var c=/\b(fail|failed|error|fatal|denied|cannot|could not|not found)\b/i.test(l)?"l-err":
   /^(ok|done|updated|installed|.*\b(already up to date|fast-forward)\b)/i.test(l)?"l-ok":
   /^(updating|running)\b/i.test(l)?"l-hd":/^(from|remote:|\s*\d+ file|\s*create mode|\s*delete mode)/i.test(l)?"l-dim":"";
  return '<div'+(c?' class="'+c+'"':'')+'>'+esc(l.slice(0,300))+'</div>'}).join("");
 if(stick)lg.scrollTop=lg.scrollHeight}
function renderUpdate(r){var a=r.addon,d=r.dreampi,msg;
 updRunning=r.state=="running";if(updRunning)updWatched=true;
 if(r.state=="running")msg="Updating... the page is unavailable for a few seconds while the services restart.";
 else if(r.state=="ok")msg=updWatched?"Updated. Reloading...":"The add-on was updated a few minutes ago.";
 else if(r.state=="failed")msg="The update failed. Details below.";
 else if(r.checking)msg="Checking...";
 else if(!r.time)msg="Not checked yet";
 else if(r.error)msg=r.error;
 else if(a&&a.available)msg="A newer add-on version is available: "+a.latest+(a.latest_date?" ("+a.latest_date.slice(0,10)+")":"")+(a.behind?", "+a.behind+" new change"+(a.behind>1?"s":""):"")+". You have "+a.current+".";
 else if(a&&a.available===false)msg="The add-on is up to date ("+a.current+").";
 else msg=(a&&a.note)||"Couldn't tell if the add-on is current.";
 if(a&&a.note&&a.available!==null&&!updRunning&&r.state=="idle")msg+=" "+a.note;
 $("upd-text").textContent=msg;
 var dp=$("upd-dreampi");dp.style.display="none";
 if(d&&d.newer&&r.state=="idle"){dp.style.display="block";
  dp.textContent="DreamPi has newer scripts: "+d.files.filter(function(f){return f.newer}).map(function(f){return f.name+" "+f.current+" \u2192 "+f.latest}).join(", ")+
   (d.auto_updates?". It updates itself when the Pi restarts with internet.":". Automatic updates are off (/boot/noautoupdates.txt exists).")}
 var show=!!(a&&a.available&&r.can_update&&r.state=="idle");
 $("upd-do-row").style.display=show?"flex":"none";
 $("upd-do-sub").textContent="Fetches the new version from GitHub and installs it ("+(r.branch||"main")+" branch). Settings are kept.";
 $("upd-check").disabled=!!r.checking||updRunning;
 renderUpdLog(r);
 if(r.state=="ok"&&updWatched){updWatched=false;setTimeout(function(){location.reload()},3000)}
 clearTimeout(updTimer);
 if(r.state=="running"||r.checking)updTimer=setTimeout(loadUpdate,2000)}
$("upd-check").onclick=function(){$("upd-text").textContent="Checking...";xhrJson("POST","/update/check",function(r){if(r)renderUpdate(r.status);
 clearTimeout(updTimer);updTimer=setTimeout(loadUpdate,1500)})};
$("upd-do").onclick=function(){if(!confirm("Update the add-on now? It is fetched from GitHub and installed; this page is unavailable for a few seconds."))return;
 withPin(function(){
  updRunning=true;updWatched=true;$("upd-text").textContent="Starting the update...";
  xhrJson("POST","/update/start",function(r,st,body){
   if(st==401||st==429){updRunning=false;updWatched=false;$("upd-text").textContent=(body&&body.message)||"PIN refused";return}
   if(r&&r.message&&r.message!="Update started"){updRunning=false;updWatched=false;$("upd-text").textContent=r.message}
   clearTimeout(updTimer);updTimer=setTimeout(loadUpdate,2000)})})};
// Reboot the Pi: confirm, ask the server, then wait until the page answers again and reload it.
$("reboot-b").onclick=function(){
 var inCall=(window.lastDreampiState||"").indexOf("call")==0;
 if(!confirm((inCall?"A call is in progress and will be cut. ":"")+"Reboot the Raspberry Pi now? It is back in about a minute."))return;
 var b=this,sub=$("reboot-sub");
 withPin(function(){b.disabled=true;
 xhrJson("POST","/reboot",function(r,st,body){
  if(!r||!r.started){b.disabled=false;sub.textContent=(r&&r.message)||(body&&body.message)||"Could not reboot";return}
  sub.textContent="Rebooting... this page comes back by itself.";
  var down=false,tries=0;
  (function poll(){tries++;
   var x=new XMLHttpRequest();x.open("GET","/ping?"+Date.now(),true);x.timeout=3000;
   x.onload=function(){if(down||tries>60)location.reload();else setTimeout(poll,2000)};
   x.onerror=x.ontimeout=function(){down=true;setTimeout(poll,2000)};x.send()})()})})};
hook("settingsOpen",loadUpdate);

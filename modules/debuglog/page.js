// Debug log module, page side: the Debug log bar and live log on the main page, and the switch for showing them in Settings
// (kept per browser). Recording itself is switched in the panel; the module's Python side keeps the log file.
var logSize=0,debugOn=false,logBusy=false,debugOpen=false;
// Debug log menu: hidden unless switched on in settings, remembered per browser
function setDebugMenu(on){
 try{localStorage.setItem("netswitch-debug",on?"on":"off")}catch(e){}
 $("dbg-b").checked=on;$("debug-bar").style.display=on?"flex":"none";
 if(!on){debugOpen=false;$("debug").style.display="none";$("show-debug").classList.remove("open")}}
$("dbg-b").onchange=function(){setDebugMenu(this.checked)};
$("show-debug").onclick=function(){debugOpen=!debugOpen;
 $("debug").style.display=debugOpen?"block":"none";
 this.classList.toggle("open",debugOpen);
 if(debugOpen){pollLog();var el=$("log");el.scrollTop=el.scrollHeight}};
setDebugMenu((function(){try{return localStorage.getItem("netswitch-debug")==="on"}catch(e){return false}})());
function cls(line){
 if(/modem: DTMF/.test(line))return"dtmf";
 if(/netswitch:|add-on:/.test(line))return"route";
 if(/web page:/.test(line))return"web";
 if(/underrun/.test(line))return"dim";
 if(/fail|error|Couldn't|Unable|No carrier|NO CARRIER/i.test(line))return"err";
 if(/modem/.test(line))return"modem";
 return"";
}
function pollLog(){
 if(!debugOpen||logBusy||(!debugOn&&logSize))return; logBusy=true;
 var x=new XMLHttpRequest();x.open("GET","/log?from="+logSize,true);
 x.onload=function(){logBusy=false;if(x.status!=200)return;var r=JSON.parse(x.responseText);
  var el=$("log");if(r.reset)el.innerHTML="";
  if(r.text){var html=r.text.split(/\r?\n/).filter(function(l){return l.length}).map(function(l){
    return '<div class="'+cls(l)+'">'+esc(l)+'</div>'}).join("");
   el.insertAdjacentHTML("beforeend",html);
   if($("follow").checked)el.scrollTop=el.scrollHeight;}
  logSize=r.size;};
 x.onerror=function(){logBusy=false};x.send();
}
hook("api",function(d){
 $("debug-b").innerHTML=(d.debug?"&#9679; Recording":"Recording off");
 $("log-tools").style.display=d.debug?"inline":"none";
 $("log").style.display=(d.debug||logSize)?"block":"none";
 debugOn=d.debug});
hook("posted",pollLog);
pollLog(); setInterval(pollLog,700);

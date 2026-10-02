// Status LED settings: the optional LED module's part of the page (page/led.html has its markup, page/led.css its
// styles). The page builder adds all three, with netswitch_led*.py's GET/POST /ledconfig on the server, only when the
// module's files are present; page.js calls the hooks at the bottom when they exist. Runs in the same script as page.js.
var led=null,ledDefaults=null,ledTimer=null,ledStates=[],ledGroups=[],ledEffects=[],ledCount=1,ledGpio=18;
var wbPreviewOn=false,wbHeartbeat=null;
var ledInstalled=false,ledHiddenFlag=false;
function ledGpioRow(){$("gpio-led-row").style.display=ledInstalled&&!ledHiddenFlag?"flex":"none"}   // called by updateGpioSection() in page.js
function loadLed(){var x=new XMLHttpRequest();x.open("GET","/ledconfig",true);
 x.onload=function(){if(x.status!=200)return;var r=JSON.parse(x.responseText);
  led=r.config;ledDefaults=r.defaults;ledStates=r.states;ledGroups=r.groups;ledEffects=r.effects;ledCount=r.count||1;ledGpio=r.gpio||18;
  $("led-section").style.display=(r.installed&&!r.hidden)?"block":"none";   // install.sh --led, not hidden
  ledInstalled=r.installed;ledHiddenFlag=r.hidden;updateGpioSection();
  $("led-count-t").textContent=ledCount>1?" ("+ledCount+" LEDs)":"";
  if(!$("led-order").options.length)$("led-order").innerHTML=r.orders.map(function(o){
   return '<option value="'+o+'">'+o+'</option>'}).join("");
  if(!$("led-gpio").options.length)$("led-gpio").innerHTML=r.gpios.map(function(g){
   return '<option value="'+g+'">GPIO'+g+'</option>'}).join("");
  $("led-count-i").value=ledCount;$("led-gpio").value=ledGpio;$("led-order").value=led.order;
  buildLed()};x.send()}
// Every message is one row of led.messages[key]: on/off, colour, effect + speed, level, LEDs.
function msgOf(st){return led.messages[st]}
function shortLabel(l){return l.split(" \u2014 ")[0]}   // the group heading already says DCNow! / DCNET / Netlink
function buildLed(){
 var html="";
 ledGroups.forEach(function(g){
  var items=ledStates.filter(function(s){return s[2]==g[0]});if(!items.length)return;
  var net=g[0].indexOf("call-")==0&&ledDefaults.messages[g[0]]?ledDefaults.messages[g[0]].color:"";
  html+='<tr class="grp"><td colspan="4">'+(net?'<span class="gdot" style="background:'+net+'"></span>':"")+esc(g[1])+'</td></tr>';
  items.forEach(function(s){var st=s[0];
   html+='<tr id="r-'+st+'"><td class="name"><input type="checkbox" class="cbox neutral" id="e-'+st+'" title="Show this message" aria-label="Show '+esc(s[1])+'"><span class="lbl-t">'+esc(shortLabel(s[1]))+
   (s[7]===false?'<small class="nd">not detected yet</small>':"")+'</span></td>'+
   '<td class="c"><input type="color" id="c-'+st+'" data-state="'+st+'" aria-label="Colour: '+esc(s[1])+'"></td>'+
   '<td class="c"><button type="button" class="chip fx" id="f-'+st+'" data-state="'+st+'" data-label="'+esc(s[1])+'" aria-label="Effect: '+esc(s[1])+'"></button></td>'+
   '<td class="c"><button type="button" class="chip lvl" id="l-'+st+'" data-state="'+st+'" data-label="'+esc(s[1])+'" aria-label="Level: '+esc(s[1])+'"></button></td></tr>'})});
 $("led-rows").innerHTML=html;
 ledStates.forEach(function(s){var st=s[0];
  $("c-"+st).addEventListener("input",function(){msgOf(st).color=this.value;showFx(st);saveLed()});
  $("e-"+st).onchange=function(){msgOf(st).enabled=this.checked;showRow(st);saveLed()};
  $("f-"+st).onclick=function(e){e.stopPropagation();openFx(this)};
  $("l-"+st).onclick=function(e){e.stopPropagation();openLvl(this)}});
 showLed()}
function effectName(e){for(var i=0;i<ledEffects.length;i++)if(ledEffects[i][0]==e)return ledEffects[i][1];return e}
function showLed(){$("led-bright").value=brightToSlider(led.max_brightness);$("led-bright-v").textContent=pct(led.max_brightness);
 $("led-order").value=led.order;
 showWb();
 ledStates.forEach(function(s){var st=s[0],c=msgOf(st);
  $("c-"+st).value=c.color;$("e-"+st).checked=c.enabled!==false;showRow(st);showFx(st);showLvl(st)})}
function showWb(){["r","g","b"].forEach(function(c){var v=Math.round(led.white_balance[c]*255);
 $("wb-"+c).value=v;$("wb-"+c+"-v").textContent=v})}
function showRow(st){$("r-"+st).className=msgOf(st).enabled===false?"dis":""}
function ledsText(L){return L[0]==L[1]?"LED "+L[0]:"LEDs "+L[0]+"-"+L[1]}
function showFx(st){var el=$("f-"+st);if(!el)return;var c=msgOf(st);
 var sub=[];if(c.effect!="solid")sub.push(c.speed);if(ledCount>1&&c.leds)sub.push(ledsText(c.leds));
 el.innerHTML=esc(effectName(c.effect))+(sub.length?"<small>"+sub.join(" \u00b7 ")+"</small>":"")}
function showLvl(st){var el=$("l-"+st);if(!el)return;var b=msgOf(st).brightness,own=b!==null&&b!==undefined;
 el.className="chip lvl"+(own?" on":"");el.textContent=pct(own?b:led.max_brightness)}
function placePop(pop,el){var box=pop.parentNode.getBoundingClientRect(),r=el.getBoundingClientRect();
 pop.classList.add("open");
 pop.style.left=Math.min(Math.max(r.right-box.left-pop.offsetWidth,0),box.width-pop.offsetWidth)+"px";
 pop.style.top=(r.bottom-box.top+6)+"px"}
var lvlCur=null,fxCur=null;
function closePops(){$("lvl-pop").classList.remove("open");$("fx-pop").classList.remove("open");
 lvlCur=fxCur=null}
var secMode="all";   // what the LEDs buttons of the open effect popup show: all | one | range
function openFx(el){closePops();var st=el.dataset.state,c=msgOf(st);fxCur=st;
 $("fx-t").textContent=el.dataset.label;
 $("fx-opts").innerHTML=ledEffects.filter(function(e){return !e[2]||ledCount>1||e[0]==c.effect}).map(function(e){
  return '<button type="button" class="pill-s" data-fx="'+e[0]+'">'+esc(e[1])+'</button>'}).join("");
 Array.prototype.forEach.call($("fx-opts").querySelectorAll("button"),function(b){b.onclick=function(){c.effect=b.dataset.fx;fxMark();saveLed()}});
 $("fx-sec").style.display=$("fx-sec-in").style.display=ledCount>1?"flex":"none";
 $("sec-a").max=$("sec-b").max=ledCount;
 secMode=!c.leds?"all":c.leds[0]==c.leds[1]?"one":"range";
 fxMark();placePop($("fx-pop"),el)}
function fxMark(){if(!fxCur)return;var c=msgOf(fxCur),fixed=c.effect=="solid";
 Array.prototype.forEach.call($("fx-opts").querySelectorAll("button"),function(b){b.className="pill-s"+(b.dataset.fx==c.effect?" sel":"")});
 Array.prototype.forEach.call($("fx-speed").querySelectorAll("button"),function(b){b.disabled=fixed;
  b.className="pill-s"+(!fixed&&b.dataset.speed==c.speed?" sel":"")});
 var L=c.leds;
 $("sec-all").className="pill-s"+(secMode=="all"?" sel":"");$("sec-one").className="pill-s"+(secMode=="one"?" sel":"");$("sec-range").className="pill-s"+(secMode=="range"?" sel":"");
 $("fx-sec-in").style.display=(ledCount>1&&secMode!="all")?"flex":"none";
 $("sec-b").style.display=$("sec-to").style.display=secMode=="range"?"":"none";
 $("sec-a").setAttribute("aria-label",secMode=="range"?"First LED":"LED");
 $("sec-a").value=L?L[0]:"";$("sec-b").value=L?L[1]:"";$("sec-a").placeholder="1";$("sec-b").placeholder=ledCount;
 showFx(fxCur)}
function setLeds(first,last){if(!fxCur)return;
 first=Math.max(1,Math.min(ledCount,first));last=Math.max(first,Math.min(ledCount,last));
 msgOf(fxCur).leds=[first,last];fxMark();saveLed()}
$("sec-all").onclick=function(){if(!fxCur)return;secMode="all";msgOf(fxCur).leds=null;fxMark();saveLed()};
$("sec-one").onclick=function(){if(!fxCur)return;var L=msgOf(fxCur).leds;secMode="one";setLeds(L?L[0]:1,L?L[0]:1)};
$("sec-range").onclick=function(){if(!fxCur)return;var L=msgOf(fxCur).leds;secMode="range";
 var a=L?L[0]:1,b=L&&L[1]>L[0]?L[1]:Math.min(ledCount,a+1);setLeds(a,b)};
function secInput(){if(!fxCur)return;var a=parseInt($("sec-a").value,10),b=parseInt($("sec-b").value,10);
 if(isNaN(a)&&isNaN(b))return;if(isNaN(a))a=1;if(isNaN(b))b=ledCount;
 if(secMode=="one")b=a;
 setLeds(Math.min(a,b),Math.max(a,b))}
$("sec-a").onchange=$("sec-b").onchange=secInput;
Array.prototype.forEach.call($("fx-speed").querySelectorAll("button"),function(b){b.onclick=function(){
 if(!fxCur)return;msgOf(fxCur).speed=b.dataset.speed;fxMark();saveLed()}});
$("fx-done").onclick=closePops;
function openLvl(el){closePops();var st=el.dataset.state,c=msgOf(st);
 if(c.brightness===null||c.brightness===undefined){c.brightness=led.max_brightness;showLvl(st);saveLed()}
 lvlCur=st;
 $("lvl-t").textContent=el.dataset.label;
 $("lvl-r").style.accentColor=c.color;$("lvl-r").value=brightToSlider(c.brightness);$("lvl-v").textContent=pct(c.brightness);
 placePop($("lvl-pop"),el)}
$("lvl-r").oninput=function(){if(!lvlCur)return;var b=Math.round(sliderToBright(this.value)*1000)/1000;
 msgOf(lvlCur).brightness=b;$("lvl-v").textContent=pct(b);showLvl(lvlCur);saveLed()};
$("lvl-base").onclick=function(){if(!lvlCur)return;msgOf(lvlCur).brightness=null;showLvl(lvlCur);saveLed();closePops()};
$("lvl-done").onclick=closePops;
$("lvl-pop").onclick=$("fx-pop").onclick=function(e){e.stopPropagation()};
$("settings").addEventListener("click",function(){if(lvlCur||fxCur)closePops()});
["r","g","b"].forEach(function(c){$("wb-"+c).oninput=function(){
 led.white_balance[c]=Math.round(this.value)/255;$("wb-"+c+"-v").textContent=Math.round(this.value);saveLed()}});
function setWbPreview(on){wbPreviewOn=on;$("wb-preview").classList.toggle("on",on);
 $("wb-preview").textContent=on?"Stop preview":"Preview on LED";
 clearInterval(wbHeartbeat);
 var x=new XMLHttpRequest();x.open("POST",on?"/wbtest":"/wbtestdone",true);x.setRequestHeader("X-Requested-With","netswitch");x.send();
 if(on)wbHeartbeat=setInterval(function(){
  var h=new XMLHttpRequest();h.open("POST","/wbtest",true);h.setRequestHeader("X-Requested-With","netswitch");h.send()},1000)}
$("wb-preview").onclick=function(){setWbPreview(!wbPreviewOn)};
$("wb-reset").onclick=function(){led.white_balance={r:1,g:1,b:1};showWb();saveLed()};
function saveLed(){clearTimeout(ledTimer);ledTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/ledconfig",true);x.setRequestHeader("Content-Type","application/json");
 led.count=ledCount;led.gpio=ledGpio;
 x.onload=function(){if(x.status!=200)return;var els=document.querySelectorAll(".led-saved");Array.prototype.forEach.call(els,function(e){e.classList.add("show")});
  setTimeout(function(){Array.prototype.forEach.call(els,function(e){e.classList.remove("show")})},1200);refresh()};x.send(JSON.stringify(led))},250)}
// Logarithmic slider: the left half covers 0-9 %, where an indicator LED is most useful.
var LOG_BASE=100;
function sliderToBright(p){return (Math.pow(LOG_BASE,p/1000)-1)/(LOG_BASE-1)}
function brightToSlider(b){return Math.round(1000*Math.log(1+b*(LOG_BASE-1))/Math.log(LOG_BASE))}
function pct(b){var v=b*100;return (v<10&&v>0?v.toFixed(1):Math.round(v))+"%"}
$("led-bright").oninput=function(){led.max_brightness=Math.round(sliderToBright(this.value)*1000)/1000;$("led-bright-v").textContent=pct(led.max_brightness);
 ledStates.forEach(function(s){showLvl(s[0])});saveLed()};
$("led-reset").onclick=function(){var order=led.order,wb=led.white_balance;   // wiring facts, not a look to reset
 led=JSON.parse(JSON.stringify(ledDefaults));led.order=order;led.white_balance=wb;showLed();saveLed()};
$("led-count-i").onchange=function(){var n=parseInt(this.value,10);
 if(isNaN(n))return;ledCount=Math.max(1,Math.min(300,n));this.value=ledCount;
 $("led-count-t").textContent=ledCount>1?" ("+ledCount+" LEDs)":"";saveLed()};
$("led-gpio").onchange=function(){ledGpio=parseInt(this.value,10);saveLed()};
$("led-order").onchange=function(){led.order=this.value;saveLed()};
$("led-hide-b").onclick=function(){
 if(!confirm("Hide the Status LED settings? This can only be undone on the Pi itself, by deleting led_hidden in /opt/dreampi-netswitch."))return;
 var x=new XMLHttpRequest();x.open("POST","/ledhide",true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=function(){$("led-section").style.display="none";ledHiddenFlag=true;updateGpioSection()};x.send()};

// hooks called by page.js
function ledOpen(){loadLed()}                                             // Settings opened
function ledClose(){closePops();if(wbPreviewOn)setWbPreview(false)}      // Settings closed
function ledEscape(){if(lvlCur||fxCur){closePops();return true}return false}   // Escape closes an open pop-up first

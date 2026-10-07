// Status LED module, page side: the custom widget "led-tools" (layout.json; markup of the calibration pop-up in messages.html): the
// Calibration row (white balance and the global level, with a preview on the LED) and the Colours row (how each palette colour looks on screen
// and on the LED). The colour rows themselves are the standard "triggers" widget over /ledrows. Rows, buttons and pop-ups are the page's
// standard ones (editRow, footRow, ui.popup).
custom("led-tools",function(host,ctx){
var cfg=null,timer=null,wbOn=false,wbBeat=null;
var calRow=editRow({title:"Calibration",button:"Adjust"});
calRow.setSub("White balance and maximum brightness");
var calPop=document.getElementById("cal-pop");
host.insertBefore(calRow.el,calPop);
var pCal=ui.popup(calPop);
pCal.onclose=function(){stopHold()};                              // the white test ends with the pop-up
// ---- loading and saving (the calibration only: the looks are saved by the rows)
function load(){xhrJson("GET","/ledconfig",function(r){if(!r)return;cfg=r.config;showCal()})}
function save(){clearTimeout(timer);timer=setTimeout(function(){
 post("/ledconfig",{max_brightness:cfg.max_brightness,white_balance:cfg.white_balance},function(r){if(r)ctx.saved();reloadTriggers("/ledrows")})},250)}
var LOG_BASE=100;
function sliderToBright(p){return (Math.pow(LOG_BASE,p/1000)-1)/(LOG_BASE-1)}
function brightToSlider(b){return Math.round(1000*Math.log(1+b*(LOG_BASE-1))/Math.log(LOG_BASE))}
function pct(b){var v=b*100;return (v<10&&v>0?String(parseFloat(v.toFixed(1))):Math.round(v))+"%"}
// ---- Calibration: white balance and the global level (a pop-up like the others)
function showCal(){["r","g","b"].forEach(function(c){var v=Math.round(cfg.white_balance[c]*255);$("wb-"+c).value=v;$("wb-"+c+"-v").textContent=v});
 $("led-bright").value=brightToSlider(cfg.max_brightness);$("led-bright-v").textContent=pct(cfg.max_brightness)}
calRow.btn.onclick=function(e){if(!pCal.isOpen())showCal();pCal.toggle(calRow.btn,e)};
$("cal-done").onclick=function(){pCal.close()};
["r","g","b"].forEach(function(c){$("wb-"+c).oninput=function(){cfg.white_balance[c]=Math.round(this.value)/255;$("wb-"+c+"-v").textContent=Math.round(this.value);save()}});
// "Preview on LED": the LED holds one solid colour (white for the white balance, or the colour being calibrated) while this is on;
// the page repeats the request every second, so a closed page stops it.
var holdColour="#ffffff";
function holdPost(){var q=new XMLHttpRequest();q.open("POST","/wbtest",true);q.setRequestHeader("X-Requested-With","netswitch");q.setRequestHeader("Content-Type","application/json");q.send(JSON.stringify({colour:holdColour}))}
function stopHold(){if(!wbOn)return;wbOn=false;clearInterval(wbBeat);var x=new XMLHttpRequest();x.open("POST","/wbtestdone",true);x.setRequestHeader("X-Requested-With","netswitch");x.send();
 $("wb-preview").classList.remove("on");$("wb-preview").textContent="Preview on LED";if(colPreview){colPreview.classList.remove("on");colPreview.textContent="Preview on LED"}}
function startHold(colour){holdColour=colour;if(wbOn){holdPost();return}wbOn=true;holdPost();wbBeat=setInterval(holdPost,1000)}
function setWb(on){if(on){startHold("#ffffff");$("wb-preview").classList.add("on");$("wb-preview").textContent="Stop preview"}else stopHold()}
$("wb-preview").onclick=function(){setWb(!wbOn)};
$("wb-reset").onclick=function(){cfg.white_balance={r:1,g:1,b:1};showCal();save()};
$("led-bright").oninput=function(){cfg.max_brightness=Math.round(sliderToBright(this.value)*1000)/1000;$("led-bright-v").textContent=pct(cfg.max_brightness);save()};
// ---- Colours: how the LED shows each palette colour (the LED's red need not be the page's red). How a colour looks on screen is set in the Colour palette module.
var colRow=editRow({title:"Colours",button:"Adjust",aria:"Adjust the colours"}),colPop=h("div",{"class":"gpop"}),pCol=ui.popup(colPop),colSel=null,colPreview=null,colChanged=false,colTimer=null,pal=[];
colRow.setSub("How the LED shows each colour");
host.appendChild(colRow.el);host.appendChild(colPop);
function colSave(body,after){post("/ledcolours",body,function(r){if(r&&r.colours){pal=r.colours;if(after)after()}})}
function openCol(btn,e){if(pCol.isOpen()){pCol.toggle(btn,e);return}
 xhrJson("GET","/ledcolours",function(r){if(!r)return;pal=r.colours;colChanged=false;fillCol();pCol.toggle(btn,e)})}
function fillCol(){colPop.innerHTML="";var cur=null;pal.forEach(function(c){if(c.id===colSel)cur=c});if(!cur&&pal.length){cur=pal[0];colSel=cur.id}
 colPop.appendChild(h("div",{"class":"t",text:"LED colours: the left half of a ball is how the colour looks on screen (set in Colour palette), the right half how it is sent to the LED"}));
 var grid=h("span",{"class":"swatches grid"});
 pal.forEach(function(c){
  var b=h("button",{type:"button","class":"swatch"+(c.id===colSel?" sel":""),style:"--c:linear-gradient(90deg,"+c.ui+" 50%,"+c.led+" 50%);--cl:"+mixWhite(c.ui),"aria-label":c.name});
  b.onclick=function(){colSel=c.id;stopHold();fillCol()};grid.appendChild(b)});
 colPop.appendChild(grid);
 if(!cur)return;
 if(cur.fixed){colPop.appendChild(h("div",{"class":"sub",text:cur.name+" is the colour of the selected network, DCNow! or DCNET: it follows the switch and has no value of its own (set the network colours in Appearance)."}));
  var d0=h("button",{type:"button","class":"pill-s",text:"Done"});d0.onclick=function(){pCol.close()};colPop.appendChild(h("div",{"class":"bar end"},[d0]));return}
 var ledWell=colourWell(cur.led,cur.name+" on the LED",function(v){cur.led=v;colChanged=true;if(wbOn&&colPreview.classList.contains("on"))startHold(cur.led);
   clearTimeout(colTimer);colTimer=setTimeout(function(){colSave({id:cur.id,led:cur.led})},250)}),
  changed=cur.led!==cur.led_default;
 colPreview=h("button",{type:"button","class":"pill-s fixw"+(wbOn&&holdColour===cur.led?" on":""),text:wbOn&&holdColour===cur.led?"Stop preview":"Preview on LED"});
 colPreview.onclick=function(){if(wbOn&&colPreview.classList.contains("on")){stopHold();return}startHold(cur.led);colPreview.classList.add("on");colPreview.textContent="Stop preview"};
 colPop.appendChild(h("div",{"class":"frow"},[h("span",{text:cur.name+" on the LED"}),h("span",{"class":"ctls"},[ledWell,colPreview])]));
 var reset=h("button",{type:"button","class":"pill-s",text:"Reset this colour"}),resetAll=h("button",{type:"button","class":"pill-s danger",text:"Reset all"}),done=h("button",{type:"button","class":"pill-s",text:"Done"});
 reset.disabled=!changed;
 reset.onclick=function(){stopHold();colChanged=true;colSave({reset:cur.id},fillCol)};
 resetAll.onclick=function(){if(!confirm("Put every colour back to the LED values the add-on shipped with?"))return;stopHold();colChanged=true;colSave({reset:"all"},fillCol)};
 done.onclick=function(){pCol.close()};
 colPop.appendChild(h("div",{"class":"bar"},[reset,resetAll,done]));
 colPop.appendChild(h("div",{"class":"sub",text:"The LED value is the colour asked for, before the white balance and the brightness. Use Preview on LED to see it."}))}
colRow.btn.onclick=function(e){openCol(colRow.btn,e)};
pCol.onclose=function(){stopHold();colChanged=false};
// ---- the page's hooks
hook("settingsOpen",load);
hook("settingsClose",function(){stopHold()});
});

// Status LED module, page side: the custom widget "led-groups" of the Status LED box (layout.json; markup of the calibration
// pop-up in messages.html, styles in page.css). It shows the colour groups: each row is one look (colour, effect, level, LEDs) with
// the messages that use it listed under it; Edit changes the look, Add puts more messages into the row, and new rows are added
// at the bottom. The rows, buttons, tags and pop-ups are the page's standard ones (editRow, footRow, ui.popup).
custom("led-groups",function(host,ctx){
var cfg=null,defaults=null,messages=[],cats=[],priority=[],colours={palette:[],tokens:[]},tokenUi={},effects=[],ledCount=1,timer=null;
var byKey={},rowOf={},wbOn=false,wbBeat=null;
var calRow=editRow({title:"Calibration",button:"Adjust"}),list=h("div",{"class":"after"}),
 addGroup=h("button",{type:"button","class":"pill-s",text:"Add colour"}),restore=h("button",{type:"button","class":"pill-s",text:"Restore defaults"}),
 foot=footRow([addGroup,restore]);
calRow.setSub("White balance and maximum brightness");
var calPop=document.getElementById("cal-pop");
host.insertBefore(calRow.el,calPop);host.insertBefore(list,calPop);host.insertBefore(foot.el,calPop);
var editPop=h("div",{"class":"gpop"}),addPop=h("div",{"class":"gpop"});host.appendChild(editPop);host.appendChild(addPop);
var pCal=ui.popup(calPop),pEdit=ui.popup(editPop),pAdd=ui.popup(addPop),editing=null,adding=null;
pEdit.onclose=function(){editing=null};pAdd.onclose=function(){adding=null};
pCal.onclose=function(){if(wbOn)setWb(false)};                              // the white test ends with the pop-up
// ---- loading and saving
function load(){xhrJson("GET","/ledconfig",function(r){if(!r)return;
 cfg=r.config;defaults=r.defaults;messages=r.messages;cats=r.categories;priority=r.priority;colours=r.colours;tokenUi=r.token_ui;effects=r.effects;ledCount=r.count||1;
 byKey={};messages.forEach(function(m){byKey[m.key]=m});
 paintAll();showCal()})}
function save(){clearTimeout(timer);timer=setTimeout(function(){
 post("/ledconfig",cfg,function(r){if(r)ctx.saved();refresh()})},250)}
// ---- the rows
function colourOf(g){for(var i=0;i<colours.palette.length;i++)if(colours.palette[i].id===g.colour)return colours.palette[i];
 for(var j=0;j<colours.tokens.length;j++)if(colours.tokens[j].id===g.colour)return {id:g.colour,name:colours.tokens[j].name,ui:tokenUi[g.colour]};
 return {id:g.colour,name:g.colour,ui:"#888"}}
function effectName(g){var n=g.effect;effects.forEach(function(e){if(e[0]===g.effect)n=e[1]});return g.effect==="solid"?n.toLowerCase():g.speed+" "+n.toLowerCase()}
function pct(b){var v=b*100;return (v<10&&v>0?String(parseFloat(v.toFixed(1))):Math.round(v))+"%"}
function ledsText(L){return L[0]===L[1]?"LED "+L[0]:"LEDs "+L[0]+"-"+L[1]}
function groupSub(g){var t=[g.brightness===null||g.brightness===undefined?"Global level "+pct(cfg.max_brightness):"Level "+pct(g.brightness)];
 if(ledCount>1&&g.leds)t.push(ledsText(g.leds));return t.join(" \u00b7 ")}
function paintRow(g,r){var c=colourOf(g);r.setTitle(c.name+", "+effectName(g));r.setDot(c.ui);r.setSub(groupSub(g));
 r.setList(g.messages.map(function(k){return byKey[k]?byKey[k].label:k}),function(i){g.messages.splice(i,1);paintAll();save()})}
function paintAll(){if(!cfg)return;list.innerHTML="";rowOf={};
 cfg.groups.forEach(function(g){var r=editRow({title:"",button:"Edit",button2:"Add",aria:"Edit this colour",aria2:"Add messages to this colour"});
  paintRow(g,r);rowOf[g.id]=r;
  r.btn.onclick=function(e){openEdit(g,r.btn,e)};r.btn2.onclick=function(e){openAdd(g,r.btn2,e)};list.appendChild(r.el)});
 sh(list,cfg.groups.length>0);
 addGroup.disabled=cfg.groups.length>=24;
 foot.setInfo(infoText());
 if(editing)fillEdit(editing);if(adding)fillAdd(adding)}
function infoText(){var order=priority.filter(function(k){return byKey[k]&&k!=="off"}).map(function(k){return byKey[k].label}).join(", ");
 return "Each row is a look: a colour, an animation (solid or blinking), a level and, on a strip, which LEDs. Add messages to a row to give them that look; a message can be in one row only, and a message in no row never lights the LEDs.\n"+
  "When several messages are true at once on the same LEDs, the most important one shows. Most important first: "+order+"."}
// ---- Edit: the look of one row
var LOG_BASE=100;
function sliderToBright(p){return (Math.pow(LOG_BASE,p/1000)-1)/(LOG_BASE-1)}
function brightToSlider(b){return Math.round(1000*Math.log(1+b*(LOG_BASE-1))/Math.log(LOG_BASE))}
function openEdit(g,btn,e){if(pEdit.isOpen()&&editing===g){pEdit.toggle(btn,e);return}editing=g;fillEdit(g);pEdit.toggle(btn,e)}
function seg(options,current,onPick,disabled){var box=h("span",{"class":"seg"});
 options.forEach(function(o){var b=h("button",{type:"button","class":"pill-s"+(o[0]===current?" sel":""),text:o[1]});b.disabled=!!disabled;b.onclick=function(){onPick(o[0])};box.appendChild(b)});return box}
function fillEdit(g){editPop.innerHTML="";var c=colourOf(g);
 editPop.appendChild(h("div",{"class":"t",text:"Colour, animation and level"}));
 // colour: the palette, then the colours that follow the networks
 var grid=h("span",{"class":"swatches grid"});
 colours.palette.filter(function(x){return x.id.indexOf("bright-")!==0}).concat(colours.palette.filter(function(x){return x.id.indexOf("bright-")===0})).forEach(function(x){
  var b=h("button",{type:"button","class":"swatch"+(g.colour===x.id?" sel":""),style:"--c:"+x.ui,"aria-label":x.name});
  b.onclick=function(){g.colour=x.id;paintAll();save()};grid.appendChild(b)});
 editPop.appendChild(h("div",{"class":"frow wrapcol"},[h("span",{text:"Colour: "+c.name}),grid]));
 editPop.appendChild(h("div",{"class":"frow"},[h("span",{text:"Or a network colour"}),
  seg(colours.tokens.map(function(t){return [t.id,t.name]}),g.colour,function(v){g.colour=v;paintAll();save()})]));
 editPop.appendChild(h("div",{"class":"frow"},[h("span",{text:"Animation"}),seg(effects.map(function(e){return [e[0],e[1]]}),g.effect,function(v){g.effect=v;paintAll();save()})]));
 editPop.appendChild(h("div",{"class":"frow"},[h("span",{text:"Speed"}),seg([["slow","Slow"],["fast","Fast"]],g.speed,function(v){g.speed=v;paintAll();save()},g.effect==="solid")]));
 var own=g.brightness!==null&&g.brightness!==undefined,val=h("span",{"class":"rv",text:pct(own?g.brightness:cfg.max_brightness)}),
  slider=h("input",{type:"range",min:0,max:1000,step:1,"aria-label":"Level"}),useGlobal=h("button",{type:"button","class":"pill-s",text:"Use global"});
 slider.value=brightToSlider(own?g.brightness:cfg.max_brightness);useGlobal.disabled=!own;
 slider.oninput=function(){g.brightness=Math.round(sliderToBright(slider.value)*1000)/1000;setText(val,pct(g.brightness));useGlobal.disabled=false;paintRow(g,rowOf[g.id]);save()};
 useGlobal.onclick=function(){g.brightness=null;paintAll();save()};
 editPop.appendChild(h("div",{"class":"frow"},[h("span",{text:"Level"}),h("span",{"class":"lvl"},[slider,val])]));
 editPop.appendChild(h("div",{"class":"frow"},[h("span",{"class":"sub",text:own?"Its own level":"Uses the global level from Calibration"}),useGlobal]));
 if(ledCount>1){   // a strip: which LEDs this look uses
  var mode=!g.leds?"all":g.leds[0]===g.leds[1]?"one":"range",a=h("input",{type:"number",min:1,max:ledCount,"aria-label":"First LED"}),b=h("input",{type:"number",min:1,max:ledCount,"aria-label":"Last LED"});
  function setL(x,y){x=Math.max(1,Math.min(ledCount,x));y=Math.max(x,Math.min(ledCount,y));g.leds=[x,y];paintAll();save()}
  var L=g.leds;a.value=L?L[0]:"";b.value=L?L[1]:"";
  a.onchange=b.onchange=function(){var x=parseInt(a.value,10),y=parseInt(b.value,10);if(isNaN(x))x=1;if(isNaN(y)||mode==="one")y=x;setL(Math.min(x,y),Math.max(x,y))};
  editPop.appendChild(h("div",{"class":"frow"},[h("span",{text:"LEDs"}),seg([["all","All"],["one","One"],["range","Range"]],mode,function(v){
   if(v==="all"){g.leds=null;paintAll();save()}else if(v==="one"){setL(g.leds?g.leds[0]:1,g.leds?g.leds[0]:1)}else{var s=g.leds?g.leds[0]:1;setL(s,g.leds&&g.leds[1]>s?g.leds[1]:Math.min(ledCount,s+1))}})]));
  if(mode!=="all")editPop.appendChild(h("div",{"class":"frow"},[h("span",{"class":"sub",text:mode==="one"?"LED number":"From and to"}),h("span",{"class":"ctls"},mode==="one"?[a]:[a,b])]))}
 var rm=h("button",{type:"button","class":"pill-s danger",text:"Remove"}),done=h("button",{type:"button","class":"pill-s",text:"Done"});
 rm.onclick=function(){var i=cfg.groups.indexOf(g);if(i>=0)cfg.groups.splice(i,1);pEdit.close();paintAll();save()};
 done.onclick=function(){pEdit.close()};
 editPop.appendChild(h("div",{"class":"bar"},[rm,done]))}
// ---- Add: pick messages for a row (only those that are in no row yet)
function openAdd(g,btn,e){if(pAdd.isOpen()&&adding===g){pAdd.toggle(btn,e);return}adding=g;fillAdd(g);pAdd.toggle(btn,e)}
function fillAdd(g){addPop.innerHTML="";var used={},box=h("div",{"class":"addlist"}),any=false;
 cfg.groups.forEach(function(x){x.messages.forEach(function(k){used[k]=true})});
 addPop.appendChild(h("div",{"class":"t",text:"Add messages to "+colourOf(g).name+", "+effectName(g)}));
 cats.forEach(function(cat){var free=messages.filter(function(m){return m.category===cat[0]&&!used[m.key]});if(!free.length)return;any=true;
  box.appendChild(h("div",{"class":"cathead",text:cat[1]}));
  free.forEach(function(m){var r=editRow({title:m.label,button:"Add",aria:"Add "+m.label});
   r.setSub(m.description+(m.detected?"":" (Not detected yet.)"));
   r.btn.onclick=function(){g.messages.push(m.key);paintAll();save()};box.appendChild(r.el)})});
 if(!any)box.appendChild(h("div",{"class":"sub",text:"Every message is in a row already."}));
 addPop.appendChild(box);
 var done=h("button",{type:"button","class":"pill-s",text:"Done"});done.onclick=function(){pAdd.close()};
 addPop.appendChild(h("div",{"class":"bar end"},[done]))}
// ---- the foot: a new row, back to the defaults
addGroup.onclick=function(){var used={};cfg.groups.forEach(function(g){used[g.colour]=true});
 var first=colours.palette.filter(function(c){return !used[c.id]&&c.id.indexOf("bright-")!==0})[0]||colours.palette[0];
 var g={id:"g"+Date.now().toString(36),colour:first.id,effect:"solid",speed:"slow",brightness:null,leds:null,messages:[]};
 cfg.groups.push(g);paintAll();save();var r=rowOf[g.id];if(r)openEdit(g,r.btn,{stopPropagation:function(){}})};
restore.onclick=function(){if(!confirm("Put the colour rows back as they were when the add-on was installed? Calibration is kept."))return;
 cfg.groups=JSON.parse(JSON.stringify(defaults.groups));pEdit.close();pAdd.close();paintAll();save()};
// ---- Calibration: white balance and the global level (a pop-up like the others)
function showCal(){["r","g","b"].forEach(function(c){var v=Math.round(cfg.white_balance[c]*255);$("wb-"+c).value=v;$("wb-"+c+"-v").textContent=v});
 $("led-bright").value=brightToSlider(cfg.max_brightness);$("led-bright-v").textContent=pct(cfg.max_brightness)}
calRow.btn.onclick=function(e){if(!pCal.isOpen())showCal();pCal.toggle(calRow.btn,e)};
$("cal-done").onclick=function(){pCal.close()};
["r","g","b"].forEach(function(c){$("wb-"+c).oninput=function(){cfg.white_balance[c]=Math.round(this.value)/255;$("wb-"+c+"-v").textContent=Math.round(this.value);save()}});
function setWb(on){wbOn=on;$("wb-preview").classList.toggle("on",on);$("wb-preview").textContent=on?"Stop preview":"Preview on LED";
 clearInterval(wbBeat);
 var x=new XMLHttpRequest();x.open("POST",on?"/wbtest":"/wbtestdone",true);x.setRequestHeader("X-Requested-With","netswitch");x.send();
 if(on)wbBeat=setInterval(function(){var q=new XMLHttpRequest();q.open("POST","/wbtest",true);q.setRequestHeader("X-Requested-With","netswitch");q.send()},1000)}
$("wb-preview").onclick=function(){setWb(!wbOn)};
$("wb-reset").onclick=function(){cfg.white_balance={r:1,g:1,b:1};showCal();save()};
$("led-bright").oninput=function(){cfg.max_brightness=Math.round(sliderToBright(this.value)*1000)/1000;$("led-bright-v").textContent=pct(cfg.max_brightness);paintAll();save()};
// ---- the page's hooks
hook("settingsOpen",load);
hook("settingsClose",function(){if(wbOn)setWb(false)});
hook("api",function(d){if(cfg&&d.led&&d.led.count&&d.led.count!==ledCount){ledCount=d.led.count;paintAll()}});
});

// Status LED module, page side: the custom widget "led-groups" of the Status LED box (layout.json; markup of the calibration
// pop-up in messages.html, styles in page.css). It shows the colour groups: each row is one look (colour, effect, level, LEDs) with
// the messages that use it listed under it; Edit changes the look, Add puts more messages into the row, and new rows are added
// at the bottom. The rows, buttons, tags and pop-ups are the page's standard ones (editRow, footRow, ui.popup).
custom("led-groups",function(host,ctx){
var cfg=null,defaults=null,messages=[],cats=[],colours={palette:[],tokens:[]},tokenUi={},effects=[],ledCount=1,timer=null;
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
pCal.onclose=function(){stopHold()};                              // the white test ends with the pop-up
// ---- loading and saving
function load(){xhrJson("GET","/ledconfig",function(r){if(!r)return;
 cfg=r.config;defaults=r.defaults;messages=r.messages;cats=r.categories;colours=r.colours;tokenUi=r.token_ui;effects=r.effects;ledCount=r.count||1;
 byKey={};messages.forEach(function(m){byKey[m.key]=m});
 paintAll();showCal()})}
function save(){clearTimeout(timer);timer=setTimeout(function(){
 post("/ledconfig",cfg,function(r){if(r)ctx.saved();refresh()})},250)}
// ---- the rows
function isToken(id){return id==="network"||colours.tokens.some(function(t){return t.id===id})}      // colours that follow the networks
function tokenColours(){return (S.led&&S.led.tokens)||tokenUi}      // the networks' colours as they are now (they follow the switch)
function colourOf(g){if(g.colour==="network"){var nw=tokenColours().network;return {id:"network",name:"Selected network",ui:nw.ui,ui_l:nw.ui_l}}
 for(var i=0;i<colours.palette.length;i++)if(colours.palette[i].id===g.colour)return colours.palette[i];
 for(var j=0;j<colours.tokens.length;j++)if(colours.tokens[j].id===g.colour){var tk=tokenColours()[g.colour];return {id:g.colour,name:colours.tokens[j].name,ui:tk.ui,ui_l:tk.ui_l}}
 return {id:g.colour,name:g.colour,ui:"#888888",ui_l:"#aaaaaa"}}
function effectName(g){var n=g.effect;effects.forEach(function(e){if(e[0]===g.effect)n=e[1]});return g.effect==="solid"?n.toLowerCase():g.speed+" "+n.toLowerCase()}
function pct(b){var v=b*100;return (v<10&&v>0?String(parseFloat(v.toFixed(1))):Math.round(v))+"%"}
function ledsText(L){return L[0]===L[1]?"LED "+L[0]:"LEDs "+L[0]+"-"+L[1]}
function groupSub(g){var t=[g.brightness===null||g.brightness===undefined?"Global level "+pct(cfg.max_brightness):"Level "+pct(g.brightness)];
 if(ledCount>1&&g.leds)t.push(ledsText(g.leds));return t.join(" \u00b7 ")}
function paintRow(g,r){var c=colourOf(g);r.setTitle(c.name+", "+effectName(g));r.setLook(c,g.effect,g.speed);r.setSub(groupSub(g));
 r.setList(g.messages.map(function(k){return byKey[k]?byKey[k].label:k}),function(i){g.messages.splice(i,1);paintAll();save()})}
function paintAll(){if(!cfg)return;list.innerHTML="";rowOf={};
 cfg.groups.forEach(function(g){var r=editRow({title:"",button:"Edit",button2:"Add",aria:"Edit this colour",aria2:"Add messages to this colour"});
  paintRow(g,r);rowOf[g.id]=r;
  r.btn.onclick=function(e){openEdit(g,r.btn,e)};r.btn2.onclick=function(e){openAdd(g,r.btn2,e)};list.appendChild(r.el)});
 sh(list,cfg.groups.length>0);
 addGroup.disabled=cfg.groups.length>=24;
 foot.setInfo(infoText());
 if(editing)fillEdit(editing);if(adding)fillAdd(adding)}
function infoText(){
 return "Each row is a look: a colour, an animation (solid or blinking), a level and, on a strip, which LEDs. Add messages to a row to give them that look; a message can be in one row only, and a message in no row never lights the LEDs.\n"+
  "When several messages are true at once on the same LEDs, the most important one shows. You set the order with Priority."}
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
 colours.palette.forEach(function(x){var ui=x.ui,ul=x.ui_l;
  if(x.id==="network"){var tk=tokenColours().network;ui=tk.ui;ul=tk.ui_l}      // Selected network: the ball shows the network's colour now
  var b=h("button",{type:"button","class":"swatch"+(g.colour===x.id?" sel":""),style:"--c:"+ui+";--cl:"+ul,"aria-label":x.name});
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
$("led-bright").oninput=function(){cfg.max_brightness=Math.round(sliderToBright(this.value)*1000)/1000;$("led-bright-v").textContent=pct(cfg.max_brightness);paintAll();save()};
// ---- Priority: which message wins when several are true (drag to put them in order, most important first)
var prioRow=editRow({title:"Priority",button:"Edit",aria:"Edit the message priority"}),prioPop=h("div",{"class":"gpop"}),pPrio=ui.popup(prioPop);
prioRow.setSub("Which message wins when several are true");
host.insertBefore(prioRow.el,list);host.appendChild(prioPop);
function fillPrio(){prioPop.innerHTML="";var used={},catName={},box=h("div",{"class":"mlist"});
 cfg.groups.forEach(function(g){g.messages.forEach(function(k){used[k]=true})});
 cats.forEach(function(c){catName[c[0]]=c[1]});
 prioPop.appendChild(h("div",{"class":"t",text:"Most important first. Drag the handle (or use the up and down arrow keys on it) to move a message. Dimmed messages are in no colour yet, so they do not light the LED."}));
 cfg.priority.forEach(function(k){var m=byKey[k];if(!m)return;
  var grip=h("button",{type:"button","class":"grip",title:"Drag to move (or use the up and down arrow keys)","aria-label":"Move "+m.label+": drag, or use the up and down arrow keys",html:"&#8942;&#8942;"}),
   left=h("span",{"class":used[k]?"":"prio-off"},[document.createTextNode(m.label),h("span",{"class":"sub",text:catName[m.category]||""})]);
  box.appendChild(h("div",{"class":"srow","data-id":k},[grip,left]))});
 prioPop.appendChild(box);
 sortable(box,function(order){cfg.priority=order;save()});
 var reset=h("button",{type:"button","class":"pill-s",text:"Restore default order"}),done=h("button",{type:"button","class":"pill-s",text:"Done"});
 reset.onclick=function(){cfg.priority=defaults.priority.slice();fillPrio();save()};
 done.onclick=function(){pPrio.close()};
 prioPop.appendChild(h("div",{"class":"bar"},[reset,done]))}
prioRow.btn.onclick=function(e){if(!pPrio.isOpen())fillPrio();pPrio.toggle(prioRow.btn,e)};
// ---- Colours: how each palette colour looks on screen and on the LED (the LED's red need not be the page's red)
var colRow=editRow({title:"Colours",button:"Adjust",aria:"Adjust the colours"}),colPop=h("div",{"class":"gpop"}),pCol=ui.popup(colPop),colSel=null,colPreview=null,colChanged=false,colTimer=null,pal=[];
colRow.setSub("How each colour looks on screen and on the LED");
host.insertBefore(colRow.el,list);host.appendChild(colPop);
function applyVars(c){applyPaletteVars(c);colours.palette.forEach(function(p){if(p.id===c.id){p.ui=c.ui;p.ui_l=mixWhite(c.ui)}})}      // the page follows at once (applyPaletteVars is the base's)
function colSave(body,after){post("/ledcolours",body,function(r){if(r&&r.colours){pal=r.colours;if(after)after()}})}
function openCol(btn,e){if(pCol.isOpen()){pCol.toggle(btn,e);return}
 xhrJson("GET","/ledcolours",function(r){if(!r)return;pal=r.colours;colChanged=false;fillCol();pCol.toggle(btn,e)})}
function fillCol(){colPop.innerHTML="";var cur=null;pal.forEach(function(c){if(c.id===colSel)cur=c});if(!cur&&pal.length){cur=pal[0];colSel=cur.id}
 colPop.appendChild(h("div",{"class":"t",text:"Colours: the left half of a ball is how it looks on screen, the right half how it is sent to the LED"}));
 var grid=h("span",{"class":"swatches grid"});
 pal.forEach(function(c){
  var b=h("button",{type:"button","class":"swatch"+(c.id===colSel?" sel":""),style:"--c:linear-gradient(90deg,"+c.ui+" 50%,"+c.led+" 50%);--cl:"+mixWhite(c.ui),"aria-label":c.name});
  b.onclick=function(){colSel=c.id;stopHold();fillCol()};grid.appendChild(b)});
 colPop.appendChild(grid);
 if(!cur)return;
 if(cur.fixed){colPop.appendChild(h("div",{"class":"sub",text:cur.name+" is the colour of the selected network, DCNow! or DCNET: it follows the switch and has no value of its own (set the network colours in Appearance)."}));
  var d0=h("button",{type:"button","class":"pill-s",text:"Done"});d0.onclick=function(){pCol.close()};colPop.appendChild(h("div",{"class":"bar end"},[d0]));return}
 var uiIn=h("input",{type:"color",value:cur.ui,"aria-label":cur.name+" on screen"}),ledIn=h("input",{type:"color",value:cur.led,"aria-label":cur.name+" on the LED"}),
  changed=cur.ui!==cur.ui_default||cur.led!==cur.led_default;
 colPreview=h("button",{type:"button","class":"pill-s"+(wbOn&&holdColour===cur.led?" on":""),text:wbOn&&holdColour===cur.led?"Stop preview":"Preview on LED"});
 uiIn.oninput=function(){cur.ui=uiIn.value;applyVars(cur);colChanged=true;clearTimeout(colTimer);colTimer=setTimeout(function(){colSave({id:cur.id,ui:cur.ui})},250)};
 ledIn.oninput=function(){cur.led=ledIn.value;colChanged=true;if(wbOn&&colPreview.classList.contains("on"))startHold(cur.led);
  clearTimeout(colTimer);colTimer=setTimeout(function(){colSave({id:cur.id,led:cur.led})},250)};
 colPreview.onclick=function(){if(wbOn&&colPreview.classList.contains("on")){stopHold();return}startHold(cur.led);colPreview.classList.add("on");colPreview.textContent="Stop preview"};
 colPop.appendChild(h("div",{"class":"frow"},[h("span",{text:cur.name+" on screen"}),uiIn]));
 colPop.appendChild(h("div",{"class":"frow"},[h("span",{text:cur.name+" on the LED"}),h("span",{"class":"ctls"},[ledIn,colPreview])]));
 var reset=h("button",{type:"button","class":"pill-s",text:"Reset this colour"}),resetAll=h("button",{type:"button","class":"pill-s danger",text:"Reset all"}),done=h("button",{type:"button","class":"pill-s",text:"Done"});
 reset.disabled=!changed;
 reset.onclick=function(){stopHold();colChanged=true;colSave({reset:cur.id},fillCol)};
 resetAll.onclick=function(){if(!confirm("Put every colour back to the values the add-on shipped with?"))return;stopHold();colChanged=true;colSave({reset:"all"},fillCol)};
 done.onclick=function(){pCol.close()};
 colPop.appendChild(h("div",{"class":"bar"},[reset,resetAll,done]));
 colPop.appendChild(h("div",{"class":"sub",text:"The LED value is the colour asked for, before the white balance and the brightness. Use Preview on LED to see it."}))}
colRow.btn.onclick=function(e){openCol(colRow.btn,e)};
pCol.onclose=function(){stopHold();if(colChanged){colChanged=false;reloadInSettings()}};
// ---- the page's hooks
hook("settingsOpen",load);
hook("settingsClose",function(){stopHold()});
hook("api",function(d){if(cfg&&d.led&&d.led.count&&d.led.count!==ledCount){ledCount=d.led.count;paintAll()}
 if(cfg)cfg.groups.forEach(function(g){var r=rowOf[g.id];if(r&&isToken(g.colour))r.setLook(colourOf(g),g.effect,g.speed)})});   // a row in a network's colour follows the switch
});

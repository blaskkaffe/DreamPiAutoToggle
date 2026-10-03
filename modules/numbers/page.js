// Phone numbers module, page side: Settings > Special phone numbers. Four lists (one per action) kept in numbers.json by the
// module; the hook matches what was dialed against their endings. Each block has an Add button that opens a pop-up.
var numCfg=null,numTimer=null;
function loadNumbers(){var x=new XMLHttpRequest();x.open("GET","/numbers",true);
 x.onload=function(){if(x.status!=200)return;numCfg=JSON.parse(x.responseText);renderNumbers()};x.send()}
function renderNumbers(){if(!numCfg)return;
 $("num-list").innerHTML=numCfg.actions.map(function(a){var list=numCfg.numbers[a.key]||[];
  return ui.row({title:a.label,sub:a.sub,control:ui.btn("Add",{"data-add":a.key,"aria-label":"Add a number to "+a.label}),
   below:'<div class="tags">'+(list.length?list.map(function(n,i){return ui.tag(n,{"data-key":a.key,"data-i":i})}).join(""):
    '<span class="empty">No number: this action is off</span>')+'</div>'})}).join("");
 Array.prototype.forEach.call($("num-list").querySelectorAll(".tag button"),function(b){b.onclick=function(){
  numCfg.numbers[b.dataset.key].splice(+b.dataset.i,1);saveNumbers()}});
 Array.prototype.forEach.call($("num-list").querySelectorAll("button[data-add]"),function(b){b.onclick=function(e){openAdd(b,e)}})}
// The Add pop-up: one for the whole block, placed under the Add button that opened it
var addKey=null,addPop=ui.popup($("num-pop"));
addPop.onclose=function(){addKey=null};
function openAdd(btn,e){var key=btn.dataset.add;
 if(addPop.isOpen()&&addKey==key){addPop.toggle(btn,e);return}
 addKey=key;var a=numCfg.actions.filter(function(x){return x.key==key})[0];
 $("num-pop-t").textContent="Add a number to "+a.label;$("num-in").value="";$("num-in").maxLength=numCfg.max;$("num-msg").textContent="";
 addPop.toggle(btn,e);$("num-in").focus()}
function addNumber(){var key=addKey;if(!key)return;var n=$("num-in").value.replace(/[^0-9*#]/g,""),say=function(t){$("num-msg").textContent=t};
 if(n.length<numCfg.min)return say("Needs at least "+numCfg.min+" digits, * or #");
 for(var i=0;i<numCfg.actions.length;i++){var a=numCfg.actions[i];
  if((numCfg.numbers[a.key]||[]).indexOf(n)>=0)return say(n+" is already used by "+a.label)}
 if(numCfg.numbers[key].length>=numCfg.per_action)return say("At most "+numCfg.per_action+" numbers");
 numCfg.numbers[key].push(n);addPop.close();saveNumbers()}
$("num-add").onclick=addNumber;
$("num-in").onkeydown=function(e){if(e.key=="Enter"){e.preventDefault();addNumber()}};
function saveNumbers(){clearTimeout(numTimer);numTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/numbers",true);x.setRequestHeader("Content-Type","application/json");
 x.onload=function(){if(x.status!=200)return;numCfg=JSON.parse(x.responseText);renderNumbers();var el=$("num-saved");el.classList.add("show");
  setTimeout(function(){el.classList.remove("show")},1200)};x.send(JSON.stringify(numCfg.numbers))},100)}
$("num-defaults").onclick=function(){if(!numCfg)return;numCfg.numbers=JSON.parse(JSON.stringify(numCfg.defaults));saveNumbers()};
hook("settingsOpen",loadNumbers);


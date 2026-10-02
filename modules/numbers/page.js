// Phone numbers module, page side: Settings > Phone numbers. Five lists (one per action) kept in numbers.json by the
// module; the hook matches what was dialed against their endings.
var numCfg=null,numTimer=null;
function loadNumbers(){var x=new XMLHttpRequest();x.open("GET","/numbers",true);
 x.onload=function(){if(x.status!=200)return;numCfg=JSON.parse(x.responseText);renderNumbers()};x.send()}
function renderNumbers(){if(!numCfg)return;
 $("num-list").innerHTML=numCfg.actions.map(function(a){var list=numCfg.numbers[a.key]||[];
  return '<div class="nrow" data-key="'+a.key+'"><b>'+esc(a.label)+'</b><span class="sub">'+esc(a.sub)+'</span>'+
   '<div class="nchips">'+(list.length?list.map(function(n,i){return '<span class="nchip">'+esc(n)+
    '<button type="button" data-key="'+a.key+'" data-i="'+i+'" aria-label="Remove '+esc(n)+'">&#10005;</button></span>'}).join(""):
    '<span class="nempty">No number: this action is off</span>')+'</div>'+
   '<div class="nadd"><input type="text" maxlength="'+numCfg.max+'" placeholder="Add a number" aria-label="Add a number for '+esc(a.label)+'" data-key="'+a.key+'">'+
   '<button type="button" class="pill-s" data-add="'+a.key+'">Add</button></div><div class="nmsg" data-msg="'+a.key+'"></div></div>'}).join("");
 Array.prototype.forEach.call($("num-list").querySelectorAll(".nchip button"),function(b){b.onclick=function(){
  numCfg.numbers[b.dataset.key].splice(+b.dataset.i,1);saveNumbers()}});
 Array.prototype.forEach.call($("num-list").querySelectorAll("button[data-add]"),function(b){b.onclick=function(){addNumber(b.dataset.add)}});
 Array.prototype.forEach.call($("num-list").querySelectorAll(".nadd input"),function(inp){inp.onkeydown=function(e){
  if(e.key=="Enter"){e.preventDefault();addNumber(inp.dataset.key)}}})}
function numMsg(key,text){var el=$("num-list").querySelector('[data-msg="'+key+'"]');if(el)el.textContent=text}
function addNumber(key){var inp=$("num-list").querySelector('.nadd input[data-key="'+key+'"]'),n=inp.value.replace(/[^0-9*#]/g,"");
 if(n.length<numCfg.min)return numMsg(key,"Needs at least "+numCfg.min+" digits, * or #");
 for(var i=0;i<numCfg.actions.length;i++){var a=numCfg.actions[i];
  if((numCfg.numbers[a.key]||[]).indexOf(n)>=0)return numMsg(key,n+" is already used by "+a.label)}
 if(numCfg.numbers[key].length>=numCfg.per_action)return numMsg(key,"At most "+numCfg.per_action+" numbers");
 numCfg.numbers[key].push(n);saveNumbers()}
function saveNumbers(){clearTimeout(numTimer);numTimer=setTimeout(function(){
 var x=new XMLHttpRequest();x.open("POST","/numbers",true);x.setRequestHeader("Content-Type","application/json");
 x.onload=function(){if(x.status!=200)return;numCfg=JSON.parse(x.responseText);renderNumbers();var el=$("num-saved");el.classList.add("show");
  setTimeout(function(){el.classList.remove("show")},1200)};x.send(JSON.stringify(numCfg.numbers))},100)}
$("num-defaults").onclick=function(){if(!numCfg)return;numCfg.numbers=JSON.parse(JSON.stringify(numCfg.defaults));saveNumbers()};
hook("settingsOpen",loadNumbers);


// The check-in module's one custom widget: the status menu editor (Settings > Statuses). A row with an Edit button opens the list in a pop-up (orderEditor() in
// page/widgets.js, like the Modules menu): tap a status to edit it (name, colour, the extra field it asks for, text before, start time, whether it checks the
// person out, whether it is sticky, dots), drag its handle to move it, Add status makes a new one.
// The whole list is POSTed to /checkin/statuses.
custom("checkin-statuses",function(host){var box=host.querySelector(".cstatuses"),modal=h("div",{"class":"rp-modal keep-visible",style:"display:none"}),key="",items=[],editing=-1;
 document.body.appendChild(modal);
 var NEEDS=[["","Nothing"],["time","A time"],["date","A date"],["datetime","A date and a time"],["note","A note (free text)"]];
 function colours(){return PAL()}
 function summary(s){var t=[];if(s.needs)t.push({time:"asks for a time",date:"asks for a date",datetime:"asks for a date and a time",note:"asks for a note"}[s.needs]);if(s.out)t.push("checks out");if(s.sticky)t.push("sticky");if(s.dots)t.push(s.dots+" dot"+(s.dots>1?"s":""));return t.map(function(x){return tr(x)}).join(" · ")}      // each part is translated, then joined
 function save(list,done){post("/checkin/statuses",{statuses:list},function(r,st,b){if(r&&r.ok){refresh();if(done)done(true,b)}else if(done)done(false,b)})}
 // the list is edited in a pop-up like the Modules menu: tap a status to change it, drag its handle to move it (the order is the order of the buttons in the status menu)
 var ed=orderEditor(box,{title:"Statuses",help:"Tap a status to change it, drag the handle to move it. The order is the order of the buttons in the status menu on the board.",
  sub:function(l){return l.length+" status"+(l.length===1?"":"es")},
  idOf:function(s){return s.code},item:function(s){return {id:s.code,title:s.label,sub:summary(s),colour:s.colour}},
  onEdit:function(s){edit(items.indexOf(s))},add:"Add status",onAdd:function(){edit(-1)},canAdd:function(l){return l.length<16},
  onOrder:function(ids){var by={};items.forEach(function(s){by[s.code]=s});save(ids.map(function(c){return by[c]}).filter(Boolean))}});
 function paint(list){items=list||[];ed.set(items)}
 function field(label,inner,id){return '<label class="rp-nl" data-row="'+id+'">'+label+inner+'</label>'}
 function edit(i){editing=i;var s=i>=0?items[i]:{label:"",colour:"blue",needs:"",out:false,sticky:false,dots:0,prefix:"",default:""};
  modal.innerHTML='<div class="rp-sheet rp-need2" role="dialog" aria-modal="true" aria-label="'+(i>=0?"Edit "+esc(s.label):"New status")+'"><button type="button" class="rp-x" data-close="1" title="Close" aria-label="Close">&#10005;</button>'+
   '<div class="rp-wn">'+(i>=0?esc(s.label):"New status")+'</div>'+
   field("Name",'<input class="rp-big" type="text" data-f="label" maxlength="30" value="'+esc(s.label)+'">',"label")+
   field("Colour",'<select class="rp-big" data-f="colour">'+colours().map(function(c){return '<option value="'+esc(c.id)+'"'+(c.id===s.colour?" selected":"")+'>'+esc(c.name)+'</option>'}).join("")+'</select>',"colour")+
   field("It asks for",'<select class="rp-big" data-f="needs">'+NEEDS.map(function(n){return '<option value="'+n[0]+'"'+(n[0]===s.needs?" selected":"")+'>'+n[1]+'</option>'}).join("")+'</select>',"needs")+
   field("Text before the value (for example: at, back, info:)",'<input class="rp-big" type="text" data-f="prefix" maxlength="20" value="'+esc(s.prefix||"")+'">',"prefix")+
   field("Start time in the pop-up (for example 07:30)",'<input class="rp-big" type="text" data-f="default" maxlength="5" value="'+esc(s.default||"")+'">',"default")+
   field("Dots next to the name",'<span class="optrow" role="group" aria-label="Dots next to the name" data-f="dots" data-v="'+(s.dots||0)+'">'+[0,1,2,3].map(function(n){return '<button type="button" class="pill-s'+(n===(s.dots||0)?" on":"")+'" data-dot="'+n+'" aria-pressed="'+(n===(s.dots||0))+'">'+(n?n:"None")+'</button>'}).join("")+'</span>',"dots")+
   '<label class="rp-nl rp-chk"><input type="checkbox" class="cbox neutral" data-f="out"'+(s.out?" checked":"")+'> Counts as out (the person is checked out)</label>'+
   '<label class="rp-nl rp-chk"><input type="checkbox" class="cbox neutral" data-f="sticky"'+(s.sticky?" checked":"")+'> Sticky: stays when INNE / UTE is pressed</label>'+
   '<div class="rp-cmsg sub" aria-live="polite"></div><div class="rp-nb rp-nb3">'+(i>=0?'<button type="button" class="pill-s danger rp-so" data-del="1">Delete</button>':'<span></span>')+'<button type="button" class="pill-s rp-so" data-close="1">Cancel</button><button type="button" class="pill-s pri rp-so c-green" data-save="1">Save</button></div></div>';
  trDom(modal);modal.style.display="";shows();var f0=modal.querySelector("input");if(f0&&f0.focus)f0.focus()}
 function shows(){var n=modal.querySelector('[data-f=needs]').value,pf=modal.querySelector('[data-f=prefix]'),dflt={time:"kl",date:"till",datetime:"till",note:"info:"};
  if(editing<0&&pf&&!pf._typed)pf.value=dflt[n]||"";      // a new status starts with the usual text before the value; what is typed (even nothing) is kept as it is
  sh(modal.querySelector('[data-row=prefix]'),!!n);sh(modal.querySelector('[data-row=default]'),n==="time")}
 function read(){var o={};Array.prototype.forEach.call(modal.querySelectorAll("[data-f]"),function(e){var k=e.getAttribute("data-f");o[k]=e.type==="checkbox"?e.checked:(k==="dots"?+e.getAttribute("data-v"):e.value)});return o}
 function close(){modal.style.display="none";modal.innerHTML="";editing=-1}
 modal.addEventListener("input",function(e){if(e.target.getAttribute&&e.target.getAttribute("data-f")==="prefix")e.target._typed=true});
 modal.addEventListener("change",function(e){if(e.target.getAttribute&&e.target.getAttribute("data-f")==="needs")shows()});
 modal.addEventListener("click",function(e){if(e.target===modal){close();return}var b=e.target.closest&&e.target.closest("button");if(!b)return;
  if(b.hasAttribute("data-dot")){var grp=b.parentNode;grp.setAttribute("data-v",b.getAttribute("data-dot"));Array.prototype.forEach.call(grp.querySelectorAll("button"),function(x){var on=x===b;x.classList.toggle("on",on);x.setAttribute("aria-pressed",on)});return}
  if(b.hasAttribute("data-close")){close();return}
  var msg=modal.querySelector(".rp-cmsg");
  if(b.hasAttribute("data-save")){var o=read();if(!o.label.trim()){setText(msg,"A status needs a name");return}
   var l=items.slice();if(editing>=0)l[editing]=Object.assign({},items[editing],o);else l.push(o);
   b.disabled=true;save(l,function(ok,x){b.disabled=false;if(ok)close();else setText(msg,(x&&x.message)||"That did not work")})}
  if(b.hasAttribute("data-del")){var name=items[editing].label;askConfirm("Delete the status "+name+"?","Delete",function(){var l=items.slice();l.splice(editing,1);save(l,function(ok,x){if(ok)close();else setText(modal.querySelector(".rp-cmsg"),(x&&x.message)||"That did not work")})})}});
 modal.addEventListener("keydown",function(e){if(e.key==="Enter"&&e.target.type==="text"){e.preventDefault();var b=modal.querySelector("[data-save]");if(b)b.click()}});
 hook("escape",function(){if(modal.style.display!=="none"){close();return true}});
 bind("@checkin.statuses",paint)});

// The check-in module's one custom widget: the status menu editor (Settings > Statuses). Each status is a row (tap it to edit: name, colour, the extra field it
// asks for, prefix, start time, whether it checks the person out, whether it is sticky, dots); the arrows move it, Add status makes a new one.
// The whole list is POSTed to /checkin/statuses.
custom("checkin-statuses",function(host){var box=host.querySelector(".cstatuses"),modal=h("div",{"class":"rp-modal keep-visible",style:"display:none"}),key="",items=[],editing=-1;
 document.body.appendChild(modal);
 var NEEDS=[["","Nothing"],["time","A time"],["date","A date"],["note","A note (free text)"]];
 function colours(){return PAL()}
 function summary(s){var t=[];if(s.needs)t.push({time:"asks for a time",date:"asks for a date",note:"asks for a note"}[s.needs]);if(s.out)t.push("checks out");if(s.sticky)t.push("sticky");if(s.dots)t.push(s.dots+" dot"+(s.dots>1?"s":""));return t.join(" · ")}
 function save(list,done){post("/checkin/statuses",{statuses:list},function(r,st,b){if(r&&r.ok){refresh();if(done)done(true,b)}else if(done)done(false,b)})}
 function paint(list){items=list||[];var k=JSON.stringify(items);if(k===key)return;key=k;box.innerHTML="";
  var add=h("button",{type:"button","class":"pill-s",text:"Add status"});add.onclick=function(){edit(-1)};sh(add,items.length<16);
  box.appendChild(h("div",{"class":"bar end"},[add]));
  items.forEach(function(s,i){var row=h("div",{"class":"srow rp-edit",title:"Edit "+s.label});
   var up=h("button",{type:"button","class":"pill-s",text:"▲","aria-label":"Move "+s.label+" up"}),dn=h("button",{type:"button","class":"pill-s",text:"▼","aria-label":"Move "+s.label+" down"});
   up.disabled=i===0;dn.disabled=i===items.length-1;
   function move(d){var l=items.slice(),t=l[i];l.splice(i,1);l.splice(i+d,0,t);save(l)}
   up.onclick=function(e){e.stopPropagation();move(-1)};dn.onclick=function(e){e.stopPropagation();move(1)};
   row.appendChild(h("span",{},[h("span",{"class":"dot c-"+s.colour+" rp-sw"}),document.createTextNode(s.label),h("div",{"class":"sub",text:summary(s)})]));
   row.appendChild(h("span",{"class":"ctls"},[up,dn]));
   row.addEventListener("click",function(e){if(e.target.closest&&e.target.closest("button"))return;edit(i)});box.appendChild(row)})}
 function field(label,inner,id){return '<label class="rp-nl" data-row="'+id+'">'+label+inner+'</label>'}
 function edit(i){editing=i;var s=i>=0?items[i]:{label:"",colour:"blue",needs:"",out:false,sticky:false,dots:0,prefix:"",default:""};
  modal.innerHTML='<div class="rp-sheet rp-need2" role="dialog" aria-modal="true" aria-label="'+(i>=0?"Edit "+esc(s.label):"New status")+'"><button type="button" class="rp-x" data-close="1" title="Close" aria-label="Close">&#10005;</button>'+
   '<div class="rp-wn">'+(i>=0?esc(s.label):"New status")+'</div>'+
   field("Name",'<input class="rp-big" type="text" data-f="label" maxlength="30" value="'+esc(s.label)+'">',"label")+
   field("Colour",'<select class="rp-big" data-f="colour">'+colours().map(function(c){return '<option value="'+esc(c.id)+'"'+(c.id===s.colour?" selected":"")+'>'+esc(c.name)+'</option>'}).join("")+'</select>',"colour")+
   field("It asks for",'<select class="rp-big" data-f="needs">'+NEEDS.map(function(n){return '<option value="'+n[0]+'"'+(n[0]===s.needs?" selected":"")+'>'+n[1]+'</option>'}).join("")+'</select>',"needs")+
   field("Text before the date (for example: back)",'<input class="rp-big" type="text" data-f="prefix" maxlength="20" value="'+esc(s.prefix||"")+'">',"prefix")+
   field("Start time in the pop-up (for example 07:30)",'<input class="rp-big" type="text" data-f="default" maxlength="5" value="'+esc(s.default||"")+'">',"default")+
   field("Dots next to the name",'<select class="rp-big" data-f="dots">'+[0,1,2,3].map(function(n){return '<option value="'+n+'"'+(n===(s.dots||0)?" selected":"")+'>'+(n?n:"None")+'</option>'}).join("")+'</select>',"dots")+
   '<label class="rp-nl rp-chk"><input type="checkbox" class="cbox neutral" data-f="out"'+(s.out?" checked":"")+'> Counts as out (the person is checked out)</label>'+
   '<label class="rp-nl rp-chk"><input type="checkbox" class="cbox neutral" data-f="sticky"'+(s.sticky?" checked":"")+'> Sticky: stays when INNE / UTE is pressed</label>'+
   '<div class="rp-cmsg sub" aria-live="polite"></div><div class="rp-nb rp-nb3">'+(i>=0?'<button type="button" class="pill-s danger rp-so" data-del="1">Delete</button>':'<span></span>')+'<button type="button" class="pill-s rp-so" data-close="1">Cancel</button><button type="button" class="pill-s pri rp-so c-green" data-save="1">Save</button></div></div>';
  modal.style.display="";shows();var f0=modal.querySelector("input");if(f0&&f0.focus)f0.focus()}
 function shows(){var n=modal.querySelector('[data-f=needs]').value;
  sh(modal.querySelector('[data-row=prefix]'),n==="date");sh(modal.querySelector('[data-row=default]'),n==="time")}
 function read(){var o={};Array.prototype.forEach.call(modal.querySelectorAll("[data-f]"),function(e){var k=e.getAttribute("data-f");o[k]=e.type==="checkbox"?e.checked:(k==="dots"?+e.value:e.value)});return o}
 function close(){modal.style.display="none";modal.innerHTML="";editing=-1}
 modal.addEventListener("change",function(e){if(e.target.getAttribute&&e.target.getAttribute("data-f")==="needs")shows()});
 modal.addEventListener("click",function(e){if(e.target===modal){close();return}var b=e.target.closest&&e.target.closest("button");if(!b)return;
  if(b.hasAttribute("data-close")){close();return}
  var msg=modal.querySelector(".rp-cmsg");
  if(b.hasAttribute("data-save")){var o=read();if(!o.label.trim()){setText(msg,"A status needs a name");return}
   var l=items.slice();if(editing>=0)l[editing]=Object.assign({},items[editing],o);else l.push(o);
   b.disabled=true;save(l,function(ok,x){b.disabled=false;if(ok)close();else setText(msg,(x&&x.message)||"That did not work")})}
  if(b.hasAttribute("data-del")){var name=items[editing].label;askConfirm("Delete the status "+name+"?","Delete",function(){var l=items.slice();l.splice(editing,1);save(l,function(ok,x){if(ok)close();else setText(modal.querySelector(".rp-cmsg"),(x&&x.message)||"That did not work")})})}});
 modal.addEventListener("keydown",function(e){if(e.key==="Enter"&&e.target.type==="text"){e.preventDefault();var b=modal.querySelector("[data-save]");if(b)b.click()}});
 hook("escape",function(){if(modal.style.display!=="none"){close();return true}});
 bind("@checkin.statuses",paint)});

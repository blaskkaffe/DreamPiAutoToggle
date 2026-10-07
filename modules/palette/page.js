// Colour palette module, page side: the widget "palette-editor" (Settings > Colour palette). One row per colour of the palette: drag its handle to move it,
// Edit changes its name and its colour on screen (or deletes it; what the LED shows is set in Status LED > Colours), Add colour makes a new one, Reset palette brings back the colours the add-on ships.
// Everything is saved as it is done; the rest of the page follows at once (/api carries the changed palette).
custom("palette-editor",function(host,ctx){
 var list=h("div",{"class":"mlist"}),data=[],cur=null,timer=null,
  nameIn=h("input",{type:"text",maxlength:"24","aria-label":"Colour name"}),
  uiIn=h("input",{type:"color","aria-label":"Colour on screen"}),
  uiRow=h("div",{"class":"frow"},[h("span",{text:"Colour"}),uiIn]),
  del=h("button",{type:"button","class":"pill-s danger",text:"Delete"}),back=h("button",{type:"button","class":"pill-s",text:"Default"}),done=h("button",{type:"button","class":"pill-s",text:"Done"}),
  title=h("div",{"class":"t",text:"Colour"}),
  pop=h("div",{},[title,h("div",{"class":"frow"},[h("span",{text:"Name"}),nameIn]),uiRow,h("div",{"class":"bar"},[del,back,done])]),
  add=h("button",{type:"button","class":"pill-s",text:"Add colour"}),reset=h("button",{type:"button","class":"pill-s",text:"Reset palette"}),
  foot=h("div",{"class":"bar"},[add,reset]),p=ui.popup(pop),dragging=false;
 host.appendChild(list);host.appendChild(foot);host.appendChild(pop);
 function byId(id){var r=null;data.forEach(function(c){if(c.id===id)r=c});return r}
 function take(r){if(r&&r.colours){data=r.colours;sh(add,r.can_add!==false);paint();var c=p.isOpen()?byId(cur):null;if(c){title.textContent=c.name;sh(back,!c.custom&&c.changed)}}}      // an open editor keeps what is typed in it; only its title and the Default button follow
 function paint(){if(list.classList.contains("dragging"))return;list.innerHTML="";
  data.forEach(function(c){
   var grip=h("button",{type:"button","class":"grip",title:"Drag to move (or use the up and down arrow keys)","aria-label":"Move "+c.name+": drag, or use the up and down arrow keys",html:GRIP_SVG}),
    ball=h("span",{"class":"swatch",style:"--c:"+c.ui+";--cl:"+c.ui_l}),
    edit=h("button",{type:"button","class":"pill-s",text:"Edit","aria-label":"Edit "+c.name}),
    note=c.id==="network"?"Follows the selected network":c.id==="global"?"The colour you pick in Appearance":(c.custom?"Your own":(c.changed?"Changed":"")),
    left=h("span",{},[document.createTextNode(c.name),h("span",{"class":"sub",text:c.ui+(note?" • "+note:"")})]);
   edit.onclick=function(e){e.stopPropagation();openEditor(c.id,edit)};
   list.appendChild(h("div",{"class":"srow","data-id":c.id},[grip,left,ball,edit]))});
  sortable(list,function(names){post("/palette/order",{order:names},function(r){take(r);ctx.saved()})})}
 function load(){xhrJson("GET","/palette/list",function(r){take(r)})}
 function openEditor(id,anchor){var c=byId(id);if(!c)return;cur=id;
  title.textContent=c.name;nameIn.value=c.name;uiIn.value=c.ui;
  sh(uiRow,id!=="network");sh(del,!c.fixed);sh(back,!c.custom&&c.changed);
  p.open(anchor)}
 function save(body){clearTimeout(timer);timer=setTimeout(function(){body.id=cur;post("/palette/edit",body,function(r){if(r){take(r);ctx.saved()}})},250)}
 nameIn.onchange=function(){if(nameIn.value.trim())save({name:nameIn.value})};
 uiIn.oninput=function(){save({ui:uiIn.value})};
 del.onclick=function(){var c=byId(cur);if(!c||!confirm("Delete the colour "+c.name+"? Whatever uses it goes back to its default colour."))return;
  p.close();post("/palette/delete",{id:cur},function(r){if(r){take(r);ctx.saved()}else alert("That colour cannot be deleted.")})};
 back.onclick=function(){p.close();post("/palette/reset",{id:cur},function(r){if(r){take(r);ctx.saved()}})};
 done.onclick=function(){p.close()};
 add.onclick=function(e){e.stopPropagation();post("/palette/add",{name:"New colour",ui:"#8890a0"},function(r){if(!r){alert("The palette is full.");return}take(r);ctx.saved();
  var row=list.querySelector('[data-id="'+r.id+'"]');if(row)openEditor(r.id,row.querySelector("button.pill-s"))})};
 reset.onclick=function(e){e.stopPropagation();if(confirm("Bring back the colours the add-on ships? Your own colours, names, order and changes are lost."))post("/palette/reset",{},function(r){if(r){take(r);ctx.saved()}})};
 hook("settingsOpen",load);hook("settingsClose",function(){p.close()});UPD.push(function(){if(!p.isOpen()&&!list.classList.contains("dragging")&&PV!==host._pv){host._pv=PV;load()}});load()});

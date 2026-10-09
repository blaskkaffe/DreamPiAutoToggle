// The contacts module's one custom widget: a CSV file or pasted text to the server (POST /contacts/import).
custom("contacts-import",function(host){
 var ta=host.querySelector(".ctext"),file=host.querySelector(".cfile"),rep=host.querySelector(".crep"),go=host.querySelector(".cgo"),msg=host.querySelector(".cmsg"),pick=host.querySelector(".cpick"),fname=host.querySelector(".cname");
 pick.onclick=function(){file.click()};
 file.onchange=function(){var f=file.files&&file.files[0];if(!f)return;setText(fname,f.name);var r=new FileReader();
  // UTF-8 when the bytes are valid UTF-8; else Windows-1252 (what a plain "CSV" save in Excel on a Swedish PC gives: a, a, o are single bytes)
  r.onload=function(){var buf=r.result,txt;try{txt=new TextDecoder("utf-8",{fatal:true}).decode(buf)}catch(e){txt=new TextDecoder("windows-1252").decode(buf)}ta.value=txt};r.readAsArrayBuffer(f)};
 go.onclick=function(){if(!ta.value.trim()){setText(msg,"Choose a file or paste some text first");return}
  go.disabled=true;setText(msg,"Importing...");
  post("/contacts/import",{csv:ta.value,replace:rep.checked},function(r,st,b){go.disabled=false;
   setText(msg,(b&&b.message)||"The import did not work");
   if(r&&r.ok){ta.value="";file.value="";setText(fname,"No file chosen");reloadData("contacts");refresh()}})}});

// The people on file, one row each with a switch for "on the board" (the standard row and toggle widgets, built from the data source /contacts).
// A tap on a row (not on its switch) opens a pop-up to edit the person: name, department, role, phone, building (POST /contacts/person).
custom("contacts-people",function(host){var key="",box=host.querySelector(".cpeople"),modal=h("div",{"class":"rp-modal keep-visible",style:"display:none"}),list0=[];
 document.body.appendChild(modal);box.style.maxHeight="46vh";box.style.overflowY="auto";
 var FIELDS=[["name","Name","text"],["department","Department","text"],["role","Role","text"],["phone","Phone","tel"],["location","Building","text"]];
 function close(){modal.style.display="none";modal.innerHTML=""}
 function edit(p){modal.innerHTML='<div class="rp-sheet rp-need2" role="dialog" aria-modal="true" aria-label="Edit '+esc(p.title)+'"><button type="button" class="rp-x" data-close="1" title="Close" aria-label="Close">&#10005;</button>'+
  
  '<div class="rp-who"><span class="cphoto">'+rosterAvatar({name:p.name,photo:p.photo},"rp-avb")+'</span><div class="rp-wt"><div class="rp-wn">'+esc(p.title)+'</div>'+
  '<div class="rp-nb"><button type="button" class="pill-s rp-so" data-pick="1">Choose photo</button><button type="button" class="pill-s rp-so" data-nophoto="1"'+(p.photo?"":" disabled")+'>Remove photo</button></div>'+
  '<input type="file" accept="image/*" class="cfilepick" data-photo="1" hidden aria-label="Photo of '+esc(p.name)+'"></div></div>'+FIELDS.map(function(f){return '<label class="rp-nl">'+f[1]+'<input class="rp-big" type="'+f[2]+'" data-f="'+f[0]+'" value="'+esc(p[f[0]]||"")+'" maxlength="80"></label>'}).join("")+
  '<label class="rp-nl rp-chk"><input type="checkbox" class="cbox neutral" data-f="restrictToLocation"'+(p.restrict?" checked":"")+'> Only show on the board when this building is chosen</label>'+
  '<div class="rp-cmsg sub" aria-live="polite"></div><div class="rp-nb rp-nb3"><button type="button" class="pill-s danger rp-so" data-del="1">Delete</button><button type="button" class="pill-s rp-so" data-close="1">Cancel</button><button type="button" class="pill-s pri rp-so c-green" data-save="1">Save</button></div></div>';
  modal.style.display="";var f0=modal.querySelector("input");if(f0&&f0.focus)f0.focus();
  modal._id=p.id}
 // Delete: asks first in a pop-up, then removes the person (and their photo) for good
 function del(b){var name=modal.querySelector(".rp-wn").textContent;
  askConfirm("Delete "+name+"? This can't be undone.","Delete",function(){
   b.disabled=true;post("/contacts/delete",{id:modal._id},function(r,st,x){b.disabled=false;
    if(r&&r.ok){close();reloadData("contacts");refresh();return}setText(modal.querySelector(".rp-cmsg"),(x&&x.message)||"That did not work")})})}
 function save(){var body={id:modal._id},msg=modal.querySelector(".rp-cmsg"),btn=modal.querySelector("[data-save]");
  Array.prototype.forEach.call(modal.querySelectorAll("[data-f]"),function(i){body[i.getAttribute("data-f")]=i.type==="checkbox"?i.checked:i.value});
  btn.disabled=true;post("/contacts/person",body,function(r,st,b){btn.disabled=false;
   if(r&&r.ok){close();reloadData("contacts");refresh();return}
   setText(msg,(b&&b.message)||"That did not work")})}
 modal.addEventListener("click",function(e){if(e.target===modal){close();return}var b=e.target.closest&&e.target.closest("button");if(!b)return;
  if(b.hasAttribute("data-close"))close();else if(b.hasAttribute("data-save"))save();else if(b.hasAttribute("data-del"))del(b);
  else if(b.hasAttribute("data-pick"))modal.querySelector(".cfilepick").click();else if(b.hasAttribute("data-nophoto"))setPhoto("",b)});
 // The picture of a person is chosen here only (not by tapping the board): cut to a 160 px square in the browser, kept by this module (POST /contacts/photo)
 function paintPhoto(url){var p=list0.filter(function(x){return x.id===modal._id})[0];if(!p)return;p.photo=url;modal.querySelector(".cphoto").innerHTML=rosterAvatar({name:p.name,photo:url},"rp-avb");modal.querySelector("[data-nophoto]").disabled=!url}
 function setPhoto(data,btn){if(btn)btn.disabled=true;post("/contacts/photo",{id:modal._id,photo:data},function(r,st,b){
  if(!r){alert((b&&b.message)||"The photo was not saved");if(btn)btn.disabled=false;return}
  reloadData("contacts");refresh();paintPhoto(data?"/contacts/photo/"+modal._id+"?v="+Date.now():"")})}
 modal.addEventListener("change",function(e){var f=e.target&&e.target.getAttribute&&e.target.getAttribute("data-photo")&&e.target.files&&e.target.files[0];if(!f)return;
  var img=new Image(),url=URL.createObjectURL(f);
  img.onload=function(){var c=document.createElement("canvas"),n=160,m=Math.min(img.width,img.height),g=c.getContext("2d");c.width=c.height=n;
   g.drawImage(img,(img.width-m)/2,(img.height-m)/2,m,m,0,0,n,n);URL.revokeObjectURL(url);setPhoto(c.toDataURL("image/jpeg",.82))};
  img.onerror=function(){URL.revokeObjectURL(url);alert("That file is not a picture")};img.src=url;e.target.value=""});
 modal.addEventListener("keydown",function(e){if(e.key==="Enter"&&e.target.type!=="checkbox"){e.preventDefault();save()}});
 hook("escape",function(){if(modal.style.display!=="none"){close();return true}});
 bind("@contacts.people",function(list){list=list||[];var k=JSON.stringify(list);if(k===key)return;key=k;list0=list;box.innerHTML="";
  list.forEach(function(p){var row=build({type:"row",title:p.title,sub:p.tag,control:{type:"toggle",bind:p.active,post:"/contacts/active",body:{id:p.id},label:p.title+" on the board"}},{saved:function(){reloadData("contacts")}});
   row.classList.add("rp-edit");row.setAttribute("title","Edit "+p.title);
   row.addEventListener("click",function(e){if(e.target.closest&&e.target.closest("input,label,button"))return;edit(p)});box.appendChild(row)})})});

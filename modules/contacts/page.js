// The contacts module's one custom widget: a CSV file or pasted text to the server (POST /contacts/import).
custom("contacts-import",function(host){
 var ta=host.querySelector(".ctext"),file=host.querySelector(".cfile"),rep=host.querySelector(".crep"),go=host.querySelector(".cgo"),msg=host.querySelector(".cmsg");
 file.onchange=function(){var f=file.files&&file.files[0];if(!f)return;var r=new FileReader();
  r.onload=function(){ta.value=String(r.result||"")};r.readAsText(f)};
 go.onclick=function(){if(!ta.value.trim()){setText(msg,"Choose a file or paste some text first");return}
  go.disabled=true;setText(msg,"Importing...");
  post("/contacts/import",{csv:ta.value,replace:rep.checked},function(r,st,b){go.disabled=false;
   setText(msg,(b&&b.message)||"The import did not work");
   if(r&&r.ok){ta.value="";file.value="";reloadData("contacts");refresh()}})}});

// The people on file, one row each with a switch for "on the board" (the standard row and toggle widgets, built from the data source /contacts).
custom("contacts-people",function(host){var key="",box=host.querySelector(".cpeople");box.style.maxHeight="46vh";box.style.overflowY="auto";
 bind("@contacts.people",function(list){list=list||[];var k=JSON.stringify(list);if(k===key)return;key=k;box.innerHTML="";
  list.forEach(function(p){box.appendChild(build({type:"row",title:p.title,sub:p.tag,control:{type:"toggle",bind:p.active,post:"/contacts/active",body:{id:p.id},label:p.title+" on the board"}},{saved:function(){reloadData("contacts")}}))})})});

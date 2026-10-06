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

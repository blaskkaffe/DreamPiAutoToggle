// The system module's one custom widget: a backup file (a zip from Settings > Backup) to the server (POST /backup/restore). Restoring replaces the people, the
// statuses and the settings with the backup's, so it asks first; the page then loads again to show them.
custom("system-restore",function(host){
 var file=host.querySelector(".cfile"),go=host.querySelector(".cgo"),msg=host.querySelector(".cmsg"),pick=host.querySelector(".cpick"),fname=host.querySelector(".cname"),data="";
 pick.onclick=function(){file.click()};
 file.onchange=function(){var f=file.files&&file.files[0];data="";go.disabled=true;if(!f)return;setText(fname,f.name);setText(msg,"");
  var r=new FileReader();r.onload=function(){data=String(r.result).replace(/^[^,]*,/,"");go.disabled=!data};r.onerror=function(){setText(msg,"That file could not be read")};r.readAsDataURL(f)};
 go.onclick=function(){if(!data)return;
  askConfirm("Restore this backup? The people, statuses and settings now on this computer are replaced.","Restore",function(){
   go.disabled=true;setText(msg,"Restoring...");
   post("/backup/restore",{backup:data},function(r,st,b){
    if(r&&r.ok){setText(msg,"Restored. Loading the page again...");setTimeout(function(){location.reload()},1200);return}
    go.disabled=false;setText(msg,(b&&b.message)||"The restore did not work")})})}});

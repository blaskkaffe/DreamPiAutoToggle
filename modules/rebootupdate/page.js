// Reboot and Update module, page side: once an update this page watched has finished, reload it (the new page files are in place).
var updWatched=false;
hook("api",function(){var u=S.update;if(!u)return;
 if(u.state=="running")updWatched=true;
 if(u.state=="ok"&&updWatched){updWatched=false;setTimeout(function(){location.reload()},3000)}});

// Reboot and Update module, page side: once an update this page watched has finished, reload it (the new page files are in place).
// Settings stays open if it was: the update log and the result are what the person was looking at.
var updWatched=false;
hook("api",function(){var u=S.update;if(!u)return;
 if(u.state=="running")updWatched=true;
 if(u.state=="ok"&&updWatched){updWatched=false;setTimeout(function(){if($("settings").classList.contains("open"))reloadInSettings();else location.reload()},3000)}});

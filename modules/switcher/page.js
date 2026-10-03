// Network switcher module, page side: the browser tab's icon follows the selected network (the box and the buttons are in layout.json).
var favNet="dcnow";
hook("api",function(d){
 if(d.network&&d.network!=favNet){favNet=d.network;$("fav").href="/static/favicon-"+d.network+".png";$("touch").href="/static/touch-"+d.network+".png"}});

// openMenu link module, page side: the custom widget "openmenu-games" (layout.json): the card's games with a search box and a Start button
// each. The box, its status and its note are the standard widgets over GET /openmenu/view (S.openmenu); the games are the data source
// om_games (S.om_games, GET /openmenu/games), read again when the hash in S.openmenu changes. The lists of other modules (the
// online players, the events) get their Start buttons from the "launcher" announcement in module.json, not from this file.
// A Start POSTs /openmenu/launch after asking.
custom("openmenu-games",function(host){
 var busy=false,msg="",lastHash=null;
 var find=h("input",{type:"text",placeholder:"Search the card","aria-label":"Search the card",autocomplete:"off"}),
  note=h("div",{"class":"sub"}),listEl=h("div",{"class":"wlist compact keep"}),listKey="";
 host.appendChild(find);host.appendChild(note);host.appendChild(listEl);
 function games(){return (S.om_games&&S.om_games.games)||[]}
 function can(){var v=S.openmenu;return !!(v&&v.connected&&!v.busy&&!busy)}
 function launch(g){
  if(!confirm("Start "+g.name+" on the Dreamcast?"))return;
  busy=true;msg="";
  post("/openmenu/launch",{product:g.product},function(r,st,b){busy=false;var m=b||r;msg=m&&m.message?m.message:"";reloadData("openmenu");engineUpdate()})}
 function row(g){
  var b=h("button",{type:"button","class":"pill-s",text:"Start","aria-label":"Start "+g.name});b.disabled=!can();b.onclick=function(){launch(g)};
  return h("div",{"class":"p"},[h("span",{"class":"pn"},[document.createTextNode(g.name),h("span",{"class":"pg",text:g.product+(g.disc?" • disc "+g.disc:"")})]),b])}
 function paint(){
  var v=S.openmenu;if(!v)return;
  if(lastHash!==v.hash){lastHash=v.hash;if(!S.om_games||S.om_games.hash!==v.hash)reloadData("om_games")}      // the Dreamcast sent a new list
  var all=games(),q=find.value.toLowerCase();
  var shown=all.filter(function(g){return !q||g.name.toLowerCase().indexOf(q)>=0||g.product.toLowerCase().indexOf(q)>=0}).slice(0,60);
  var lk=JSON.stringify([shown.map(function(g){return g.product+g.disc}),can()]);
  if(lk!==listKey){listKey=lk;listEl.innerHTML="";shown.forEach(function(g){listEl.appendChild(row(g))})}
  setText(note,msg||(all.length>shown.length?(all.length-shown.length)+" more: use the search":""));
  find.style.display=all.length?"block":"none"}
 find.oninput=function(){listKey="";paint()};
 UPD.push(paint);paint();
});

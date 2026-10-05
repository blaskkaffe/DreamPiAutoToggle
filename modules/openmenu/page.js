// openMenu link module, page side: the custom widget "openmenu-games" (layout.json). It shows the online players whose game is
// on the Dreamcast's SD card with a Join button, and the card's games with a search box and a Start button each. The box, its
// status and its note are the standard widgets over GET /openmenu/view (S.openmenu); the players come from the Online players
// module's data (S.players.list, when that module is on). A Start / Join POSTs /openmenu/launch after asking.
custom("openmenu-games",function(host){
 var games=[],hash=null,loading=false,busy=false,msg="";
 var find=h("input",{type:"text",placeholder:"Search the card","aria-label":"Search the card",autocomplete:"off"}),
  note=h("div",{"class":"sub"}),joinEl=h("div",{"class":"wlist compact keep"}),listEl=h("div",{"class":"wlist compact keep"}),
  joinKey="",listKey="";
 host.appendChild(joinEl);host.appendChild(find);host.appendChild(note);host.appendChild(listEl);
 // the card's game that a game title means: the same name, else one name inside the other (the shortest wins)
 function norm(t){return String(t||"").toLowerCase().replace(/[^a-z0-9]+/g,"")}
 function matchGame(title){
  var w=norm(title),best=null,i,n;
  if(w.length<3)return null;
  for(i=0;i<games.length;i++){if(norm(games[i].name)===w)return games[i]}
  for(i=0;i<games.length;i++){n=norm(games[i].name);if(n.length>=3&&(w.indexOf(n)>=0||n.indexOf(w)>=0)&&(!best||n.length<norm(best.name).length))best=games[i]}
  return best}
 function can(){var v=S.openmenu;return !!(v&&v.connected&&!v.busy&&!busy)}
 function launch(g){
  if(!confirm("Start "+g.name+" on the Dreamcast?"))return;
  busy=true;msg="";
  post("/openmenu/launch",{product:g.product},function(r,st,b){busy=false;var m=b||r;msg=m&&m.message?m.message:"";engineUpdate()})}
 function row(title,sub,tag,g){
  var kids=[h("span",{"class":"pn"},[document.createTextNode(title),h("span",{"class":"pg",text:sub})])];
  if(g){var b=h("button",{type:"button","class":"pill-s",text:tag,"aria-label":tag+" "+g.name});b.disabled=!can();b.onclick=function(){launch(g)};kids.push(b)}
  return h("div",{"class":"p"},kids)}
 function loadGames(){
  if(loading)return;loading=true;
  xhrJson("GET","/openmenu/games",function(r){loading=false;if(r&&r.games){games=r.games;hash=r.hash;joinKey=listKey="";paint()}})}
 function paint(){
  var v=S.openmenu;if(!v)return;
  if(hash!==v.hash)loadGames();
  var q=find.value.toLowerCase(),btnState=can()?"1":"0";
  var pl=(S.players&&S.players.list)||[],joins=[];
  pl.forEach(function(p){var g=p.sub&&p.sub!=="(Idle)"?matchGame(p.sub):null;if(g)joins.push({p:p,g:g})});
  var jk=JSON.stringify([joins.map(function(j){return [j.p.title,j.g.product]}),btnState]);
  if(jk!==joinKey){joinKey=jk;joinEl.innerHTML="";
   if(joins.length)joinEl.appendChild(h("div",{"class":"sub",text:"Playing a game on your card:"}));
   joins.forEach(function(j){joinEl.appendChild(row(j.p.title,j.p.sub+(j.p.tag?" • "+j.p.tag:""),"Join",j.g))})}
  var shown=games.filter(function(g){return !q||g.name.toLowerCase().indexOf(q)>=0||g.product.toLowerCase().indexOf(q)>=0}).slice(0,60);
  var lk=JSON.stringify([shown.map(function(g){return g.product+g.disc}),btnState]);
  if(lk!==listKey){listKey=lk;listEl.innerHTML="";
   shown.forEach(function(g){listEl.appendChild(row(g.name,g.product+(g.disc?" • disc "+g.disc:""),"Start",g))})}
  setText(note,msg||(games.length>shown.length?(games.length-shown.length)+" more: use the search":""));
  find.style.display=games.length?"block":"none"}
 find.oninput=function(){listKey="";paint()};
 UPD.push(paint);paint();
});

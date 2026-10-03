// Clock module, page side: the time zone map, a custom widget in the clock box. It shows the world in 24 time zone bands with the
// hour in each, the band of the Pi's own time zone highlighted, and a dot for every city of the world time list.
// The numbers come from /api (S.clock.map: utc, local offset, cities); the land is a hand-made rough outline [lon, lat, ...].
var CLOCK_LAND=[
 [-168,66,-162,70,-156,71,-140,70,-128,70,-115,68,-95,72,-85,68,-80,63,-93,60,-94,58,-85,55,-80,52,-78,62,-70,60,-62,58,-56,52,-60,47,-66,45,-70,43,-76,38,-81,31,-80,25,-82,27,-85,30,-90,29,-97,27,-97,22,-92,18,-87,21,-88,16,-83,15,-83,10,-79,9,-77,8,-82,8,-86,12,-92,14,-97,16,-105,20,-110,24,-113,31,-117,32,-121,35,-124,40,-124,47,-128,51,-135,58,-146,61,-152,59,-158,57,-165,55,-160,59,-165,62],
 [-77,8,-72,12,-62,10,-52,5,-50,0,-44,-2,-35,-6,-39,-14,-41,-22,-48,-26,-53,-34,-58,-38,-62,-40,-65,-45,-68,-52,-70,-55,-74,-50,-73,-40,-71,-30,-70,-18,-76,-14,-81,-5,-80,0,-77,4],
 [-73,78,-60,82,-30,83,-20,78,-20,70,-30,67,-43,60,-50,64,-55,70],
 [-10,36,-9,43,-1,46,-4,48,2,51,8,54,10,58,5,62,14,68,25,71,40,68,60,70,80,73,105,77,130,72,150,71,170,70,180,68,180,65,165,60,155,58,160,52,143,52,140,47,135,43,129,35,122,40,121,31,118,24,108,21,106,10,100,13,104,2,98,8,98,16,92,22,87,21,80,15,77,8,73,17,67,25,57,25,56,27,51,25,56,17,44,13,35,28,34,31,36,36,28,37,26,40,23,36,20,40,13,45,16,41,18,40,12,38,8,44,3,43,-5,36],
 [-17,21,-10,30,-6,36,10,37,11,33,20,32,32,31,35,28,43,12,51,12,41,-2,40,-15,35,-24,32,-29,25,-34,18,-34,12,-17,13,-8,9,-1,9,4,-8,4,-13,8,-17,14],
 [114,-22,122,-18,130,-12,137,-12,142,-11,146,-19,153,-26,150,-37,141,-38,135,-34,129,-32,116,-35,113,-26],
 [-5,50,1,51,2,53,-2,56,-3,58.5,-6,58,-5,54,-3,53],
 [130,31,133,34,140,35,141,41,142,45,140,41,136,36,131,34],
 [44,-13,50,-15,48,-25,44,-24],
 [95,5,105,-6,103,-5,98,0],
 [109,1,118,7,119,1,116,-4,110,-3],
 [172,-35,178,-38,174,-42,170,-46,167,-45,172,-40],
 [-24,64,-14,65,-14,66,-22,66]];
custom("clock-map",function(host){
 var NS="http://www.w3.org/2000/svg",W_=360,H_=150,TOP=11;
 function X(lon){return lon+180}
 function Y(lat){return Math.max(TOP,TOP+75-Math.min(75,lat))}
 function el(name,attrs,parent){var e=document.createElementNS(NS,name);for(var k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e}
 var svg=el("svg",{"class":"cmap",viewBox:"0 0 "+W_+" "+H_,role:"img","aria-label":"Time zone map"}),note=h("div",{"class":"cmapnote"});
 var bands=[],hours=[];
 for(var o=-12;o<=12;o++){var x0=Math.max(0,X(o*15-7.5)),x1=Math.min(W_,X(o*15+7.5));
  bands.push(el("rect",{"class":"band"+(o%2?" alt":""),x:x0,y:TOP,width:x1-x0,height:H_-TOP},svg));
  hours.push(el("text",{"class":"hr",x:(x0+x1)/2,y:8.5},svg))}
 CLOCK_LAND.forEach(function(p){var pts=[];for(var i=0;i<p.length;i+=2)pts.push(X(p[i])+","+Y(p[i+1]));el("polygon",{"class":"land",points:pts.join(" ")},svg)});
 var dots=el("g",{},svg);
 host.appendChild(svg);host.appendChild(note);
 function utcText(off){var a=Math.abs(off),hh=Math.floor(a),mm=Math.round((a-hh)*60);return "UTC"+(off<0?"-":"+")+hh+(mm?":"+(mm<10?"0":"")+mm:"")}
 var made=0;
 function paint(){var c=S.clock,m=c&&c.map;if(!m)return;
  var here=Math.round(m.local);
  for(var i=0;i<bands.length;i++){var off=i-12,hr=Math.floor((((m.utc+off*3600)%86400)+86400)%86400/3600);
   if(c.format==="12h")hr=hr%12||12;
   setText(hours[i],String(hr));bands[i].setAttribute("class","band"+(off%2?" alt":"")+(off===here?" here":""))}
  if(made!==m.cities.length){dots.innerHTML="";m.cities.forEach(function(ci){var d=el("circle",{"class":"city",cx:X(ci.lon),cy:Y(ci.lat),r:2.2},dots);var t=el("title",{},d);t.textContent=ci.name+" "+ci.text});made=m.cities.length}
  else{var k=0;Array.prototype.forEach.call(dots.childNodes,function(d,i){var ci=m.cities[i];if(ci)d.firstChild.textContent=ci.name+" "+ci.text})}
  setText(note,"This Pi: "+utcText(m.local)+" (highlighted)")}
 hook("api",paint);paint()});

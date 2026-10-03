// Clock module, page side: two custom widgets in the clock box, shown when the box is opened with world time on.
//  clock-list  the picked cities, each with its time on one line (S.clock.cities: [[name, time], ...])
//  clock-map   the world's time zones: the real areas (GET /clock/zones, fetched the first time the map is drawn; made by
//              tools/build_clock_zones.py from timezone-boundary-builder, OpenStreetMap data, ODbL) on faint sea bands of 15 degrees.
//              Each area's offset comes with /api (S.clock.map.offs, summer time included), so an area shows the hour it has
//              now; the areas with the same time as the clock are highlighted and the cities are dots.
custom("clock-list",function(host){
 var box=h("div",{"class":"cwl"});host.appendChild(box);var last="";
 function paint(){var c=S.clock,l=(c&&c.cities)||[],k=JSON.stringify(l);if(k===last)return;last=k;
  setHtml(box,l.map(function(x){return '<span class="cwc"><span class="cwn">'+esc(x[0])+'</span><span class="cwt">'+esc(x[1])+'</span></span>'}).join(""))}
 hook("api",paint);paint()});
custom("clock-map",function(host){
 var NS="http://www.w3.org/2000/svg",RT=9,TOPLAT=78,BOTLAT=-60,W_=360,H_=RT+TOPLAT-BOTLAT;
 function el(name,attrs,parent){var e=document.createElementNS(NS,name);for(var k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e}
 var svg=el("svg",{"class":"cmap",viewBox:"0 0 "+W_+" "+H_,role:"img","aria-label":"Time zone map"}),note=h("div",{"class":"cmapnote"});
 for(var o=-12;o<=12;o++){var x0=Math.max(0,o*15-7.5+180),x1=Math.min(W_,o*15+7.5+180);         // the sea keeps the plain 15-degree zones
  el("rect",{"class":"sea"+(o%2?" alt":""),x:x0,y:RT,width:x1-x0,height:H_-RT},svg);
  var t=el("text",{"class":"ofs",x:(x0+x1)/2,y:7},svg);t.textContent=o>0?"+"+o:String(o)}
 var areas=el("g",{transform:"translate(0,"+RT+")"},svg),labels=el("g",{transform:"translate(0,"+RT+")"},svg),dots=el("g",{},svg);
 host.appendChild(svg);host.appendChild(note);
 var Z=null,asked=false,shapes=[],texts=[],made="";
 function load(){if(asked)return;asked=true;
  xhrJson("GET","/clock/zones",function(r){if(!r||!r.zones){asked=false;return}Z=r;
   r.zones.forEach(function(z,i){var g=el("g",{},areas);
    z.p.forEach(function(ring){var pts=[];for(var k=0;k<ring.length;k+=2)pts.push(ring[k]+","+ring[k+1]);el("polygon",{points:pts.join(" ")},g)});
    shapes[i]=g;texts[i]=z.l.map(function(p){return el("text",{"class":"zl",x:Math.min(W_-7,Math.max(7,p[0])),y:p[1]+2},labels)})});
   paint()})}
 function hourText(utc,off,fmt){var m=Math.floor(((utc/60+off*60)%1440+1440)%1440),hh=Math.floor(m/60),mm=m%60;
  if(fmt==="12h")hh=hh%12||12;return String(hh)+(off%1?":"+(mm<10?"0":"")+mm:"")}
 function paint(){var c=S.clock,m=c&&c.map;if(!m)return;load();
  if(Z){for(var i=0;i<shapes.length;i++){var off=m.offs&&m.offs[i];
    var cls="z"+(off==null?" none":(off%1?" frac":(Math.floor(off)%2?" odd":"")))+(off!=null&&Math.abs(off-m.here)<0.01?" here":"");
    if(shapes[i].getAttribute("class")!==cls)shapes[i].setAttribute("class",cls);
    texts[i].forEach(function(t){setText(t,off==null?"":hourText(m.utc,off,c.format))})}}
  var key=JSON.stringify(m.cities.map(function(x){return[x.name,x.lon,x.lat]}));
  if(key!==made){made=key;dots.innerHTML="";m.cities.forEach(function(ci){
    var d=el("circle",{"class":"city",cx:ci.lon+180,cy:RT+TOPLAT-ci.lat,r:2.4},dots);el("title",{},d)})}
  Array.prototype.forEach.call(dots.childNodes,function(d,i){var ci=m.cities[i];if(ci)setText(d.firstChild,ci.name+" "+ci.text)});
  setText(note,"Highlighted: where it is the same time as this clock ("+m.zone+")")}
 hook("api",paint);paint()});

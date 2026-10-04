// Clock module, page side: two custom widgets in the clock box, shown when the box is opened with world time on.
//  clock-list  the picked cities, each with its time on one line (S.clock.cities: [[name, time], ...])
//  clock-map   the world's time zones as a stylised map: the areas (GET /clock/zones, fetched the first time the map is drawn; made
//              by tools/build_clock_zones.py from timezone-boundary-builder, OpenStreetMap data, ODbL, simplified) on faint sea
//              stripes of 15 degrees, the hour it is in each stripe along the top and its UTC offset along the bottom. Each area's
//              offset comes with /api (S.clock.map.offs, summer time included); the areas with the same time as the clock are
//              highlighted and the cities are dots.
//  And the time itself: with "Large clock" on the box gives the time more rows (data-mode, page.css) and fit() sizes the text to them.
custom("clock-list",function(host){
 var box=h("div",{"class":"cwl"});host.appendChild(box);var last="";
 function paint(){var c=S.clock,l=(c&&c.cities)||[],k=JSON.stringify(l);if(k===last)return;last=k;
  setHtml(box,l.map(function(x){return '<span class="cwc"><span class="cwn">'+esc(x[0])+'</span><span class="cwt">'+esc(x[1])+'</span></span>'}).join(""))}
 hook("api",paint);paint()});
custom("clock-map",function(host){
 var NS="http://www.w3.org/2000/svg",RT=10,RB=10,TOPLAT=78,BOTLAT=-60,W_=360,MAPH=TOPLAT-BOTLAT,H_=RT+MAPH+RB;
 function el(name,attrs,parent){var e=document.createElementNS(NS,name);for(var k in attrs)e.setAttribute(k,attrs[k]);if(parent)parent.appendChild(e);return e}
 var svg=el("svg",{"class":"cmap",viewBox:"0 0 "+W_+" "+H_,role:"img","aria-label":"Time zone map"}),hours=[];
 for(var o=-12;o<=12;o++){var x0=Math.max(0,o*15-7.5+180),x1=Math.min(W_,o*15+7.5+180);         // the sea keeps the plain 15-degree zones
  el("rect",{"class":"sea"+(o%2?" alt":""),x:x0,y:RT,width:x1-x0,height:MAPH},svg);
  var hr=el("text",{"class":"hr",x:(x0+x1)/2,y:RT-2.5},svg);hours.push([o,hr]);                   // the hour it is in this stripe (top)
  var t=el("text",{"class":"ofs",x:(x0+x1)/2,y:H_-2.5},svg);t.textContent=o>0?"+"+o:String(o)}     // its UTC offset (bottom)
 var areas=el("g",{transform:"translate(0,"+RT+")"},svg),dots=el("g",{},svg);
 host.appendChild(svg);
 var Z=null,asked=false,shapes=[],made="";
 function load(){if(asked)return;asked=true;
  xhrJson("GET","/clock/zones",function(r){if(!r||!r.zones){asked=false;return}Z=r;
   r.zones.forEach(function(z,i){var g=el("g",{},areas);
    z.p.forEach(function(ring){var pts=[];for(var k=0;k<ring.length;k+=2)pts.push(ring[k]+","+ring[k+1]);el("polygon",{points:pts.join(" ")},g)});
    shapes[i]=g});
   paint()})}
 function hourText(utc,off,fmt){var m=Math.floor(((utc/60+off*60)%1440+1440)%1440),hh=Math.floor(m/60);
  if(fmt!=="24h")hh=hh%12||12;return String(hh)}
 function paint(){var c=S.clock,m=c&&c.map;if(!m)return;load();
  hours.forEach(function(x){setText(x[1],hourText(m.utc,x[0],c.format))});
  if(Z){for(var i=0;i<shapes.length;i++){var off=m.offs&&m.offs[i];
    var cls="z"+(off==null?" none":(off%1?" frac":(Math.floor(off)%2?" odd":"")))+(off!=null&&Math.abs(off-m.here)<0.01?" here":"");
    if(shapes[i].getAttribute("class")!==cls)shapes[i].setAttribute("class",cls)}}
  var key=JSON.stringify(m.cities.map(function(x){return[x.name,x.lon,x.lat]}));
  if(key!==made){made=key;dots.innerHTML="";m.cities.forEach(function(ci){
    var d=el("circle",{"class":"city",cx:ci.lon+180,cy:RT+TOPLAT-ci.lat,r:3.4},dots);el("title",{},d)})}
  Array.prototype.forEach.call(dots.childNodes,function(d,i){var ci=m.cities[i];if(ci)setText(d.firstChild,ci.name+" "+ci.text)})}
 hook("api",paint);paint()});
// The time of a large clock: the text is as big as the rows it was given (data-mode, page.css) and the box's width allow
(function(){var cv=document.createElement("canvas").getContext("2d"),last="";
 function fit(){var now=document.querySelector('.dbox[data-box="clock"] .now'),b=now&&now.querySelector(":scope > b");if(!b)return;
  if(!now.hasAttribute("data-mode")||now.classList.contains("open")){if(b.style.fontSize){b.style.fontSize="";last=""}return}
  var cs=getComputedStyle(b),w=b.clientWidth,hh=b.clientHeight,t=b.textContent,key=[t.length,w,hh,cs.fontFamily].join("|");
  if(key===last||!w||!hh)return;last=key;cv.font="bold 100px "+cs.fontFamily;
  b.style.fontSize=Math.max(10,Math.min(hh*0.8,w*0.96*100/(cv.measureText(t).width||1)))+"px"}
 hook("api",fit);hook("layout",fit);window.addEventListener("resize",fit)})();

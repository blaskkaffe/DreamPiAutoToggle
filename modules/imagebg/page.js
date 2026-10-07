// Background image module, page side. The background: a fixed picture layer (and a black layer over it that darkens it) drawn from
// S.imagebg ({has, fit, dim, version} in /api), so a change made on another device shows here too. The widget "imagebg-pick" (Settings >
// Background image) chooses the picture: a big one is shrunk in the browser first (at most 2560 px, JPEG) before it is sent to the Pi.
background("imagebg",function(host){
 var pic=h("div",{id:"imgbg"}),dim=h("div",{id:"imgbg-dim"}),last="";
 host.appendChild(pic);host.appendChild(dim);
 var SIZE={cover:"cover",contain:"contain",stretch:"100% 100%",tile:"auto"};
 function paint(){var v=S.imagebg||{},key=JSON.stringify(v);if(key===last)return;last=key;
  document.body.classList.toggle("imgbg-on",!!v.has);document.documentElement.classList.toggle("imgbg-on",!!v.has);document.documentElement.classList.toggle("dark-only",!!v.has);
  pic.style.backgroundImage=v.has?"url(/imagebg/image?v="+v.version+")":"none";
  pic.style.backgroundSize=SIZE[v.fit]||"cover";pic.style.backgroundRepeat=v.fit==="tile"?"repeat":"no-repeat";
  dim.style.opacity=String((v.dim||0)/100)}
 UPD.push(paint);paint()});
custom("imagebg-pick",function(host,ctx){
 var file=h("input",{type:"file",accept:"image/png,image/jpeg,image/gif,image/webp","class":"imgbg-file","aria-label":"Background picture"}),
  r=editRow({title:"Picture",button:"Choose",aria:"Choose a background picture",button2:"Remove",aria2:"Remove the background picture"}),
  thumb=h("div",{"class":"imgbg-thumb"});
 host.appendChild(r.el);host.appendChild(file);r.el.querySelector(".below").appendChild(thumb);
 function shrink(f,done){      // the file itself when it is small, else a JPEG of at most 2560 px
  if(f.size<1500000&&/^image\/(jpeg|png|webp|gif)$/.test(f.type))return done(f);
  var url=URL.createObjectURL(f),img=new Image();
  img.onload=function(){var sc=Math.min(1,2560/Math.max(img.naturalWidth,img.naturalHeight)),c=document.createElement("canvas");
   c.width=Math.max(1,Math.round(img.naturalWidth*sc));c.height=Math.max(1,Math.round(img.naturalHeight*sc));
   c.getContext("2d").drawImage(img,0,0,c.width,c.height);URL.revokeObjectURL(url);c.toBlob(done,"image/jpeg",.85)};
  img.onerror=function(){URL.revokeObjectURL(url);done(null)};img.src=url}
 function send(blob){var x=new XMLHttpRequest();x.open("POST","/imagebg/upload",true);x.setRequestHeader("X-Requested-With","page");
  if(pinValue)x.setRequestHeader("X-Pin",pinValue);
  x.onload=function(){r.btn.disabled=false;if(x.status===200){refresh();ctx.saved()}else alert(x.status===401?"Wrong PIN":(x.responseText||"The picture was not saved."))};
  x.onerror=function(){r.btn.disabled=false;alert("The picture was not saved.")};x.send(blob)}
 r.btn.onclick=function(e){e.stopPropagation();file.click()};
 file.onchange=function(){var f=file.files&&file.files[0];file.value="";if(!f)return;r.btn.disabled=true;
  shrink(f,function(b){if(!b){r.btn.disabled=false;alert("This browser can't read that picture. Try a JPEG or PNG.");return}send(b)})};
 r.btn2.onclick=function(e){e.stopPropagation();if(confirm("Remove the background picture?"))post("/imagebg/remove",{},function(v){if(v){refresh();ctx.saved()}})};
 function paint(){var v=S.imagebg||{};r.setSub(v.has?"A picture is set":"No picture yet: choose one from this device");sh(r.btn2,!!v.has);sh(thumb,!!v.has);
  var u=v.has?"url(/imagebg/image?v="+v.version+")":"none";if(thumb._u!==u){thumb._u=u;thumb.style.backgroundImage=u}}
 UPD.push(paint);paint()});

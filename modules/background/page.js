// Dreamcast background module, page side: a fixed layer behind the page that runs Robert Dale Smith's animated scene
// (dc-background.js, which needs three.min.js). Both come from this module (GET /background/...). If they can't be
// loaded the page just keeps its plain background. The look of the boxes on top of it is in page.css.
// The page calls this with the background's host element when this module is the one drawn (layout.json: a fullscreen background).
background("background",function(host){
 var layer=document.createElement("div");layer.id="dcbg";layer.className="keep-visible";
 host.appendChild(layer);
 function load(src,done){var sc=document.createElement("script");sc.src=src;sc.onload=done;
  sc.onerror=function(){document.body.classList.remove("dcbg");document.documentElement.classList.remove("dcbg")};document.head.appendChild(sc)}
 function go(){if(document.body.classList.contains("dcbg"))DCBackground.start(layer)}
 document.body.classList.add("dcbg");document.documentElement.classList.add("dcbg");
 if(window.DCBackground)go();
 else if(window.THREE)load("/background/dc-background.js",go);
 else load("/background/three.min.js",function(){load("/background/dc-background.js",go)});
});

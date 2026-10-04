// DC99 events module, page side: the list of the next two weeks in the events box (custom widget "events-list"), each event with
// its time (in the time zone of Settings > About), title (a link to its page), source and a bell (ui.iconButton) that sets or clears its reminder
// (POST /events/remind). The rows come from the data source S.events (GET /events/view).
custom("events-list",function(host){
 var box=h("div",{"class":"evlist"});host.appendChild(box);var last="";
 function paint(){var e=S.events,l=(e&&e.list)||[],k=JSON.stringify(l);if(k===last)return;last=k;
  if(!l.length){setHtml(box,'<div class="sub">No events in the next two weeks</div>');return}
  setHtml(box,l.map(function(x){var t=x.url?'<a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.title)+'</a>':esc(x.title);
   return '<div class="evr'+(x.reminded?' on':'')+'"><span class="evw">'+esc(x.day)+'<b>'+esc(x.hm)+'</b></span><span class="evt">'+t+'<span class="evsrc">'+esc(x.source)+(x.series?' · every one':'')+'</span></span>'+
    ui.iconButtonHtml("bell",x.reminded,x.title,'data-id="'+esc(x.id)+'"')+'</div>'}).join(""))}
 box.addEventListener("click",function(ev){var b=ev.target.closest&&ev.target.closest(".bell");if(!b)return;ev.stopPropagation();
  b.disabled=true;xhrJson("POST","/events/remind",function(r){b.disabled=false;if(r){S.events=r;engineUpdate();paint();refresh()}},{id:b.getAttribute("data-id"),on:b.getAttribute("aria-pressed")!=="true"})});
 hook("api",paint);UPD.push(paint);paint()});

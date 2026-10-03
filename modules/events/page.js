// DC99 events module, page side: the list of the next two weeks in the events box (custom widget "events-list"), each event with
// its time (in the zone set in Settings), title (a link to its page), source and a bell that sets or clears its reminder
// (POST /events/remind). The rows come from the data source S.events (GET /events/view).
custom("events-list",function(host){
 var box=h("div",{"class":"evlist"});host.appendChild(box);var last="";
 var BELL='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 22a2.5 2.5 0 0 0 2.4-2h-4.8A2.5 2.5 0 0 0 12 22zm7-6V11a7 7 0 0 0-5.5-6.8V3a1.5 1.5 0 0 0-3 0v1.2A7 7 0 0 0 5 11v5l-2 2v1h18v-1z"/></svg>';
 function paint(){var e=S.events,l=(e&&e.list)||[],k=JSON.stringify(l);if(k===last)return;last=k;
  if(!l.length){setHtml(box,'<div class="sub">No events in the next two weeks</div>');return}
  setHtml(box,l.map(function(x){var t=x.url?'<a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+esc(x.title)+'</a>':esc(x.title);
   return '<div class="evr'+(x.reminded?' on':'')+'"><span class="evw">'+esc(x.day)+'<b>'+esc(x.hm)+'</b></span><span class="evt">'+t+'<span class="evsrc">'+esc(x.source)+(x.series?' · every one':'')+'</span></span>'+
    '<button type="button" class="bell" data-id="'+esc(x.id)+'" aria-pressed="'+(x.reminded?'true':'false')+'" title="'+(x.reminded?'Reminder on: tap to clear':'Remind me')+'" aria-label="'+(x.reminded?'Clear the reminder for ':'Remind me of ')+esc(x.title)+'">'+BELL+'</button></div>'}).join(""))}
 box.addEventListener("click",function(ev){var b=ev.target.closest&&ev.target.closest(".bell");if(!b)return;ev.stopPropagation();
  b.disabled=true;xhrJson("POST","/events/remind",function(r){b.disabled=false;if(r){S.events=r;engineUpdate();paint();refresh()}},{id:b.getAttribute("data-id"),on:b.getAttribute("aria-pressed")!=="true"})});
 hook("api",paint);UPD.push(paint);paint()});

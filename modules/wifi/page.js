// Wi-Fi setup module, page side: the Wi-Fi rows at the top of Settings > System and the "which button holds to start it" row under
// the buttons. Setup itself runs in the module's own service (dreampi-netswitch-wifi); this talks to it through POST /wifitoggle and /wificonnect.
var WIFI_LABELS={
 idle:["Search","Search for a Wi-Fi network to connect the Pi to"],
 scanning:["Stop","Scanning for Wi-Fi networks..."],
 hosting:["Stop","Pick a network below, or connect to “DreamPi WiFi Config” and open http://192.168.4.1"],
 connecting:["Stop","Connecting to “%s”..."],
 ok:["Connected","Connected to “%s”"],
 failed:["Stop","Couldn't connect (%s)"]};
$("wifi-b").onclick=function(){
 var x=new XMLHttpRequest();x.open("POST","/wifitoggle",true);x.setRequestHeader("X-Requested-With","netswitch");
 x.onload=refresh;x.send()};
// Wi-Fi network list, shown in Settings too while scanning/hosting (not just on the temporary "DreamPi WiFi Config" page) -
// useful when this page is still reachable, for example over Ethernet, while the Pi's Wi-Fi is being (re)configured.
// One row per network (name, how strong, secured or open) with a Connect button that opens a pop-up for the password,
// the same way the phone numbers' Add button opens its pop-up. "Other network" is for a hidden one.
var wifiListKey=null;
function wifiStrength(sig){return sig==null?"":sig>=-55?"Strong":sig>=-65?"Good":sig>=-75?"Fair":"Weak"}
function renderWifiList(nets){
 var rows=nets.map(function(n,i){
  var info=[n.secured?"Secured":"Open",wifiStrength(n.signal)].filter(Boolean).join(" \u00b7 ");
  return ui.row({title:n.ssid,sub:info,control:ui.btn("Connect",{"data-i":i,"aria-label":"Connect to "+n.ssid})})}).join("");
 $("wifi-list").innerHTML=rows+(nets.length?"":ui.row({title:"No networks found"}))+
  ui.row({title:"Other network",sub:"For a hidden network: enter its name",control:ui.btn("Enter",{"data-i":-1})});
 Array.prototype.forEach.call($("wifi-list").querySelectorAll("button[data-i]"),function(b){
  b.onclick=function(e){wifiOpen(+b.dataset.i<0?{ssid:"",secured:true,other:true}:nets[+b.dataset.i],b,e)}})}
var wifiPop=ui.popup($("wifi-pop"));
function wifiOpen(n,btn,e){
 if(wifiPop.isOpen()&&wifiPop.anchor===btn){wifiPop.close();return}
 $("wifi-pop-t").textContent=n.other?"Connect to another network":"Connect to "+n.ssid;
 $("wifi-ssid").value=n.ssid;$("wifi-ssid").style.display=n.other?"block":"none";
 $("wifi-pass").value="";$("wifi-pass").style.display=n.secured?"block":"none";$("wifi-msg").textContent="";
 wifiPop.toggle(btn,e);
 (n.other?$("wifi-ssid"):n.secured?$("wifi-pass"):$("wifi-connect-b")).focus()}
function wifiClose(){wifiPop.close()}
function wifiConnect(){
 var ssid=$("wifi-ssid").value.trim();
 if(!ssid){$("wifi-msg").textContent="Enter the network name";return}
 withPin(function(){
  $("wifi-connect-b").disabled=true;$("wifi-connect-b").textContent="Connecting...";
  xhrJson("POST","/wificonnect",function(r,st,body){
   $("wifi-connect-b").disabled=false;$("wifi-connect-b").textContent="Connect";
   if(st==401||st==429){$("wifi-msg").textContent=(body&&body.message)||"PIN refused";return}
   wifiClose();refresh()},{ssid:ssid,password:$("wifi-pass").value})})}
$("wifi-connect-b").onclick=wifiConnect;
$("wifi-pass").onkeydown=$("wifi-ssid").onkeydown=function(e){if(e.key=="Enter"){e.preventDefault();wifiConnect()}};
hook("api",function(d){
 if(!d.wifi)return;
 var wl=WIFI_LABELS[d.wifi.state]||WIFI_LABELS.idle;
 setText($("wifi-b"),wl[0]);
 setText($("wifi-sub"),((d.wifi.demo&&d.wifi.state=="hosting")?"Pick a network below":wl[1].replace("%s",d.wifi.ssid||""))+(d.wifi.demo?" - DEMO: dummy networks, password \u201cdemo\u201d connects":""));
 $("wifi-b").disabled=d.wifi.state=="ok";
 var showNets=d.wifi.state=="hosting"||d.wifi.state=="scanning";
 $("wifi-networks").style.display=showNets?"block":"none";
 if(showNets&&d.wifi.networks){var key=JSON.stringify(d.wifi.networks);
  if(key!=wifiListKey){wifiListKey=key;renderWifiList(d.wifi.networks)}}
 else if(!showNets){wifiListKey=null;wifiClose();$("wifi-list").innerHTML=""}});
// the button row: which button, or both, held for 3 s starts Wi-Fi setup (saved with the other button settings)
hook("buttons",function(r){
 if(!$("wifi-btn-sel").options.length)$("wifi-btn-sel").innerHTML=r.wifi_choices.map(function(c){
  return '<option value="'+c[0]+'">'+esc(c[1])+'</option>'}).join("");
 $("wifi-btn-sel").value=btn.wifi_button});
function describeWifiButton(){var v=$("wifi-btn-sel").value;
 $("wifi-btn-sub").textContent="Hold button "+(v=="12"?"1 + 2":v)+" for 3 s to start Wi-Fi setup"}
hook("buttons",describeWifiButton);
$("wifi-btn-sel").onchange=function(){btn.wifi_button=this.value;describeWifiButton();saveButtons()};

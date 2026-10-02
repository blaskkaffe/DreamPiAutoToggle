// Wi-Fi setup module, page side: the Wi-Fi rows in Settings > Network and the "which button holds to start it" row under
// the buttons. Setup itself runs in the buttons service; this talks to it through POST /wifitoggle and /wificonnect.
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
// Wi-Fi network list, shown in Settings too while scanning/hosting (not just on the
// temporary "DreamPi WiFi Config" page) - useful when this page is still reachable,
// for example over Ethernet, while the Pi's Wi-Fi is being (re)configured.
var wifiListKey=null,wifiChosen=null;
function wifiBars(sig){if(sig==null)return"";var n=sig>=-55?4:sig>=-65?3:sig>=-75?2:1;return " "+"█".repeat(n)+"░".repeat(4-n)}
function renderWifiList(nets){
 $("wifi-list").innerHTML=nets.map(function(n,i){
  return '<button type="button" class="wnet" data-i="'+i+'">'+(n.secured?"🔒 ":"")+esc(n.ssid)+
   '<span class="sig">'+esc(wifiBars(n.signal))+'</span></button>'}).join("")||
  '<div class="sub" style="margin:4px 0 10px">No networks found. Enter one manually.</div>';
 Array.prototype.forEach.call($("wifi-list").querySelectorAll(".wnet"),function(b){
  b.onclick=function(){wifiSelect(nets[+b.dataset.i])}})}
function wifiSelect(n){wifiChosen=n;$("wifi-ssid").value=n.ssid;$("wifi-ssid").readOnly=true;
 $("wifi-pass").style.display=n.secured?"block":"none";$("wifi-pass").value="";
 $("wifi-connect-b").disabled=false;$("wifi-connect-b").textContent="Connect";$("wifi-form").style.display="block"}
$("wifi-manual").onclick=function(){wifiSelect({ssid:"",secured:true});$("wifi-ssid").readOnly=false;$("wifi-ssid").focus()};
$("wifi-connect-b").onclick=function(){
 var ssid=$("wifi-ssid").value.trim();if(!ssid)return;
 withPin(function(){
  $("wifi-connect-b").disabled=true;$("wifi-connect-b").textContent="Connecting...";
  xhrJson("POST","/wificonnect",function(r,st,body){
   if(st==401||st==429){$("wifi-connect-b").disabled=false;$("wifi-connect-b").textContent="Connect";alert((body&&body.message)||"PIN refused")}
   refresh()},{ssid:ssid,password:$("wifi-pass").value})})};
hook("api",function(d){
 if(!d.wifi)return;
 var wl=WIFI_LABELS[d.wifi.state]||WIFI_LABELS.idle;
 $("wifi-b").textContent=wl[0];
 $("wifi-sub").textContent=((d.wifi.demo&&d.wifi.state=="hosting")?"Pick a network below":wl[1].replace("%s",d.wifi.ssid||""))+(d.wifi.demo?" - DEMO: dummy networks, password \u201cdemo\u201d connects":"");
 $("wifi-b").disabled=d.wifi.state=="ok";
 var showNets=d.wifi.state=="hosting"||d.wifi.state=="scanning";
 $("wifi-networks").style.display=showNets?"block":"none";
 if(showNets&&d.wifi.networks){var key=JSON.stringify(d.wifi.networks);
  if(key!=wifiListKey){wifiListKey=key;renderWifiList(d.wifi.networks)}}
 else if(!showNets){wifiListKey=null;wifiChosen=null;$("wifi-form").style.display="none";$("wifi-list").innerHTML=""}});
// the button row: which button, or both, held for 3 s starts Wi-Fi setup (saved with the other button settings)
hook("buttons",function(r){
 if(!$("wifi-btn-sel").options.length)$("wifi-btn-sel").innerHTML=r.wifi_choices.map(function(c){
  return '<option value="'+c[0]+'">'+esc(c[1])+'</option>'}).join("");
 $("wifi-btn-sel").value=btn.wifi_button});
$("wifi-btn-sel").onchange=function(){btn.wifi_button=this.value;saveButtons()};

// Start-up, last of all (after the modules' own scripts have registered their custom widgets and hooks): draw the layout,
// start the modules' data sources and backgrounds, then ask /api once a second.
renderLayout();startData();startBackgrounds();applyTheme();
refresh();setInterval(refresh,1000);
// back in Settings after switching or moving a module (the page was reloaded)
try{if(sessionStorage.getItem("netswitch-reopen")){sessionStorage.removeItem("netswitch-reopen");showSettings(true)}}catch(e){}

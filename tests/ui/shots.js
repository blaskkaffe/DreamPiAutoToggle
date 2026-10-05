// Screenshots of the whole dashboard and the whole Settings overlay at four widths, for before / after comparisons of a styling change:
//   node shots.js <output dir> [label]   (run against a demo server with every module on:
//   FAKEPLAYERS=1 CLOCK=1 EVENTS=1 EVENTSOON=1 WIFIDEMO=1 PORT=8791 python3 demo_server.py)
const { chromium } = require('playwright');
const fs = require('fs');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8791) + '/';
const out = process.argv[2], label = process.argv[3] || 'shot';
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch();
  for (const w of [360, 420, 768, 1280]) {
    const page = await browser.newPage({ viewport: { width: w, height: 900 } });
    page.on('dialog', d => d.accept());
    await page.goto(URL, { waitUntil: 'networkidle' }); await settle(2500);
    await page.addStyleTag({ content: '*{animation:none !important;transition:none !important;caret-color:transparent !important}' });
    await page.screenshot({ path: out + '/' + label + '-' + w + '-dashboard.png', fullPage: true });
    for (const box of ['.dbox[data-box="network"] .now', '.dbox[data-box="players"] .now', '.dbox[data-box="events"] .now', '.dbox[data-box="clock"] .now', '.dbox[data-box="debug log"] .now'])      // every box opened
      await page.locator(box).first().click({ position: { x: 20, y: 8 } }).catch(() => {});
    await settle(900);
    await page.screenshot({ path: out + '/' + label + '-' + w + '-dashboard-open.png', fullPage: true });
    await page.click('#cog'); await settle(1500);
    await page.locator('#settings .in').screenshot({ path: out + '/' + label + '-' + w + '-settings.png' });
    await page.close();
  }
  await browser.close();
})();

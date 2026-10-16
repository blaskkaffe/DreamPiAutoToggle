// The network box's Serial PPP and KOSnet rows (run by run.sh against two demo servers: CABLE=call has the rows, the other has no cable):
// they sit between Modem and Internet, show their text, and are not there without a cable.
const { chromium } = require('playwright');
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const errors = [];
  for (const [port, cable] of [[process.env.PORT_CABLE || 8752, true], [process.env.PORT_PLAIN || 8753, false]]) {
    const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
    page.on('pageerror', e => errors.push(String(e)));
    await page.goto('http://127.0.0.1:' + port + '/', { waitUntil: 'networkidle' }); await settle(1200);
    await page.locator('.now').first().click(); await settle(500);
    const labels = await page.evaluate(() => [...document.querySelectorAll('.now .row, .now .lab')].map(e => e.innerText.trim().split('\n')[0]));
    const text = await page.evaluate(() => document.querySelector('.now').innerText);
    const vis = l => page.evaluate(l => [...document.querySelectorAll('.now *')].some(e => e.children.length === 0 && e.innerText && e.innerText.trim() === l && e.offsetParent !== null), l);
    if (cable) {
      ok(await vis('Serial PPP') && await vis('KOSnet'), 'with a cable both rows are shown');
      ok(/Serial PPP[\s\S]*Connected[\s\S]*KOSnet[\s\S]*Ready[\s\S]*Internet/.test(text), 'in the order Modem, Serial PPP, KOSnet, Internet: ' + text.replace(/\n+/g, ' | '));
    } else {
      ok(!(await vis('Serial PPP')) && !(await vis('KOSnet')), 'without a cable neither row is shown');
    }
    await page.close();
  }
  ok(errors.length === 0, 'no JavaScript errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

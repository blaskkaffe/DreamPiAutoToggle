// The page keeps asking /api one question at a time and recovers by itself after an outage of the host (hung or refused answers):
// no pile-up of requests, and the first good answer after contact was lost for 10 s or more reloads the page.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8741) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(500);
  await page.evaluate(() => { window.__marker = 'same page'; });
  // an outage where the host takes the connection and never answers
  let seen = 0, hang = true;
  await page.route('**/api?*', route => { if (!hang) return route.continue(); seen++; /* never answered */ });
  await settle(16000);
  ok(seen <= 6, 'while the host does not answer, requests do not pile up (' + seen + ' in 16 s)');
  // the host answers again: after a long outage the page reloads itself
  hang = false; await page.unroute('**/api?*'); await settle(5000);
  ok(await page.evaluate(() => window.__marker) === undefined, 'the page reloaded itself when the host came back after a long outage');
  ok(await page.locator('.rp-r').count() > 0, 'and shows the board again');
  // a short blip does not reload
  await page.evaluate(() => { window.__marker = 'same page'; });
  let n = 0; await page.route('**/api?*', route => { n++; n <= 2 ? route.abort() : route.continue(); }); await settle(5000);
  ok(await page.evaluate(() => window.__marker) === 'same page', 'a short blip (2 failed answers) does not reload the page');
  // the host has a newer page program (an update): an open page loads it by itself
  await page.evaluate(() => { window.__marker = 'same page'; window.PAGE_V = 'an-old-version'; }); await settle(7000);
  ok(await page.evaluate(() => window.__marker) === undefined, 'a page with an old program version loads again by itself');
  ok(errors.length === 0, 'no JavaScript errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? 'FAILED' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

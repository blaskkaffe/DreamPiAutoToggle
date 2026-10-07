// Update from a USB stick (run by run.sh against a demo server started with FAKEUPDATE=1 USB=1): Settings > System shows a row for the update folder of the
// stick; Install from USB asks, then shows the running update.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8739) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 420, height: 1100 } });
  const errors = [], asked = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  page.on('dialog', d => { asked.push(d.message()); d.accept(); });
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1000);
  await page.click('#cog'); await settle(1500);
  const sys = page.locator('#set-boxes [data-box="system"]');
  const row = sys.locator('.srow', { hasText: 'Update from a USB stick' });
  ok(await row.count() === 1 && await row.isVisible(), 'a USB stick with an update folder gives an Update from a USB stick row');
  ok(/STICK/.test(await row.textContent()), 'which names the stick (' + (await row.textContent()).slice(0, 90).replace(/\s+/g, ' ') + ')');
  await row.locator('button', { hasText: 'Install from USB' }).click();
  let running = false;
  for (let i = 0; i < 10 && !running; i++) { await settle(500); running = await page.evaluate(() => !!(window.S.update && S.update.state === 'running')); }
  ok(asked.length === 1 && /USB/.test(asked[0]), 'it asks before it installs (' + asked.join(' | ') + ')');
  ok(running, 'and then shows the running update');
  ok(!(await row.isVisible()), 'and the row goes away while it runs');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

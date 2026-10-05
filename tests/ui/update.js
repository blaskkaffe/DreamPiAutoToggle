// The update controls in Settings > System (run by run.sh against a demo server started with FAKEUPDATE=1): pressing Check shows the
// result, and with it the Update now row, at once (not after a refresh of the page or the next timed read), pressing Update now shows
// the running update at once, and when an update this page watched has finished the page reloads with Settings still open.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8739) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 420, height: 1100 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  page.on('dialog', d => d.accept());
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1000);
  await page.click('#cog'); await settle(1200);
  const sys = page.locator('#set-boxes [data-box="system"]');
  const updRow = sys.locator('.srow', { hasText: 'Update the add-on' });
  ok(await updRow.count() === 0 || !(await updRow.first().isVisible()), 'before a check there is no Update now row');
  await sys.locator('.srow', { hasText: 'Updates' }).locator('button', { hasText: 'Check' }).click();
  let shown = false;
  for (let i = 0; i < 12 && !shown; i++) { await settle(500); shown = await updRow.count() > 0 && await updRow.first().isVisible(); }       // 6 s: far less than the timed read (30 s)
  ok(shown, 'pressing Check shows the Update now row as soon as the check has finished, without refreshing the page');
  await updRow.first().locator('button', { hasText: 'Update now' }).click();
  let running = false;
  for (let i = 0; i < 8 && !running; i++) { await settle(500); running = await page.evaluate(() => !!(window.S.update && S.update.state === 'running')); }
  ok(running, 'pressing Update now shows the running update at once');
  ok(!(await updRow.first().isVisible()), 'and the Update now row goes away while it runs');
  // the update finishes (the fake one never does, so say so): the page reloads itself, and Settings stays open
  const nav = page.waitForNavigation({ timeout: 8000 }).then(() => true, () => false);
  await page.evaluate(() => { S.update = Object.assign({}, S.update, { state: 'ok' }); fire('api', {}); });
  ok(await nav, 'a finished update reloads the page');
  await settle(1500);
  ok(await page.evaluate(() => document.getElementById('settings').classList.contains('open')), 'and Settings is still open after the reload');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

// How the page appears and how Settings lays out its boxes (run by run.sh against the events/clock demo server):
// the first draw waits for /api and the data, so the boxes appear together (no layout shift after that), and the Settings boxes stay in
// their columns when their content changes.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8736) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 420, height: 900 } });
  for (const visit of ['first visit', 'second visit (answers kept in the browser)']) {
    const page = await ctx.newPage();
    await page.addInitScript(() => {
      window.__shifts = [];
      new PerformanceObserver(l => l.getEntries().forEach(e => { if (!e.hadRecentInput) window.__shifts.push(e.value); })).observe({ type: 'layout-shift', buffered: true });
    });
    await page.goto(URL, { waitUntil: 'commit' }); await settle(3500);
    const shift = await page.evaluate(() => window.__shifts.reduce((a, b) => a + b, 0));
    ok(shift < 0.02, visit + ': nothing moves after the page is shown (layout shift ' + shift.toFixed(4) + ')');
    ok(await page.evaluate(() => !document.body.classList.contains('booting')), visit + ': the page is shown');
    await page.close();
  }
  // Settings on a wide screen: the boxes are placed in columns once and keep them
  const page = await ctx.newPage();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1500);
  await page.click('#cog'); await settle(1500);
  const cols = () => page.evaluate(() => Array.from(document.querySelectorAll('#set-boxes > .col')).map(c => Array.from(c.querySelectorAll(':scope > .sec[data-box]')).map(b => b.getAttribute('data-box'))));
  const c0 = await cols();
  ok(c0.length >= 2 && c0.every(c => c.length > 0), 'a wide Settings has ' + c0.length + ' columns, each with boxes: ' + JSON.stringify(c0));
  const order = await page.evaluate(() => Array.from(document.querySelectorAll('#set-boxes .sec[data-box]')).map(b => b.getAttribute('data-box')));
  ok(order.join() === c0.flat().join(), 'read down the columns the boxes are in the modules\' order');
  const hs = await page.evaluate(() => Array.from(document.querySelectorAll('#set-boxes > .col')).map(c => Math.round(c.getBoundingClientRect().height)));
  ok(Math.max(...hs) < Math.min(...hs) * 2.2, 'the columns are about as tall as each other (' + hs.join(', ') + ')');
  await page.locator('[data-box="check-in"] .srow', { hasText: 'Display roles' }).locator('button', { hasText: 'Edit' }).click(); await settle(500);   // content changes
  await page.keyboard.press('Escape'); await settle(300);
  ok(JSON.stringify(await cols()) === JSON.stringify(c0), 'a box that grows stays in its column');
  await page.click('#close-settings'); await settle(300); await page.click('#cog'); await settle(1200);
  ok(JSON.stringify(await cols()) === JSON.stringify(c0), 'and Settings opened again has the same columns');
  await page.setViewportSize({ width: 420, height: 900 }); await settle(500);
  ok((await cols()).length === 1, 'a phone gets one column');
  await page.setViewportSize({ width: 1280, height: 900 }); await settle(500);
  ok((await cols()).length === c0.length, 'and a wide window its columns again');
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

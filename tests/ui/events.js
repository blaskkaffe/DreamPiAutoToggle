// The DC99 events module and the page-wide highlight in a real browser (run by run.sh against a demo server started with
// CLOCK=1 EVENTS=1 EVENTSOON=1: the sample events, and one reminded event that starts in 5 minutes).
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8736) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 420, height: 1100 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(2000);
  // the reminder: a banner, the clock and the events box stand out
  const banner = page.locator('#warnings .notebox');
  ok(await banner.count() === 1 && /Demo Game Night/.test(await banner.textContent()), 'a reminded event that starts soon shows a banner');
  ok(await page.locator('.dbox[data-box="clock"].hl').count() === 1 && await page.locator('.dbox[data-box="events"].hl').count() === 1, 'the clock box and the events box are highlighted');
  const look = await page.locator('.dbox[data-box="clock"] .now').evaluate(e => getComputedStyle(e).animationName);
  ok(/hlrainbow/.test(look), 'the highlight is the animated rainbow by default (' + look + ')');
  ok(await page.locator('.dbox[data-box="players"].hl').count() === 0, 'other boxes are not highlighted');
  // the events box
  const box = page.locator('.dbox[data-box="events"] .now');
  ok(/Demo Game Night/.test(await box.locator(':scope > b').textContent()), 'the box names the next event');
  await box.click({ position: { x: 20, y: 10 } }); await settle(600);
  const rows = box.locator('.evr');
  ok(await rows.count() >= 5, 'opened, it lists the coming events (' + await rows.count() + ')');
  ok(await rows.first().locator('.bell[aria-pressed="true"]').count() === 1, 'the reminded event has its bell on');
  const second = rows.nth(1);
  const title = (await second.locator('.evt a, .evt').first().textContent()).trim();
  await second.locator('.bell').click(); await settle(900);
  ok(await rows.nth(1).locator('.bell[aria-pressed="true"]').count() === 1, 'a bell sets a reminder (' + title.slice(0, 30) + ')');
  await rows.nth(1).locator('.bell').click(); await settle(900);
  ok(await rows.nth(1).locator('.bell[aria-pressed="false"]').count() === 1, 'and clears it again');
  ok(await box.locator('.evs').isVisible() && /Synced/.test(await box.locator('.evs').textContent()), 'the box says when it last synced');
  // dismissing the banner ends the highlight
  await banner.locator('.nx').click(); await settle(1800);
  ok(await page.locator('#warnings .notebox').count() === 0, 'the banner can be dismissed');
  ok(await page.locator('.dbox.hl').count() === 0, 'and the boxes stop standing out');
  // the highlight look is a global setting
  await page.click('#cog'); await settle(900);
  const ap = page.locator('section[data-box="appearance"]');
  ok(await ap.locator('.srow', { hasText: 'Highlight' }).count() === 1, 'Appearance has the Highlight look');
  const ev = page.locator('section[data-box="events"]');
  ok(await ev.locator('.srow', { hasText: /^Reminder\d+ minutes before/ }).count() === 1 && await ev.locator('.wpicker').count() === 1, 'Settings has the reminder time and the series list');
  await page.click('#close-settings'); await settle(500);
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

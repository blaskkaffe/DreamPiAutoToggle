// The online players box while its list is fetched again (run by run.sh against a demo server started with FAKEPLAYERS=1 PLAYERSFAST=1:
// slow downloads, a list that is stale after 3 s): the box keeps what it shows and stays open, a small spinner shows next to the rows
// that are being refreshed, and the new list replaces the old one in one go.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8737) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 420, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(5000);
  const box = page.locator('.dbox[data-box="players"] .now');
  await box.click({ position: { x: 20, y: 10 } }); await settle(500);
  const state = () => box.evaluate(e => ({ open: e.classList.contains('open'), h: Math.round(e.getBoundingClientRect().height), n: e.querySelectorAll('.wlist .p').length,
    spin: Array.from(e.querySelectorAll('.spin')).filter(s => s.offsetParent).length, busy: !!(window.S.players && S.players.refreshing) }));
  const first = await state();
  ok(first.open && first.n >= 5 && first.spin === 0, 'the open box lists the players and shows no spinner while nothing is refreshed (' + first.n + ' rows)');
  let sawSpin = false, minH = first.h, closed = false, fewer = false;
  for (let i = 0; i < 70; i++) {                                   // a minute: at least one refresh happens in it
    const s = await state();
    if (s.spin > 0) sawSpin = true;
    if (s.busy && s.spin === 0) sawSpin = false;
    minH = Math.min(minH, s.h); closed = closed || !s.open; fewer = fewer || s.n < first.n;
    await settle(900);
  }
  ok(sawSpin, 'a spinner is shown next to the rows while the list is being fetched again');
  ok(!closed && minH >= first.h - 4, 'the box stays open and does not shrink while it refreshes (smallest ' + minH + 'px, was ' + first.h + 'px)');
  ok(!fewer, 'the old list stays until the new one replaces it');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

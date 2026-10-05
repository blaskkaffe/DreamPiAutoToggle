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
  const lk = await page.locator('.dbox[data-box="players"] .links.btns a').evaluateAll(els => els.map(e => Math.round(e.getBoundingClientRect().top)));
  ok(lk.length === 4 && new Set(lk).size === 1, 'the four links are buttons in one row (' + lk.join(',') + ')');
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
  // a page opened again shows the last list at once (kept in the browser), and no "Nobody ..." text before it knows anything
  await page.route('**/players', r => setTimeout(() => r.continue().catch(() => {}), 2500));      // the server answers slowly, as a Pi does: what the page knows has to show meanwhile
  await page.reload({ waitUntil: 'domcontentloaded' }); await settle(300);
  const at0 = await page.evaluate(() => ({ n: window.S.players && S.players.list ? S.players.list.length : -1, busy: !!(S.players && S.players.busy), empty: document.body.innerText.indexOf('Nobody is online') >= 0 }));
  ok(at0.n >= 5 && at0.busy && !at0.empty, 'a page opened again shows the last list at once, marked as being refreshed (' + at0.n + ' players, no "Nobody is online")');
  await page.unroute('**/players');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

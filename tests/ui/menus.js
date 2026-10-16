// The menus of Settings open in a pop-up (not under their row), the buttons are one size, the cogwheel can be hidden, and /settings opens Settings
// (asking for the PIN when one is set). Run by run.sh against its own demo server.
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:' + (process.env.PORT || 8741);
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [], alerts = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error' && !/status of (400|401|409)/.test(m.text())) errors.push(m.text().slice(0, 150)); });
  page.on('dialog', d => { alerts.push(d.message()); return d.accept(); });
  const post = (path, body, pin) => page.evaluate(([p, b, pn]) => fetch(p, { method: 'POST', headers: Object.assign({ 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, pn ? { 'X-Pin': pn } : {}), body: JSON.stringify(b || {}) }).then(r => r.status), [path, body, pin]);
  const enterPin = async pin => { await page.waitForSelector('.pinm .pinkey'); for (const c of pin) await page.click('.pinm [data-k="' + c + '"]'); await page.click('.pinm .pinok'); };
  const opened = () => page.evaluate(() => document.getElementById('settings').classList.contains('open'));
  await page.goto(BASE + '/', { waitUntil: 'networkidle' }); await settle(1200);
  await page.click('#cog'); await settle(1000);

  // a menu is a pop-up over the screen
  const layout = page.locator('.wmenu', { has: page.locator('.menuhead', { hasText: /^Layout/ }) });
  await layout.locator('.menubtn').click(); await settle(300);
  const box = await layout.locator('.msub').boundingBox();
  ok(box && box.x === 0 && box.y === 0 && box.width >= 1279 && box.height >= 999, 'a menu opens as a pop-up that covers the screen (' + JSON.stringify(box) + ')');
  const sheet = layout.locator('.rp-msheet'), sb = await sheet.boundingBox();
  ok(sb && Math.abs(sb.x + sb.width / 2 - 640) < 4 && sb.width < 800, 'its sheet is in the middle of the screen (' + Math.round(sb.x) + ', ' + Math.round(sb.width) + ' wide)');
  ok(/^Layout/.test(await sheet.locator('.rp-mt').textContent()) && await sheet.locator('.srow', { hasText: /Hide the cogwheel/ }).count() === 1, 'the sheet has the menu\'s name and its settings (Hide the cogwheel is one)');
  ok(await page.locator('.wmenu .msub.open').count() === 1, 'one menu is open');
  await page.keyboard.press('Escape'); await settle(300);
  ok(await page.locator('.wmenu .msub.open').count() === 0 && await opened(), 'Esc closes the menu, Settings stays open');
  await layout.locator('.menubtn').click(); await settle(200); await layout.locator('.rp-mx').click(); await settle(200);
  ok(await page.locator('.wmenu .msub.open').count() === 0, 'the cross closes it');
  await layout.locator('.menubtn').click(); await settle(200); await layout.locator('.bar button', { hasText: 'Done' }).click(); await settle(200);
  ok(await page.locator('.wmenu .msub.open').count() === 0, 'Done closes it');
  await layout.locator('.menubtn').click(); await settle(200); await page.mouse.click(5, 5); await settle(200);
  ok(await page.locator('.wmenu .msub.open').count() === 0, 'a tap outside closes it');
  const text = page.locator('.wmenu', { has: page.locator('.menuhead', { hasText: /^Text/ }) });
  await layout.locator('.menubtn').click(); await settle(200); await text.locator('.menubtn').evaluate(b => b.click()); await settle(200);
  ok(await page.locator('.wmenu .msub.open').count() === 1 && await text.locator('.msub.open').count() === 1, 'opening another menu closes the first');
  await page.keyboard.press('Escape'); await settle(200);

  // the buttons are one size
  const sizes = await page.locator('[data-box="appearance"] .menuhead .menubtn').evaluateAll(bs => bs.map(b => { const r = b.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height); }));
  ok(new Set(sizes).size === 1, 'the Edit buttons of the menus are all the same size (' + sizes[0] + ', ' + sizes.length + ' of them)');
  const rowBtns = await page.locator('#settings .srow > .pill-s, #settings .srow > span > .pill-s').evaluateAll(bs => bs.filter(b => b.offsetWidth).map(b => Math.round(b.getBoundingClientRect().width)));
  ok(Math.min.apply(null, rowBtns) >= 87, 'no button of a row is narrower than the minimum size (narrowest ' + Math.min.apply(null, rowBtns) + ' px of ' + rowBtns.length + ')');
  // every other Edit button opens the same kind of sheet
  for (const [box, row] of [['system', /^Time zone/], ['statuses', /^Statuses/], ['contacts', /^People/], ['appearance', /^Language/]]) {
    await page.locator('[data-box="' + box + '"] .srow', { hasText: row }).first().locator('button').click(); await settle(400);
    const g = await page.evaluate(() => { const p = document.querySelector('.pop.open'); if (!p) return null; const r = p.getBoundingClientRect();
      return { dx: Math.round(r.left + r.width / 2 - innerWidth / 2), dy: Math.round(r.top + r.height / 2 - innerHeight / 2), x: !!p.querySelector(':scope > .rp-mx'), inside: r.left >= 0 && r.right <= innerWidth && r.top >= 0 && r.bottom <= innerHeight }; });
    ok(g && Math.abs(g.dx) <= 2 && Math.abs(g.dy) <= 2 && g.x && g.inside, box + ': Edit opens a sheet in the middle of the screen with a cross (' + JSON.stringify(g) + ')');
    await page.locator('.pop.open > .rp-mx').click(); await settle(200);
    ok(await page.locator('.pop.open').count() === 0, box + ': the cross closes it');
  }
  const theme = page.locator('[data-box="appearance"] .srow', { hasText: /^Theme/ }).first();
  await theme.locator('button').click(); await settle(300);
  const tb = await page.locator('.pop.open .optrow .pill-s').evaluateAll(bs => bs.map(b => { const r = b.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height); }));
  ok(tb.length === 4 && new Set(tb).size === 1, 'the four Theme buttons are one size (' + tb.join(' ') + ')');
  const cols = await page.locator('.pop.open .optrow .pill-s').evaluateAll(bs => new Set(bs.map(b => Math.round(b.getBoundingClientRect().left))).size);
  ok(cols === 2, 'and laid out evenly in two columns (' + cols + ')');
  await page.keyboard.press('Escape'); await page.click('#close-settings'); await settle(300);

  // the cogwheel can be hidden; /settings opens Settings
  ok(await post('/screen/nocog', { value: true }) === 200, 'Hide the cogwheel is saved');
  await page.goto(BASE + '/', { waitUntil: 'networkidle' }); await settle(1200);
  ok(!(await page.locator('#cog').isVisible()), 'the cogwheel is gone');
  await page.goto(BASE + '/settings', { waitUntil: 'networkidle' }); await settle(1800);
  ok(await opened() && await page.locator('#settings:visible').count() === 1, '/settings opens Settings by itself');
  await page.click('#close-settings'); await settle(1200);
  ok(new URL(page.url()).pathname === '/' && !(await opened()), 'closing it goes back to the board at /');
  ok(await post('/screen/nocog', { value: false }) === 200, 'Hide the cogwheel can be switched off');

  // the top bar: hidden at the edge, it goes up again after use (also when the focus stays on its buttons); hidden completely it never shows
  ok(await post('/screen/autohide', { value: true }) === 200, 'Hide the top bar is on');
  await page.goto(BASE + '/', { waitUntil: 'networkidle' }); await settle(1200);
  const shown = () => page.evaluate(() => document.body.classList.contains('hdr-show'));
  await page.mouse.move(640, 3); await settle(400);
  ok(await shown(), 'the bar comes down at the top edge');
  await page.mouse.move(640, 3); await page.click('#cog'); await settle(900); await page.evaluate(() => showSettings(false)); await page.mouse.move(640, 500); await settle(7000);      // tapped the cogwheel: it keeps the focus (not keyboard focus)
  ok(!(await shown()), 'and goes up again after a few seconds although the cogwheel still has the focus');
  ok(await post('/screen/nobar', { value: true }) === 200, 'Hide the top bar completely is on');
  await page.goto(BASE + '/', { waitUntil: 'networkidle' }); await settle(1200);
  await page.mouse.move(640, 3); await settle(500);
  ok(!(await page.locator('body > header').isVisible()) && !(await page.locator('#cog').isVisible()), 'the bar is not there, not even at the edge');
  await page.goto(BASE + '/settings', { waitUntil: 'networkidle' }); await settle(1800);
  ok(await opened(), '/settings still opens Settings');
  await page.click('#close-settings'); await settle(800);
  ok(await post('/screen/nobar', { value: false }) === 200 && await post('/screen/autohide', { value: false }) === 200, 'the bar is back to normal');

  // with a PIN set /settings asks for it
  ok(await post('/pin', { pin: '4821' }) === 200, 'a PIN is set');
  await page.goto(BASE + '/settings', { waitUntil: 'networkidle' }); await settle(1500);
  ok(await page.locator('.pinm .pinkey').count() === 12 && !(await opened()), '/settings asks for the PIN first');
  await enterPin('1111'); await settle(1200);
  ok(!(await opened()) && alerts.length >= 1, 'a wrong PIN does not open it (' + alerts[0] + ')');
  await page.waitForSelector('.pinm .pinkey'); await enterPin('4821'); await settle(1500);
  ok(await opened(), 'the right PIN opens it');
  await page.goto(BASE + '/settings', { waitUntil: 'networkidle' }); await settle(1500);
  await page.keyboard.press('Escape'); await settle(1500);
  ok(new URL(page.url()).pathname === '/' && !(await opened()), 'cancelling the PIN pad goes back to the board');
  ok(await post('/pin', { pin: '' }, '4821') === 200, 'the PIN is removed again');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  await browser.close(); process.exit(failed ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });

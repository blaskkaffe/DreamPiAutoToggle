// The screen layout and the lock on Settings (run by run.sh against its own demo server): Appearance > Max columns (dashboard and Settings),
// Stretch boxes, Scale content, the white cogwheel, and the PIN that Settings asks for when it is switched on.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8741) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error' && !/status of (401|409)/.test(m.text())) errors.push(m.text().slice(0, 150)); });     // the refused requests of the PIN checks are expected
  let prompts = [], alerts = [];
  page.on('dialog', d => { if (d.type() === 'prompt') { prompts.push(d.message()); return d.accept(answers.shift() || ''); } alerts.push(d.message()); return d.accept(); });
  const answers = [];
  const post = (path, body, pin) => page.evaluate(([p, b, pn]) => fetch(p, { method: 'POST', headers: Object.assign({ 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, pn ? { 'X-Netswitch-Pin': pn } : {}), body: JSON.stringify(b || {}) }).then(r => r.status), [path, body, pin]);
  const load = async () => { await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1200); };
  const info = () => page.evaluate(() => {
    const d = document.getElementById('dash'), cols = d.querySelectorAll(':scope > .dcol'), b = document.body;
    const boxes = Array.from(d.querySelectorAll('.dbox')).filter(x => x.offsetHeight);
    return { cols: cols.length, bodyMax: b.style.maxWidth, dashW: Math.round(d.getBoundingClientRect().width), zoom: getComputedStyle(boxes[0]).zoom,
             boxW: Math.round(boxes[0].getBoundingClientRect().width), n: boxes.length, inCols: cols.length ? Array.from(cols).map(c => c.querySelectorAll('.dbox').length) : [] };
  });
  await load();
  // ---- the defaults: one column, as before
  let i = await info();
  ok(i.cols === 0 && i.bodyMax === '460px', 'by default the dashboard is one column of the usual width (' + JSON.stringify(i) + ')');
  ok(await page.evaluate(() => getComputedStyle(document.getElementById('cog')).color) === 'rgb(238, 238, 238)', 'the settings cogwheel is white like the text');
  // ---- max columns
  ok(await post('/screen', { values: { dash_cols: 3, set_cols: 6 } }) === 200, 'Max columns are saved');
  await load(); i = await info();
  ok(i.cols === 3 && i.inCols.reduce((a, b) => a + b, 0) === i.n && Math.max.apply(null, i.inCols) - Math.min.apply(null, i.inCols) <= 2, 'three dashboard columns with the boxes shared out (' + i.inCols + ')');
  ok(i.bodyMax === (3 * 428 + 2 * 20 + 32) + 'px' && i.dashW <= 3 * 428 + 40, 'not stretched: the columns keep their usual width (' + i.dashW + ' px)');
  await page.setViewportSize({ width: 800, height: 900 }); await settle(500); i = await info();
  ok(i.cols === 0, 'a screen that fits one column only gets one, however many are allowed (800 px)');
  await page.setViewportSize({ width: 1000, height: 900 }); await settle(500); i = await info();
  ok(i.cols === 2, 'and two where two fit (1000 px)');
  await page.setViewportSize({ width: 1500, height: 900 }); await settle(500);
  // ---- stretch
  ok(await post('/screen/stretch', { value: true }) === 200, 'Stretch boxes saved');
  await settle(1500); i = await info();
  ok(i.bodyMax === 'none' && i.dashW >= 1500 - 2 * 24 - 4, 'stretched: the columns fill the width with a little room at the edges (' + i.dashW + ' px)');
  ok(i.zoom === '1', 'without Scale content the boxes only get wider (zoom ' + i.zoom + ')');
  ok(await post('/screen/scale', { value: true }) === 200, 'Scale content saved');
  await settle(1500); i = await info();
  const want = ((1500 - 48 - 40) / 3) / 428;
  ok(Math.abs(parseFloat(i.zoom) - want) < 0.02 && i.zoom !== '1', 'with Scale content the boxes are drawn bigger in step with their width (zoom ' + i.zoom + ', wanted ' + want.toFixed(2) + ')');
  ok(Math.abs(i.boxW - (1500 - 48 - 40) / 3) <= 2, 'each box is as wide as its column (' + i.boxW + ' px)');
  await page.setViewportSize({ width: 420, height: 900 }); await settle(600); i = await info();
  ok(i.cols === 0 && i.zoom === '1', 'a phone stays one column at its normal size');
  await page.setViewportSize({ width: 1500, height: 900 }); await settle(600);
  // ---- Settings in columns, and a pop-up inside a scaled box
  await page.click('#cog'); await settle(1500);
  const sc = await page.evaluate(() => ({ cols: document.querySelectorAll('#set-boxes > .col').length, z: getComputedStyle(document.querySelector('#set-boxes .sec')).zoom }));
  ok(sc.cols === 3 && sc.z !== '1', 'Settings: six allowed, three fit, stretched and scaled (' + JSON.stringify(sc) + ')');
  const app = page.locator('[data-box="appearance"]');
  await app.locator('.srow', { hasText: 'Network Selector colour' }).locator('.colourpick > button').click(); await settle(500);
  const geo = await page.evaluate(() => { const p = document.querySelector('.pop.open'), c = p.closest('.card').getBoundingClientRect(), r = p.getBoundingClientRect(), a = p.closest('.card').querySelector('.colourpick > button').getBoundingClientRect();
    return { l: r.left - c.left, rr: c.right - r.right, below: r.top - a.bottom }; });
  ok(Math.abs(geo.l - 16 * 1.0) < 40 && geo.rr >= -1 && geo.l >= -1 && geo.below > -4 && geo.below < 40, 'a pop-up in a scaled box sits under its button and inside the card (' + JSON.stringify(geo) + ')');
  await page.keyboard.press('Escape'); await settle(300);
  // the rows
  ok(await app.locator('.srow', { hasText: 'Max columns: dashboard' }).count() === 1 && await app.locator('.srow', { hasText: 'Stretch boxes' }).count() === 1, 'Appearance has the Max columns and Stretch boxes rows');
  ok(await app.locator('.srow', { hasText: 'Scale content' }).isVisible(), 'Scale content shows while Stretch is on');
  await page.click('#close-settings'); await settle(400);
  ok(await post('/screen/stretch', { value: false }) === 200 && await post('/screen', { values: { dash_cols: 1, set_cols: 4 } }) === 200, 'back to the defaults');
  await settle(1500); await load(); i = await info();
  ok(i.cols === 0 && i.bodyMax === '460px' && i.zoom === '1', 'and the dashboard is as it was (' + JSON.stringify(i) + ')');
  // ---- the PIN on Settings
  ok(await post('/settings-pin', { value: true }) === 409, 'the lock cannot be turned on without a PIN');
  ok(await post('/pin', { pin: '4821' }) === 200 && await post('/settings-pin', { value: true }) === 200, 'a PIN is set and Settings is locked');
  await load();
  answers.push('0000'); await page.click('#cog'); await settle(900);
  ok(prompts.length === 1 && /PIN/.test(prompts[0]) && alerts.length === 1 && !(await page.evaluate(() => document.getElementById('settings').classList.contains('open'))), 'a wrong PIN does not open Settings (' + alerts[0] + ')');
  answers.push('4821'); await page.click('#cog'); await settle(1500);
  ok(await page.evaluate(() => document.getElementById('settings').classList.contains('open')), 'the right PIN opens it');
  await page.click('#close-settings'); await settle(400);
  answers.push('4821'); const before = prompts.length; await page.click('#cog'); await settle(1000);
  ok(prompts.length === before + 1, 'closing Settings locks it again: the cog asks again');
  await page.click('#close-settings'); await settle(300);
  ok(await post('/colour', { module: 'switcher', key: 'dcnow', colour: 'green' }) === 401, 'a request for a setting without the PIN is refused by the service');
  ok(await post('/dcnet', {}) === 204 && await post('/dcnow', {}) === 204, 'the network buttons still work without it');
  ok(await post('/pin', { pin: '' }, '4821') === 200 && await post('/colour', { module: 'switcher', key: 'dcnow', colour: 'green' }) === 200, 'removing the PIN removes the lock');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

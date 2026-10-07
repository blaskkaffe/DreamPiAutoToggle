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
  page.on('console', m => { if (m.type() === 'error' && !/status of (400|401|409)/.test(m.text())) errors.push(m.text().slice(0, 150)); });     // the refused requests of the PIN checks are expected
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
  await app.locator('.srow', { hasText: 'Check-in board colour' }).locator('.colourpick > button').click(); await settle(500);
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
  // ---- rearranging the main screen
  await page.setViewportSize({ width: 1500, height: 2000 });
  const tiles = () => page.evaluate(() => Array.from(document.querySelectorAll('#dash .dbox')).filter(b => b.offsetHeight).map(b => b.getAttribute('data-box')));
  const seq = () => page.evaluate(() => Array.from(document.querySelectorAll('#dash .dbox')).filter(b => b.offsetHeight).sort((a, b) => a._ord - b._ord).map(b => b.getAttribute('data-box')));
  const modList = () => page.evaluate(() => fetch('/modules').then(r => r.json()).then(j => j.modules.map(m => m.name + ':' + m.group)));
  ok((await page.locator('#dash .tilegrip:visible').count()) === 0, 'no handles on the tiles until the setting is on');
  ok(await post('/screen/drag', { value: true }) === 200, 'Rearrange the main screen saved');
  await settle(1500);
  const n0 = (await tiles()).length;
  ok(n0 >= 4 && await page.locator('#dash .tilegrip:visible').count() === n0, 'every tile has a handle (' + n0 + ')');
  const drag = async (fromIdx, toIdx, below) => {
    const g = await page.evaluate(i => { const t = Array.from(document.querySelectorAll('#dash .dbox')).filter(b => b.offsetHeight).sort((a, b) => a._ord - b._ord)[i].querySelector('.tilegrip').getBoundingClientRect(); return { x: t.left + t.width / 2, y: t.top + t.height / 2 }; }, fromIdx);
    const d = await page.evaluate(([i, below]) => { const r = Array.from(document.querySelectorAll('#dash .dbox')).filter(b => b.offsetHeight).sort((a, b) => a._ord - b._ord)[i].getBoundingClientRect(); return { x: r.left + r.width / 2, y: below ? r.bottom - 4 : r.top + 4 }; }, [toIdx, !!below]);
    await page.mouse.move(g.x, g.y); await page.mouse.down(); await page.mouse.move((g.x + d.x) / 2, (g.y + d.y) / 2, { steps: 4 }); await page.mouse.move(d.x, d.y, { steps: 4 });
    const bar = await page.evaluate(() => getComputedStyle(document.querySelector('.dropbar')).display);
    await page.mouse.up(); await settle(1200); return bar;
  };
  let before = await seq();
  const bar = await drag(before.length - 1, 0, false);
  let after = await seq();
  ok(bar === 'block', 'a bar shows where the tile will land');
  ok(after[0] === before[before.length - 1] && after.slice(1).join() === before.slice(0, -1).join(), 'dragging the last tile above the first moves it to the top (' + after.join(' ') + ')');
  const mods = await modList();
  ok(mods.map(x => x.split(':')[1]).join('').match(/^0*1*2*$/) !== null, 'the modules stay grouped: dashboard ones, settings-only ones, backgrounds (' + mods.join(' ') + ')');
  await load(); await settle(800);
  ok((await seq()).join() === after.join(), 'after a reload the tiles are where they were put');
  // in several columns: a tile dropped after another one in a different column
  await post('/screen', { values: { dash_cols: 3, set_cols: 4 } }); await load(); await settle(500);
  before = await seq();
  await drag(0, 2, true); after = await seq();
  ok(after.join() !== before.join() && after.slice().sort().join() === before.slice().sort().join() && after[2] === before[0], 'three columns: a tile dropped after the third one is third (' + after.join(' ') + ')');
  // the keyboard
  const firstBox = (await seq())[0];
  await page.locator('#dash .dbox[data-box="' + firstBox + '"] .tilegrip').focus(); await page.keyboard.press('ArrowRight'); await settle(1000);
  ok((await seq())[1] === firstBox, 'an arrow key moves a tile one place on');
  ok(await post('/screen/drag', { value: false }) === 200, 'switched off again'); await settle(1500);
  ok(await page.locator('#dash .tilegrip:visible').count() === 0, 'and the handles are gone');
  await post('/screen', { values: { dash_cols: 1, set_cols: 4 } });
  // ---- the PIN on Settings
  ok(await post('/settings-pin', { value: true }) === 409, 'the lock cannot be turned on without a PIN');
  await post('/screen/drag', { value: true });
  ok(await post('/pin', { pin: '4821' }) === 200 && await post('/settings-pin', { value: true }) === 200, 'a PIN is set and Settings is locked');
  await load();
  ok(await page.locator('#dash .tilegrip:visible').count() === 0, 'while Settings is locked the tiles have no handles (moving them would change settings)');
    answers.push('0000'); await page.click('#cog'); await settle(900);
  ok(prompts.length === 1 && /PIN/.test(prompts[0]) && alerts.length === 1 && !(await page.evaluate(() => document.getElementById('settings').classList.contains('open'))), 'a wrong PIN does not open Settings (' + alerts[0] + ')');
  answers.push('4821'); await page.click('#cog'); await settle(1500);
  ok(await page.evaluate(() => document.getElementById('settings').classList.contains('open')), 'the right PIN opens it');
  await page.click('#close-settings'); await settle(400);
  answers.push('4821'); const asked0 = prompts.length; await page.click("#cog"); await settle(1000);
  ok(prompts.length === asked0 + 1, 'closing Settings locks it again: the cog asks again');
  await page.click('#close-settings'); await settle(300);
  ok(await post('/colour', { module: 'checkin', key: 'checkin', colour: 'blue' }) === 401, 'a request for a setting without the PIN is refused by the service');
  ok(await post('/checkin/toggle', { id: 'nobody' }) === 400, 'tapping people in and out still works without it (answered, not refused)');
  await post('/screen/drag', { value: false }, '4821');
  ok(await post('/pin', { pin: '' }, '4821') === 200 && await post('/colour', { module: 'checkin', key: 'checkin', colour: 'blue' }) === 200, 'removing the PIN removes the lock');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

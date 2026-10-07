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
  let alerts = [], pinDialogs = 0;
  page.on('dialog', d => { alerts.push(d.message()); return d.accept(); });
  // the PIN pad: round keys; type the digits on them and press OK
  const enterPin = async pin => { await page.waitForSelector('.pinm .pinkey'); pinDialogs++; for (const c of pin) await page.click('.pinm [data-k="' + c + '"]'); await page.click('.pinm .pinok'); };
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
  await page.click('#cog'); await enterPin('0000'); await settle(900);
  ok(pinDialogs === 1 && alerts.length === 1 && !(await page.evaluate(() => document.getElementById('settings').classList.contains('open'))), 'a wrong PIN does not open Settings (' + alerts[0] + ')');
  await page.click('#cog'); await enterPin('4821'); await settle(1500);
  ok(await page.evaluate(() => document.getElementById('settings').classList.contains('open')), 'the right PIN opens it');
  await page.click('#close-settings'); await settle(400);
  const asked0 = pinDialogs; await page.click('#cog'); await enterPin('4821'); await settle(1000);
  ok(pinDialogs === asked0 + 1, 'closing Settings locks it again: the cog asks again');
  await page.click('#close-settings'); await settle(300);
  await page.click('#cog'); await page.waitForSelector('.pinm .pinkey');
  ok(await page.locator('.pinm .pinkey').evaluateAll(els => els.length === 12 && els.every(e => getComputedStyle(e).borderRadius === '50%' || parseFloat(getComputedStyle(e).borderRadius) >= e.getBoundingClientRect().width / 2)), 'the PIN pad keys are round');
  await page.keyboard.press('Escape'); await settle(200);
  ok(await page.locator('.pinm').count() === 0, 'Esc closes the PIN pad');
  ok(await post('/colour', { module: 'checkin', key: 'checkin', colour: 'blue' }) === 401, 'a request for a setting without the PIN is refused by the service');
  ok(await post('/checkin/toggle', { id: 'nobody' }) === 400, 'tapping people in and out still works without it (answered, not refused)');
  await post('/screen/drag', { value: false }, '4821');
  ok(await post('/pin', { pin: '' }, '4821') === 200 && await post('/colour', { module: 'checkin', key: 'checkin', colour: 'blue' }) === 200, 'removing the PIN removes the lock');
  // ---- fit to screen: the main screen is as big as it can be without scrolling
  const room = () => page.evaluate(() => { const d = document.getElementById('dash').getBoundingClientRect(); return { z: parseFloat(getComputedStyle(document.querySelector('#dash .dbox')).zoom), bottom: Math.round(d.bottom + scrollY + 24), vh: innerHeight, scroll: document.documentElement.scrollHeight - innerHeight }; });
  await page.setViewportSize({ width: 600, height: 1400 }); await load(); let f = await room();
  ok(f.z === 1 && f.bottom < f.vh - 300, 'a tall window leaves empty space at the bottom without it (' + JSON.stringify(f) + ')');
  ok(await post('/screen/fit', { value: true }) === 200, 'Fit to screen saved'); await settle(1800); f = await room();
  ok(f.z > 1.1 && f.bottom <= f.vh && f.vh - f.bottom < 60 && f.scroll <= 0, 'the page is scaled up until its bottom reaches the bottom of the window, with no scrolling (' + JSON.stringify(f) + ')');
  await page.setViewportSize({ width: 600, height: 1200 }); await settle(1500); const f2 = await room();
  ok(f2.z < f.z && f2.bottom <= f2.vh && f2.vh - f2.bottom < 60, 'a shorter window gets a smaller scale (' + f2.z.toFixed(2) + ' < ' + f.z.toFixed(2) + ')');
  await page.setViewportSize({ width: 420, height: 300 }); await settle(1500); const f3 = await room();
  ok(f3.z === 1, 'a window too small for the page is not shrunk: it scrolls as usual (zoom ' + f3.z + ')');
  await page.setViewportSize({ width: 1500, height: 900 }); await settle(1500); const f4 = await room();
  ok(f4.z >= 1 && f4.bottom <= Math.max(f4.vh, f4.bottom), 'a wide window keeps its columns');
  ok(await post('/screen/fit', { value: false }) === 200, 'Fit to screen switched off'); await settle(1800);
  ok((await room()).z === 1, 'and the scale is back to 1');
  // ---- the theme
  const look = () => page.evaluate(() => ({ theme: document.documentElement.getAttribute('data-theme'), bg: getComputedStyle(document.body).backgroundColor, ink: getComputedStyle(document.body).color,
    box: getComputedStyle(document.querySelector('.dbox .now')).backgroundColor, boxInk: getComputedStyle(document.querySelector('.dbox .now')).color }));
  let t = await look();
  ok(t.theme === 'dark' && t.bg === 'rgb(17, 17, 17)', 'dark is the default (' + t.bg + ')');
  ok(await post('/screen', { values: { theme: 'light' } }) === 200, 'the theme is saved'); await load(); t = await look();
  ok(t.theme === 'light' && t.bg === 'rgb(236, 238, 242)' && t.ink === 'rgb(27, 28, 32)' && t.box === 'rgb(255, 255, 255)' && t.boxInk === 'rgb(27, 28, 32)', 'light: a light page with dark ink, and a white box with dark text (' + JSON.stringify(t) + ')');
  ok(await post('/screen', { values: { theme: 'auto' } }) === 200, 'auto is saved');
  await page.emulateMedia({ colorScheme: 'light' }); await load(); t = await look();
  ok(t.theme === 'light', 'auto follows a light device');
  await page.emulateMedia({ colorScheme: 'dark' }); await settle(500); t = await look();
  ok(t.theme === 'dark', 'and goes dark when the device does, without a reload');
  await post('/screen', { values: { theme: 'light' } }); await settle(1500);
  ok((await look()).theme === 'light', 'a change made elsewhere shows without a reload');
  await post('/screen', { values: { theme: 'dark' } }); await page.emulateMedia({ colorScheme: null }); await settle(1500);
  // ---- a setting that was saved is shown everywhere at once: after any successful POST the page asks /api and every data source again (not when their timers run out)
  await load(); await settle(1500);
  let asked = 0, askedApi = 0; page.on('request', r => { if (/\/players($|\?)/.test(r.url())) asked++; if (/\/api\?/.test(r.url())) askedApi++; });
  asked = 0; askedApi = 0;
  await page.evaluate(() => new Promise(res => post('/screen/drag', { value: false }, res))); await settle(700);
  ok(asked >= 1, 'a saved setting makes the data sources (here the Online players, which is read only once a minute) be read again at once (' + asked + ')');
  ok(askedApi >= 1, 'and /api too');
  asked = 0; await page.evaluate(() => { post('/wbtest', { colour: '#ffffff' }); }); await settle(700);
  ok(asked === 0, 'but not for the white-balance test, which posts every second');
  // switching "Ask for the PIN" on with no PIN set asks for a new one on the PIN pad, then locks Settings
  await load(); await page.click('#cog'); await settle(900);
  await page.locator('[data-box="appearance"] .srow:has-text("Ask for the PIN") input[type=checkbox]').click(); await enterPin('7315'); await enterPin('7315'); await settle(1200);
  ok(await page.evaluate(() => fetch('/api').then(r => r.json())).then(d => d.settings_pin.on && d.settings_pin.pin), 'switching the Settings lock on without a PIN asks for one on the PIN pad, and locks');
  ok(await post('/settings-pin', { value: false }, '7315') === 200 && await post('/pin', { pin: '' }, '7315') === 200, 'and it can be undone with that PIN');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

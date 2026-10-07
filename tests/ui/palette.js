// The colour palette editor in the browser (Settings > Appearance > Colour palette, run by run.sh against a demo server): change, add, rearrange, delete and reset
// colours, and the rest of the page (the colour picks, the boxes) follows at once, without reloading the page.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8743) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 430, height: 1400 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  page.on('dialog', d => d.accept());
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1000);
  await page.click('#cog'); await settle(1300);
  const app = page.locator('[data-box="appearance"]');
  const prow = app.locator('.srow', { hasText: 'Colour palette' });
  ok(await prow.count() === 1 && await prow.locator('button', { hasText: 'Edit' }).count() === 1, 'Appearance has a Colour palette row with an Edit button');
  ok(await page.locator('[data-box="palette"]').count() === 0 && await page.locator('[data-picker] >> text=Colour palette').count() === 0, 'it is part of the app, not a module of its own');
  const rows = page.locator('.pop.open .srow.pal');
  const openEditor = async () => { if (!(await page.locator('.pop.open .srow.pal').count())) { await prow.locator('button', { hasText: 'Edit' }).click(); await settle(700); } };
  const clockPick = () => app.locator('.srow', { hasText: 'Clock colour' }).locator('.colourpick > button');
  const balls = async () => { if (await page.locator('.pop.open').count()) { await page.keyboard.press('Escape'); await settle(200); } await clockPick().click(); await settle(300); const ids = await page.locator('.pop.open .swatch').evaluateAll(es => es.map(e => e.getAttribute('data-id'))); await page.keyboard.press('Escape'); await settle(200); return ids; };
  const order = () => rows.evaluateAll(es => es.map(e => e.getAttribute('data-id')));
  await openEditor();
  ok(await rows.count() === 15, 'the editor lists the 15 colours of the palette (' + await rows.count() + ')');
  ok(!(await order()).includes('network'), 'Selected network is not in it');
  let b = await balls();
  ok(b.length === 16 && b[b.length - 1] === 'network', 'the colour picks offer the palette and then Selected network, which the network switcher adds (' + b.length + ')');
  // ---- add and edit
  await openEditor();
  await page.locator('.pop.open button', { hasText: 'Add colour' }).click(); await settle(1200);
  ok(await rows.count() === 16, 'Add colour adds a row');
  const mine = page.locator('.pop.open .srow.pal[data-id="new-colour"]');
  await mine.locator('.pal-name').fill('Lime'); await mine.locator('.pal-name').dispatchEvent('change'); await settle(900);
  await mine.locator('input[type=color]').evaluate(e => { e.value = '#99ff00'; e.dispatchEvent(new Event('input', { bubbles: true })); }); await settle(1500);
  ok(await mine.locator('.pal-name').inputValue() === 'Lime' && await mine.locator('input[type=color]').inputValue() === '#99ff00', 'the new colour has its name and colour');
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  // ---- the rest of the page follows without a reload
  b = await balls();
  ok(b.includes('new-colour') && b.length === 17, 'the colour picks offer it at once, without reloading the page');
  await clockPick().click(); await settle(300); await page.locator('.pop.open .swatch[data-id="new-colour"]').click(); await settle(1800);
  const bg = await page.evaluate(() => getComputedStyle(document.querySelector('[data-box="appearance"] .srow .colourpick > button.c-new-colour')).backgroundColor);
  ok(/^rgba?\(153, 255, 0/.test(bg), 'a box can use it: the Clock colour button is lime (' + bg + ')');
  const border = await page.evaluate(() => getComputedStyle(document.querySelector('#dash .dbox[data-box="clock"] .now')).borderTopColor);
  ok(border === 'rgb(199, 255, 115)', 'the clock box on the main page is drawn in it too (' + border + ')');
  // ---- change a colour of the add-on and put it back
  await openEditor();
  const red = page.locator('.pop.open .srow.pal[data-id="red"]');
  ok(!(await red.locator('button[title^="Back"]').isVisible()), 'an unchanged colour has no Default button');
  await red.locator('input[type=color]').evaluate(e => { e.value = '#00ff00'; e.dispatchEvent(new Event('input', { bubbles: true })); }); await settle(1500);
  ok(await red.locator('button[title^="Back"]').isVisible(), 'a changed one has');
  ok(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--c-red').trim()) === '#00ff00', 'the page uses the new Red at once');
  await red.locator('button[title^="Back"]').click(); await settle(1200);
  ok(await red.locator('input[type=color]').inputValue() === '#d9363e' && !(await red.locator('button[title^="Back"]').isVisible()), 'and it goes back to its own colour');
  // ---- rearrange (the arrow keys on the handle, like the module list)
  const before = await order();
  await red.locator('.grip').focus(); await page.keyboard.press('ArrowDown'); await settle(1500);
  const after = await order();
  ok(after.indexOf('red') === before.indexOf('red') + 1, 'a colour moves down one place (' + after.slice(0, 4).join(' ') + ')');
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  b = await balls();
  ok(b.slice(0, after.length).join() === after.join() && b[b.length - 1] === 'network', 'and the colour picks follow the new order');
  // ---- delete
  await openEditor();
  ok(!(await page.locator('.pop.open .srow.pal[data-id="orange"] button[title^="Delete"]').isVisible()) && !(await page.locator('.pop.open .srow.pal[data-id="global"] button[title^="Delete"]').isVisible()), 'Orange and Global main have no Delete button');
  await page.locator('.pop.open .srow.pal[data-id="new-colour"] button[title^="Delete"]').click(); await settle(1800);
  ok(await rows.count() === 15, 'a colour of your own can be deleted');
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  ok(!(await balls()).includes('new-colour') && await page.evaluate(() => !document.querySelector('[data-box="appearance"] .srow .colourpick > button.c-new-colour')), 'it is gone from the colour picks, and what used it is back on its default (Clock: ' + await clockPick().getAttribute('class') + ')');
  await openEditor();
  await page.locator('.pop.open .srow.pal[data-id="cyan"] button[title^="Delete"]').click(); await settle(1800);
  ok(await rows.count() === 14, 'a colour of the add-on can be deleted too');
  // ---- reset
  await page.locator('.pop.open button', { hasText: 'Reset palette' }).click(); await settle(1800);
  ok(await rows.count() === 15 && (await order()).join() === 'global,red,orange,yellow,green,cyan,blue,purple,white,bright-red,bright-green,bright-cyan,bright-blue,bright-purple,bright-pink', 'Reset palette brings back the 15 colours in their order');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

// The Colour palette module in the browser (run by run.sh against a demo server): add / edit / rearrange / delete / reset colours in Settings, and the rest of the page
// (the colour picks, the boxes) follows at once, without reloading the page.
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
  const box = page.locator('[data-box="palette"]');
  const rows = box.locator('.srow[data-id]');
  ok(await box.count() === 1 && await rows.count() === 16, 'Settings has a Colour palette box with the 16 colours (' + await rows.count() + ')');
  const clockPick = () => page.locator('[data-box="appearance"] .srow', { hasText: 'Clock colour' }).locator('.colourpick > button');
  const balls = async () => { await clockPick().click(); await settle(300); const ids = await page.locator('.pop.open .swatch').evaluateAll(es => es.map(e => e.getAttribute('data-id'))); await page.keyboard.press('Escape'); await settle(200); return ids; };
  ok((await balls()).length === 16, 'a colour pick offers the whole palette (16)');
  // ---- add and edit
  await box.locator('button', { hasText: 'Add colour' }).click(); await settle(1200);
  ok(await rows.count() === 17 && await page.locator('.pop.open input[type=text]').count() === 1, 'Add colour adds a row and opens its editor');
  await page.locator('.pop.open input[type=text]').fill('Lime'); await page.locator('.pop.open input[type=text]').dispatchEvent('change'); await settle(900);
  await page.locator('.pop.open input[type=color]').first().evaluate(e => { e.value = '#99ff00'; e.dispatchEvent(new Event('input', { bubbles: true })); }); await settle(1500);
  const lime = box.locator('.srow[data-id="new-colour"]');
  ok(await lime.count() === 1 && /99ff00/.test(await lime.textContent()) && /Lime/.test(await lime.textContent()), 'the new colour is named and coloured in its row (' + (await lime.textContent()).trim().slice(0, 50) + ')');
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  // ---- the rest of the page follows without a reload
  ok((await balls()).includes('new-colour'), 'the colour picks offer it at once, without reloading the page');
  await clockPick().click(); await settle(300); await page.locator('.pop.open .swatch[data-id="new-colour"]').click(); await settle(1800);
  const bg = await page.evaluate(() => getComputedStyle(document.querySelector('[data-box="appearance"] .srow .colourpick > button.c-new-colour')).backgroundColor);
  ok(/^rgba?\(153, 255, 0/.test(bg), 'a box can use it: the Clock colour button is lime (' + bg + ')');
  const border = await page.evaluate(() => getComputedStyle(document.querySelector('#dash .dbox[data-box="clock"] .now')).borderTopColor);
  ok(border === 'rgb(199, 255, 115)', 'the clock box on the main page is drawn in it too (' + border + ')');
  // ---- change a shipped colour: everything that uses it changes
  await box.locator('.srow[data-id="red"] button.pill-s').click(); await settle(400);
  await page.locator('.pop.open input[type=color]').first().evaluate(e => { e.value = '#00ff00'; e.dispatchEvent(new Event('input', { bubbles: true })); }); await settle(1500);
  const redBall = await page.evaluate(() => getComputedStyle(document.querySelector('[data-box="palette"] .srow[data-id="red"] .swatch')).backgroundColor);
  ok(redBall === 'rgb(0, 255, 0)', 'Red can be changed (' + redBall + ')');
  await page.locator('.pop.open button', { hasText: 'Default' }).click(); await settle(1200);
  ok(await page.evaluate(() => getComputedStyle(document.querySelector('[data-box="palette"] .srow[data-id="red"] .swatch')).backgroundColor) === 'rgb(217, 54, 62)', 'and put back to its own colour with Default');
  // ---- rearrange (the arrow keys on the handle, like the module list)
  const order = () => rows.evaluateAll(es => es.map(e => e.getAttribute('data-id')));
  const before = await order();
  await box.locator('.srow[data-id="red"] .grip').focus(); await page.keyboard.press('ArrowDown'); await settle(1500);
  const after = await order();
  ok(after.indexOf('red') === before.indexOf('red') + 1, 'a colour moves down one place (' + after.slice(0, 4).join(' ') + ')');
  const b2 = await balls();
  ok(b2.join() === after.join(), 'and the colour picks follow the new order');
  // ---- delete
  await box.locator('.srow[data-id="new-colour"] button.pill-s').click(); await settle(400);
  ok(await page.locator('.pop.open button', { hasText: 'Delete' }).isVisible(), 'a colour of your own can be deleted');
  await page.locator('.pop.open button', { hasText: 'Delete' }).click(); await settle(1800);
  ok(await rows.count() === 16 && !(await balls()).includes('new-colour'), 'deleting it takes it out of the list and out of the colour picks');
  ok(await page.evaluate(() => !document.querySelector('[data-box="appearance"] .srow .colourpick > button.c-new-colour')), 'what used it is back on its default colour (Clock: ' + await clockPick().getAttribute('class') + ')');
  await box.locator('.srow[data-id="orange"] button.pill-s').click(); await settle(400);
  ok(!(await page.locator('.pop.open button', { hasText: 'Delete' }).isVisible()), 'Orange cannot be deleted (everything falls back to it)');
  await page.keyboard.press('Escape'); await settle(200);
  await box.locator('.srow[data-id="cyan"] button.pill-s').click(); await settle(400);
  await page.locator('.pop.open button', { hasText: 'Delete' }).click(); await settle(1800);
  ok(await rows.count() === 15, 'a colour of the add-on can be deleted too');
  // ---- reset
  await box.locator('button', { hasText: 'Reset palette' }).click(); await settle(1800);
  ok(await rows.count() === 16 && (await order()).join() === 'global,red,orange,yellow,green,cyan,blue,purple,teal,white,bright-red,bright-green,bright-cyan,bright-blue,bright-purple,bright-pink', 'Reset palette brings back the 16 colours in their order');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

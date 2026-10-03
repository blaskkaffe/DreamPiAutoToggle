// The clock module in a real browser (run by run.sh against a demo server started with CLOCK=1): the three lines of the box, the time
// zone map that a tap opens, the settings, and the clock's own colour.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8735) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 420, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1500);
  const box = page.locator('.dbox[data-box="clock"] .now');
  ok(await box.count() === 1, 'the clock is an info box like the network and players boxes');
  const time = async () => (await box.locator('b').textContent()).trim();
  ok(/^\d{2}:\d{2}:\d{2}$/.test(await time()), 'the middle line is the time in 24-hour form (' + await time() + ')');
  ok((await box.locator('.nlabel').textContent()).trim() === '' && await box.locator('.carousel .t').count() === 0, 'the top and bottom lines are empty to begin with');
  const t1 = await time(); await settle(1500);
  ok(t1 !== await time(), 'the time ticks');
  // settings: 12-hour, .beat and world time
  await page.click('#cog'); await settle(900);
  const sec = page.locator('section[data-box="clock"]');
  await sec.locator('.srow', { hasText: 'Time format' }).locator('button').click(); await settle(300);
  await page.locator('.pop.open select').selectOption({ label: '12-hour (AM/PM)' }); await settle(900);
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  await sec.locator('.srow', { hasText: '.beat time' }).locator('input').check(); await settle(900);
  await sec.locator('.srow', { hasText: 'World time' }).locator('input').check(); await settle(900);
  await page.click('#close-settings'); await settle(1800);
  ok(/^\d{1,2}:\d{2}:\d{2} (AM|PM)$/.test(await time()), 'the middle line follows the 12-hour setting (' + await time() + ')');
  ok(/^\.beat @\d{3}$/.test((await box.locator('.nlabel').textContent()).trim()), 'the top line shows the .beat time');
  ok(await box.locator('.carousel .t').count() > 0 && /Tokyo/.test(await box.locator('.carousel').first().textContent()), 'the bottom line lists world times');
  // the map
  ok(!(await box.locator('svg.cmap').isVisible()), 'the map is hidden until the box is tapped');
  await box.click({ position: { x: 20, y: 10 } }); await settle(500);
  ok(await box.locator('svg.cmap').isVisible() && await box.locator('svg.cmap .band').count() === 25, 'a tap opens the time zone map with its time zone bands');
  ok(await box.locator('svg.cmap .band.here').count() === 1 && await box.locator('svg.cmap .city').count() === 10 && await box.locator('svg.cmap .land').count() > 5, 'the Pi\'s band is marked and the cities are on the map');
  const w = await box.evaluate(e => ({ svg: e.querySelector('svg.cmap').getBoundingClientRect().width, row: e.querySelector('.mapw').getBoundingClientRect().width }));
  ok(w.svg > w.row * 0.95, 'the map is as wide as its row (' + Math.round(w.svg) + ' of ' + Math.round(w.row) + ')');
  // the colour
  await page.click('#cog'); await settle(900);
  await page.locator('[data-box="appearance"] .srow', { hasText: 'Clock colour' }).locator('button').first().click(); await settle(300);
  await page.locator('.pop.open .swatch[aria-label="Bright pink"]').click(); await settle(900);
  await page.click('#close-settings'); await settle(500);
  ok(await page.locator('.dbox[data-box="clock"].c-bright-pink').count() === 1, 'the clock takes the colour picked in Settings');
  // Selected network and Global main are colours too
  const clockPick = async name => { await page.click('#cog'); await settle(800);
    await page.locator('[data-box="appearance"] .srow', { hasText: 'Clock colour' }).locator('button').first().click(); await settle(300);
    await page.locator('.pop.open .swatch[aria-label="' + name + '"]').click(); await settle(900); await page.click('#close-settings'); await settle(500); };
  await page.click('#cog'); await settle(800);
  await page.locator('[data-box="appearance"] .srow', { hasText: 'Clock colour' }).locator('button').first().click(); await settle(300);
  const ids = await page.locator('.pop.open .swatch').evaluateAll(els => els.map(e => e.getAttribute('data-id')));
  ok(ids.length === 16 && ids[0] === 'global' && ids[8] === 'network' && ids[9] === 'white' && !ids.includes('pink') && !ids.includes('bright-orange'), 'the palette starts its rows with Global main and Selected network (' + ids.join(' ') + ')');
  await page.keyboard.press('Escape'); await page.click('#close-settings'); await settle(400);
  await clockPick('Selected network');
  const clockBox = page.locator('.dbox[data-box="clock"]');
  ok(await clockBox.evaluate(e => e.classList.contains('c-orange')), 'Selected network: the clock has the colour of DCNow!');
  await page.locator('.pill').nth(1).click(); await settle(2500);                       // DCNET / FLYCAST
  ok(await clockBox.evaluate(e => e.classList.contains('c-blue') && !e.classList.contains('c-orange')), 'and follows the switch to DCNET at once');
  await page.locator('.pill').nth(0).click(); await settle(2500);
  ok(await clockBox.evaluate(e => e.classList.contains('c-orange')), 'and back');
  await clockPick('Global main');
  ok(await clockBox.evaluate(e => e.classList.contains('c-global')), 'Global main: the clock takes it');
  await page.click('#cog'); await settle(800);
  await page.locator('[data-box="appearance"] .srow', { hasText: 'Global main colour' }).locator('input[type=color]').fill('#00aa55'); await settle(900);
  ok(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--c-global').trim()) === '#00aa55', 'the Global main picker changes the colour everywhere it is used at once');
  await page.click('#close-settings'); await settle(400);
  ok(await clockBox.locator('.now').evaluate(e => getComputedStyle(e).borderTopColor) === 'rgba(' + [0x00 + Math.round((255 - 0) * 0.45), 0xaa + Math.round((255 - 0xaa) * 0.45), 0x55 + Math.round((255 - 0x55) * 0.45)].join(', ') + ', 0.8)', 'and the border of the box is its lighter shade');
  // world time off: the map and the list go, the box stays
  await page.click('#cog'); await settle(900);
  await sec.locator('.srow', { hasText: 'World time' }).locator('input').uncheck(); await settle(900);
  await page.click('#close-settings'); await settle(1800);
  ok(await box.locator('.carousel .t').count() === 0 && !(await box.locator('svg.cmap').isVisible()), 'with world time off the list and the map are gone');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

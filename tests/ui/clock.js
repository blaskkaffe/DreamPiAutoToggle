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
  // the open box: each city with its time on one row, and the map of the real time zone areas
  ok(!(await box.locator('svg.cmap').isVisible()), 'the map is hidden until the box is tapped');
  await box.click({ position: { x: 20, y: 10 } }); await settle(1500);
  const rows = box.locator('.cwl .cwc');
  ok(await rows.count() === 10, 'the open box lists the ten default cities (' + await rows.count() + ')');
  const sp = await rows.filter({ hasText: 'São Paulo' }).first().evaluate(e => ({ h: e.getBoundingClientRect().height, line: parseFloat(getComputedStyle(e).lineHeight) || 20, t: e.textContent }));
  ok(sp.h < sp.line * 1.6 && /São Paulo\s*\d{1,2}:\d{2}/.test(sp.t), 'a city and its time stay together on one line (' + sp.t + ')');
  ok(!(await box.locator('.row.wcar').isVisible()), 'the scrolling line gives way to the list while the box is open');
  ok(await box.locator('svg.cmap').isVisible() && await box.locator('svg.cmap .sea').count() === 25, 'a tap opens the map with its sea bands');
  ok(await box.locator('svg.cmap g.z').count() > 50 && await box.locator('svg.cmap g.z.here').count() >= 1, 'the time zone areas are drawn and the clock\'s own time is highlighted');
  ok(await box.locator('svg.cmap .city').count() === 10 && await box.locator('svg.cmap .zl').count() > 20, 'the cities are dots and the areas show their hour');
  const w = await box.evaluate(e => ({ svg: e.querySelector('svg.cmap').getBoundingClientRect().width, row: e.querySelector('.mapw').getBoundingClientRect().width }));
  ok(w.svg > w.row * 0.95, 'the map is as wide as its row (' + Math.round(w.svg) + ' of ' + Math.round(w.row) + ')');
  // removing and adding a city, and the clock's own time zone
  await page.click('#cog'); await settle(900);
  await sec.locator('.tag', { hasText: 'Moscow' }).locator('button').click(); await settle(900);
  ok(await sec.locator('.tag', { hasText: 'Moscow' }).count() === 0 && await sec.locator('.wpicker .tag').count() === 9, 'a city is removed from the list');
  await sec.locator('.wpicker .srow', { hasText: 'Cities' }).locator('button.pill-s').first().click(); await settle(300);
  const opts = await page.locator('.pop.open select option').allTextContents();
  ok(opts.includes('Stockholm') && !opts.includes('Tokyo'), 'the Add pop-up offers the cities that are not in the list yet');
  await page.locator('.pop.open select').selectOption({ label: 'Stockholm' });
  await page.locator('.pop.open button', { hasText: 'Add' }).click(); await settle(900);
  ok(await sec.locator('.wpicker .tag', { hasText: 'Stockholm' }).count() === 1, 'a city is added');
  await sec.locator('.srow', { hasText: 'Time zone' }).locator('button').click(); await settle(300);
  const tk = (await page.locator('.pop.open select').last().locator('option').allTextContents()).filter(t => /^Tokyo/.test(t))[0];
  await page.locator('.pop.open select').last().selectOption({ label: tk }); await settle(900);
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  ok(/Tokyo/.test(await sec.locator('.srow', { hasText: 'Time zone' }).first().textContent()), 'the clock\'s time zone is set from the city list');
  await page.click('#close-settings'); await settle(1800);
  const tokyo = await page.evaluate(() => S.clock.cities.filter(c => c[0] === 'Tokyo').length);
  const shown = (await time()).replace(/:\d{2} (AM|PM)$/, ' $1');
  const tokyoNow = await page.evaluate(() => new Date().toLocaleTimeString('en-US', { timeZone: 'Asia/Tokyo', hour: 'numeric', minute: '2-digit' }));
  ok(shown === tokyoNow, 'the clock shows Tokyo time (' + shown + ' / ' + tokyoNow + ')');
  ok(tokyo === 1 && await box.locator('.cwl .cwc', { hasText: 'Stockholm' }).count() === 1, 'the list follows the settings');
  // the colour
  await page.click('#cog'); await settle(900);
  await page.locator('[data-box="appearance"] .srow', { hasText: 'Clock colour' }).locator('button').first().click(); await settle(300);
  await page.locator('.pop.open .swatch[aria-label="Pink"]').click(); await settle(900);
  await page.click('#close-settings'); await settle(500);
  ok(await page.locator('.dbox[data-box="clock"].c-pink').count() === 1, 'the clock takes the colour picked in Settings');
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

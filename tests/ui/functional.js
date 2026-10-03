// Functional check of the page in a real browser, against the demo server (sh tests/ui/run.sh runs it after the audit):
// the layout engine draws the modules' boxes and the standard widgets do what they say. Exits 1 on the first failed expectation.
const { chromium } = require('playwright');
const PORT = process.env.PORT || 8734;
const URL = 'http://127.0.0.1:' + PORT + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 420, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  page.on('dialog', d => d.accept());
  const settle = ms => page.waitForTimeout(ms || 1300);
  const openSettings = async () => { await page.click('#cog'); await settle(800); };
  const post = (path, body) => page.evaluate(([p, b]) => fetch(p, { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then(r => r.status), [path, body]);

  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1800);
  // ---- the dashboard comes from the layouts
  ok(await page.locator('.dbox').count() === 3, 'dashboard has the network, players and debug log boxes');
  ok((await page.locator('.now b').first().textContent()) === 'DCNow!', 'network box names the selected network');
  const pillColour = async n => page.locator('.pill').nth(n).evaluate(e => getComputedStyle(e).backgroundColor);
  const orange = await pillColour(0), blue = await pillColour(1);
  ok(orange !== blue, 'the two network buttons have different colours');
  // ---- the games carousel: centred while it fits (like the status row above it), scrolling when it doesn't
  ok(await page.locator('.carousel.sc').count() === 1, 'a long games line scrolls');
  await page.evaluate(() => { S.players = Object.assign({}, S.players, { games: ['Quake III (1)'] }); engineUpdate(); }); await settle(300);
  const geo = await page.evaluate(() => { const t = document.querySelector('.carousel .t').getBoundingClientRect(), b = document.querySelector('.now:nth-of-type(2), .dbox:nth-child(2) .now').getBoundingClientRect();
    return { off: Math.abs((t.left + t.right) / 2 - (b.left + b.right) / 2), sc: !!document.querySelector('.carousel.sc'), w: b.width }; });
  ok(!geo.sc && geo.off < 24, 'a short games line stands still and is centred in the box (off by ' + Math.round(geo.off) + 'px of ' + Math.round(geo.w) + ')');
  await page.evaluate(() => reloadData()); await settle(1200);
  // ---- choosing a network moves the primary colour with it
  const boxBg = () => page.locator('.now').first().evaluate(e => getComputedStyle(e).borderTopColor);
  const before = await boxBg();
  await page.locator('.pill').nth(1).click(); await settle(1800);
  ok((await page.locator('.now b').first().textContent()) === 'DCNET', 'DCNET button selects DCNET');
  ok((await boxBg()) !== before, 'the box border takes the DCNET colour');
  ok(await page.evaluate(() => document.body.classList.contains('c-blue')), "the page's primary colour is the selected network's (blue)");
  await page.locator('.pill').nth(0).click(); await settle(1500);
  ok(await page.evaluate(() => document.body.classList.contains('c-orange')), 'and back to orange for DCNow!');
  // ---- the module's own colour choice (swatches from the global palette)
  await openSettings();
  const colourBtn = page.locator('[data-box="network colours"] .colourpick > button').first();     // the DCNow! row
  ok(await colourBtn.evaluate(e => e.classList.contains('c-orange') && getComputedStyle(e).backgroundColor !== getComputedStyle(document.querySelector('.pill-s:not(.pri)')).backgroundColor), 'the Colour button shows the chosen colour (orange)');
  await colourBtn.click(); await settle(400);
  const swatches = page.locator('.pop.open .swatches .swatch');
  ok(await swatches.count() === 16, 'it opens a pop-up with the 16 palette colours');
  ok(await page.locator('.pop.open .swatch.sel').count() === 1 && await page.locator('.pop.open .swatch.sel').getAttribute('data-id') === 'orange', 'the current colour is marked');
  await swatches.nth(7).click(); await settle(1500);                       // pink (the 8 normal colours come first, then the bright ones)
  ok(await page.locator('.pop.open').count() === 0, 'picking a colour closes the pop-up');
  ok(await colourBtn.evaluate(e => e.classList.contains('c-pink')), 'and the Colour button takes it');
  ok(await page.locator('.pill').nth(0).evaluate(e => e.classList.contains('c-pink')), 'DCNow! button follows the picked colour');
  ok(await page.evaluate(() => document.body.classList.contains('c-pink')), 'and so does the page primary while DCNow! is selected');
  await colourBtn.click(); await settle(300); await page.locator('.pop.open .swatches .swatch').nth(1).click(); await settle(1200);   // back to orange
  // ---- the picker table (phone numbers)
  const group = page.locator('.wpicker .srow').first();
  await group.locator('button').first().click();
  await page.fill('.pop.open input', '5551234'); await page.click('.pop.open .pill-s'); await settle(900);
  ok(await page.locator('.wpicker .tag', { hasText: '5551234' }).count() === 1, 'a number is added to its group');
  await page.locator('.wpicker .tag', { hasText: '5551234' }).locator('button').click(); await settle(900);
  ok(await page.locator('.wpicker .tag', { hasText: '5551234' }).count() === 0, 'and removed again');
  // ---- a form that saves to the server (GPIO)
  const sel = page.locator('select[aria-label="Button 2 function"]');
  await sel.selectOption({ label: 'Select DCNET' }); await settle(900);
  ok(/DCNET/.test(await page.locator('[data-box="gpio"] .fsub').nth(1).textContent()), 'the description under Button 2 follows its function');
  await page.reload({ waitUntil: 'networkidle' }); await settle(800); await openSettings();
  ok((await page.locator('select[aria-label="Button 2 function"] option:checked').textContent()) === 'Select DCNET', 'the form value was saved');
  await page.locator('select[aria-label="Button 2 function"]').selectOption({ label: 'Off' }); await settle(700);
  // ---- shared boxes: wifi, system and the update rows are one box
  ok(await page.locator('[data-box="system"]').count() === 1, 'one System box is shared by several modules');
  ok(await page.locator('[data-box="gpio"] .wform').count() >= 2, 'and one GPIO box holds the forms of the buttons and the LED');
  // ---- the module picker: drag a module by its handle, move one with the keyboard, switch one off
  const order = async () => page.locator('[data-box="modules"] .srow[data-id]').evaluateAll(els => els.map(e => e.getAttribute('data-id')));
  const grip = n => page.locator('[data-box="modules"] .srow[data-id] .grip').nth(n);
  const drag = async (from, to) => {                                       // from / to are row numbers; the pointer ends on the lower half of `to`
    await grip(Math.min(from, to)).scrollIntoViewIfNeeded();
    const a = await grip(from).boundingBox(), rows = page.locator('[data-box="modules"] .srow[data-id]');
    const b = await rows.nth(to).boundingBox();
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2); await page.mouse.down();
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2 + (from < to ? 5 : -5), { steps: 3 });
    await page.mouse.move(a.x + a.width / 2, from < to ? b.y + b.height - 4 : b.y + 4, { steps: 12 });
    return a;
  };
  const before0 = await order();
  await drag(0, 1);
  ok(JSON.stringify(await order()) !== JSON.stringify(before0) && await page.locator('[data-box="modules"] .srow.drag').count() === 1, 'dragging a row moves it while the others make room');
  await page.mouse.up(); await page.waitForLoadState('networkidle'); await settle(1500);
  const after = await order();
  ok(after[0] === before0[1] && after[1] === before0[0], 'dropping saves the new order (the page reloads in Settings)');
  ok(await page.locator('#settings.open').count() === 1, 'and Settings stays open');
  await drag(1, 0); await page.mouse.up(); await page.waitForLoadState('networkidle'); await settle(1500);
  ok(JSON.stringify(await order()) === JSON.stringify(before0), 'and a drag back restores it');
  await drag(0, 2); await page.keyboard.press('Escape');
  ok(JSON.stringify(await order()) === JSON.stringify(before0) && await page.locator('[data-box="modules"] .srow.drag').count() === 0, 'Esc while dragging cancels');
  await page.mouse.up(); await settle(500);
  await grip(0).focus(); await page.keyboard.press('ArrowDown'); await settle(1300); await page.waitForLoadState('networkidle'); await settle(1200);
  ok((await order())[0] === before0[1], 'the arrow keys on a handle move the row too');
  await grip(1).focus(); await page.keyboard.press('ArrowUp'); await settle(1300); await page.waitForLoadState('networkidle'); await settle(1200);
  ok(JSON.stringify(await order()) === JSON.stringify(before0), 'and back');
  ok(await page.locator('[data-box="modules"] .mv').count() === 0, 'there are no arrow buttons any more');
  const players = page.locator('[data-box="modules"] input[data-module="players"]');
  await players.uncheck(); await page.waitForLoadState('networkidle'); await settle(1500);
  await page.click('#close-settings');
  ok(await page.locator('.dbox').count() === 2 && await page.locator('text=Online players:').count() === 0, 'a module switched off disappears from the dashboard');
  await openSettings();
  await page.locator('[data-box="modules"] input[data-module="players"]').check(); await page.waitForLoadState('networkidle'); await settle(1200);
  await page.click('#close-settings'); await settle(500);
  ok(await page.locator('text=Online players:').count() === 1, 'and comes back when switched on');
  // ---- the debug log expander
  await page.click('.xpand button.wide'); await settle(500);
  ok(await page.locator('.xpand .xbody').isVisible(), 'the debug log bar opens');
  await page.locator('.xpand .xbody button', { hasText: 'Recording' }).click(); await settle(1500);
  ok(/Recording$/.test((await page.locator('.xpand .xbody button').first().textContent()).trim()) && /●/.test(await page.locator('.xpand .xbody button').first().textContent()), 'Recording switches on');
  await page.locator('.xpand .xbody button', { hasText: 'Recording' }).click(); await settle(900);
  // ---- no errors anywhere
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

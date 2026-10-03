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
  // ---- the two network buttons keep their own colours whichever network is selected
  const pillCols = async () => page.locator('.pill').evaluateAll(els => els.map(e => getComputedStyle(e).backgroundColor + '|' + e.className));
  const pc0 = await pillCols();
  await page.locator('.pill').nth(1).click(); await settle(1800);
  const pc1 = await pillCols();
  ok(pc0.join() === pc1.join(), 'selecting DCNET changes neither button (' + pc0.map(x => x.split('|')[0]).join(' / ') + ')');
  await page.locator('.pill').nth(0).click(); await settle(1500);
  // ---- the module's own colour choice (swatches from the global palette)
  await openSettings();
  const colourBtn = page.locator('[data-box="appearance"] .colourpick > button').first();     // the DCNow! row
  ok(await colourBtn.evaluate(e => e.classList.contains('c-orange') && getComputedStyle(e).backgroundColor !== getComputedStyle(document.querySelector('.pill-s:not(.pri)')).backgroundColor), 'the Colour button shows the chosen colour (orange)');
  await colourBtn.click(); await settle(400);
  const swatches = page.locator('.pop.open .swatches .swatch');
  const popGeo = async () => page.evaluate(() => { const p = document.querySelector('.pop.open'), c = p.closest('.card'), cs = getComputedStyle(c), pr = p.getBoundingClientRect(), cr = c.getBoundingClientRect();
    return { left: Math.round(pr.left - cr.left - parseFloat(cs.paddingLeft)), right: Math.round(cr.right - parseFloat(cs.paddingRight) - pr.right), w: Math.round(pr.width) }; });
  const gp1 = await popGeo();
  ok(Math.abs(gp1.left) <= 1 && Math.abs(gp1.right) <= 1, 'the colour pop-up spans the card between its left and right padding (' + JSON.stringify(gp1) + ')');
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
  const gp2 = await popGeo();
  ok(Math.abs(gp1.w - gp2.w) <= 1, 'and every pop-up has the same width (' + gp1.w + ' and ' + gp2.w + ')');
  ok(Math.abs(gp2.left) <= 1 && Math.abs(gp2.right) <= 1, 'the add-number pop-up does too');
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
  const boxIds = await page.locator('#set-boxes [data-box]').evaluateAll(els => els.map(e => e.getAttribute('data-box')));
  ok(boxIds.slice(-2).join() === 'about,system', 'Settings ends with About and System (last): ' + boxIds.join(' | '));
  ok(boxIds.includes('appearance') && !boxIds.includes('modules') && !boxIds.includes('network colours'), 'the colours are in Appearance, and the modules have no box of their own');
  ok(await page.locator('[data-box="gpio"] .wform').count() >= 2, 'and one GPIO box holds the forms of the buttons and the LED');
  // ---- Appearance also has the Dreamcast background's switch (the module is off in the demo)
  const bgToggle = page.locator('[data-box="appearance"] input[type=checkbox]');
  ok(await bgToggle.count() === 1 && !(await bgToggle.isChecked()), 'Appearance has a switch for the Dreamcast background, off');
  await bgToggle.check(); await page.waitForLoadState('networkidle'); await settle(2000);
  ok(await page.evaluate(() => document.body.classList.contains('dcbg') && !!document.getElementById('dcbg')), 'switching it on draws the background (the page was rebuilt with Settings open)');
  ok(await page.locator('#settings.open').count() === 1 && await page.locator('[data-box="appearance"] input[type=checkbox]').isChecked(), 'and the switch stays on');
  await page.locator('[data-box="appearance"] input[type=checkbox]').uncheck(); await page.waitForLoadState('networkidle'); await settle(2000);
  ok(await page.evaluate(() => !document.body.classList.contains('dcbg')), 'and off again');
  // ---- the module picker: one row in System with an Edit button; the pop-up holds the list; nothing is applied until Done
  const edit = page.locator('[data-box="system"] [data-picker="modules"] button');
  ok(await edit.count() === 1 && (await edit.textContent()) === 'Edit' && (await page.locator('[data-box="system"] .card > .srow').first().getAttribute('data-picker')) === 'modules', 'System has a Modules row with an Edit button');
  const openPicker = async () => { await edit.scrollIntoViewIfNeeded(); await edit.click(); await settle(500); };
  const order = async () => page.locator('.pop.open .srow[data-id]').evaluateAll(els => els.map(e => e.getAttribute('data-id')));
  const grip = n => page.locator('.pop.open .srow[data-id] .grip').nth(n);
  const done = () => page.locator('.pop.open button', { hasText: 'Done' }).click();
  await openPicker();
  ok(await page.locator('.pop.open .srow[data-id="switcher"] .grip').count() === 1 && await page.locator('.pop.open .srow[data-id="switcher"] input').count() === 0 && /Always on/.test(await page.locator('.pop.open .srow[data-id="switcher"]').textContent()), 'an always-on module is in the list with a handle but no switch');
  const dropGeo = await popGeo();
  ok(Math.abs(dropGeo.left) <= 1 && Math.abs(dropGeo.right) <= 1, 'the modules pop-up spans the card too');
  const drag = async (from, to) => {                                       // from / to are row numbers; the pointer ends on the lower half of `to`
    await grip(Math.min(from, to)).scrollIntoViewIfNeeded();
    const a = await grip(from).boundingBox(), rows = page.locator('.pop.open .srow[data-id]');
    const b = await rows.nth(to).boundingBox();
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2); await page.mouse.down();
    await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2 + (from < to ? 5 : -5), { steps: 3 });
    await page.mouse.move(a.x + a.width / 2, from < to ? b.y + b.height - 4 : b.y + 4, { steps: 12 });
  };
  await page.evaluate(() => { window.__still = true; });
  const before0 = await order();
  await drag(1, 3);
  ok(JSON.stringify(await order()) !== JSON.stringify(before0) && await page.locator('.pop.open .srow.drag').count() === 1, 'dragging a row moves it while the others make room');
  const wd = await page.evaluate(() => ({ row: Math.round(document.querySelector('.pop.open .srow.drag').getBoundingClientRect().width), pop: Math.round(document.querySelector('.pop.open').getBoundingClientRect().width) }));
  ok(Math.abs(wd.row - wd.pop) <= 1, 'the dragged row is as wide as the pop-up (' + wd.row + ' of ' + wd.pop + ')');
  await page.mouse.up(); await settle(1500);
  const moved = await order();
  ok(moved[3] === before0[1] && await page.evaluate(() => window.__still === true) && await page.locator('.pop.open').count() === 1, 'dropping only moves it: the page is not redrawn and the pop-up stays open');
  await drag(2, 0); await page.keyboard.press('Escape');
  ok(JSON.stringify(await order()) === JSON.stringify(moved) && await page.locator('.pop.open .srow.drag').count() === 0 && await page.locator('.pop.open').count() === 1, 'Esc while dragging cancels the drag (the pop-up stays)');
  await page.mouse.up(); await settle(300);
  await grip(0).focus(); await page.keyboard.press('ArrowDown'); await settle(1300);
  const kb = await order();
  ok(kb[1] === moved[0] && await page.evaluate(() => window.__still === true), 'the arrow keys on a handle move the row too');
  const players = page.locator('.pop.open input[data-module="players"]');
  await players.uncheck(); await settle(800);
  ok(await page.evaluate(() => window.__still === true) && await page.locator('.dbox').count() === 3, 'switching a module off changes nothing until Done');
  await done(); await page.waitForLoadState('networkidle'); await settle(2000);
  ok(await page.locator('#settings.open').count() === 1 && await page.evaluate(() => window.__still !== true), 'Done saves and builds the page again with Settings still open');
  await page.click('#close-settings');
  ok(await page.locator('.dbox').count() === 2 && await page.locator('text=Online players:').count() === 0, 'the module switched off is gone from the dashboard');
  await openSettings(); await openPicker();
  const savedOrder = await order();
  ok(JSON.stringify(savedOrder) === JSON.stringify(kb), 'and the new order was saved');
  await page.locator('.pop.open input[data-module="players"]').check();
  await drag(1, 0); await page.mouse.up(); await settle(300);                       // put the first two back as they were
  await page.keyboard.press('Escape'); await page.waitForLoadState('networkidle'); await settle(2000);
  await page.click('#close-settings'); await settle(500);
  ok(await page.locator('text=Online players:').count() === 1, 'Esc closes the pop-up like Done and applies: the module is back');
  // ---- the debug log expander
  await page.click('.xpand button.wide'); await settle(500);
  ok(await page.locator('.xpand .xbody').isVisible(), 'the debug log bar opens');
  await page.locator('.xpand .xbody button', { hasText: 'Recording' }).click(); await settle(1500);
  ok(/Recording$/.test((await page.locator('.xpand .xbody button').first().textContent()).trim()) && /●/.test(await page.locator('.xpand .xbody button').first().textContent()), 'Recording switches on');
  await page.locator('.xpand .xbody button', { hasText: 'Recording' }).click(); await settle(900);
  // ---- the same drag with a finger (touch events through the browser's protocol, in a phone-sized touch context)
  const ctx2 = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });
  const tp = await ctx2.newPage();
  tp.on('pageerror', e => errors.push('touch page: ' + String(e)));
  tp.on('dialog', d => d.accept());
  await tp.goto(URL, { waitUntil: 'networkidle' }); await tp.waitForTimeout(1200);
  await tp.tap('#cog'); await tp.waitForTimeout(900);
  const editT = tp.locator('[data-box="system"] [data-picker="modules"] button');
  await editT.scrollIntoViewIfNeeded(); await editT.tap(); await tp.waitForTimeout(600);
  const cdp = await ctx2.newCDPSession(tp);
  const touch = (type, x, y) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: type === 'touchEnd' ? [] : [{ x, y }] });
  const rowsT = tp.locator('.pop.open .srow[data-id]');
  const orderT = () => rowsT.evaluateAll(els => els.map(e => e.getAttribute('data-id')));
  const startT = await orderT();
  await rowsT.nth(0).scrollIntoViewIfNeeded();
  await tp.evaluate(() => { window.__removed = 0;
    new MutationObserver(ms => ms.forEach(m => m.removedNodes.forEach(n => { if (n.classList && n.classList.contains('drag')) window.__removed++; }))).observe(document.querySelector('.pop.open .mlist'), { childList: true }); });
  const g = await tp.locator('.pop.open .srow[data-id] .grip').nth(0).boundingBox();
  const r1 = await rowsT.nth(2).boundingBox();
  await touch('touchStart', g.x + g.width / 2, g.y + g.height / 2);
  for (let i = 1; i <= 14; i++) { await touch('touchMove', g.x + g.width / 2, g.y + g.height / 2 + (r1.y + r1.height - g.y - g.height / 2) * i / 14); await tp.waitForTimeout(20); }
  const mid = await orderT();
  ok(await tp.locator('.pop.open .srow.drag').count() === 1 && mid[2] === startT[0], 'a finger drags a row two places down while the others make room');
  ok(await tp.evaluate(() => window.__removed) === 0, 'the grabbed row is never taken out of the document (iOS ends a touch whose element is re-inserted)');
  await touch('touchEnd'); await tp.waitForTimeout(700);
  const endT = await orderT();
  ok(endT[2] === startT[0] && await tp.locator('.pop.open').count() === 1, 'lifting the finger drops the row there (nothing is applied until Done)');
  await rowsT.nth(2).scrollIntoViewIfNeeded();
  const g2 = await tp.locator('.pop.open .srow[data-id] .grip').nth(2).boundingBox(), r0 = await rowsT.nth(0).boundingBox();
  await touch('touchStart', g2.x + g2.width / 2, g2.y + g2.height / 2);
  for (let i = 1; i <= 14; i++) { await touch('touchMove', g2.x + g2.width / 2, g2.y + g2.height / 2 - (g2.y + g2.height / 2 - r0.y - 6) * i / 14); await tp.waitForTimeout(20); }
  await touch('touchEnd'); await tp.waitForTimeout(700);
  ok(JSON.stringify(await orderT()) === JSON.stringify(startT), 'and a drag up with a finger puts it back');
  await ctx2.close();
  // ---- no errors anywhere
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

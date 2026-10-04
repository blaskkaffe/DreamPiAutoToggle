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
  await page.evaluate(() => { S.players = Object.assign({}, S.players, { games: [{ text: 'Quake III', n: 1 }] }); engineUpdate(); }); await settle(300);
  const geo = await page.evaluate(() => { const t = document.querySelector('.carousel .t').getBoundingClientRect(), b = document.querySelector('.now:nth-of-type(2), .dbox:nth-child(2) .now').getBoundingClientRect();
    return { off: Math.abs((t.left + t.right) / 2 - (b.left + b.right) / 2), sc: !!document.querySelector('.carousel.sc'), w: b.width }; });
  ok(!geo.sc && geo.off < 24, 'a short games line stands still and is centred in the box (off by ' + Math.round(geo.off) + 'px of ' + Math.round(geo.w) + ')');
  ok(await page.locator('.carousel .cn').first().textContent() === '1' && !/\(/.test(await page.locator('.carousel').first().textContent()), 'the game count has no brackets and its own (subtitle) colour');
  ok(await page.locator('.dbox:nth-child(2) .row.main .arrow').count() === 0, 'the players box has no small arrow');
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
  ok(await swatches.count() === 15, 'it opens a pop-up with the palette (15 colours: the network buttons cannot be "Selected network")');
  ok(await page.locator('.pop.open .swatch').first().getAttribute('data-id') === 'global', 'Global main is the first ball');
  ok(await page.locator('.pop.open .swatch.sel').count() === 1 && await page.locator('.pop.open .swatch.sel').getAttribute('data-id') === 'orange', 'the current colour is marked');
  await page.locator('.pop.open .swatch[data-id="bright-pink"]').click(); await settle(1500);
  ok(await page.locator('.pop.open').count() === 0, 'picking a colour closes the pop-up');
  ok(await colourBtn.evaluate(e => e.classList.contains('c-bright-pink')), 'and the Colour button takes it');
  ok(await page.locator('.pill').nth(0).evaluate(e => e.classList.contains('c-bright-pink')), 'DCNow! button follows the picked colour');
  ok(await page.evaluate(() => document.body.classList.contains('c-bright-pink')), 'and so does the page primary while DCNow! is selected');
  await colourBtn.click(); await settle(300); await page.locator('.pop.open .swatches .swatch[data-id="orange"]').click(); await settle(1200);   // back to orange
  // ---- the picker table (phone numbers)
  const group = page.locator('[data-box="special phone numbers"] .wpicker .srow').first();
  await group.locator('button').first().click();
  const gp2 = await popGeo();
  ok(Math.abs(gp1.w - gp2.w) <= 1, 'and every pop-up has the same width (' + gp1.w + ' and ' + gp2.w + ')');
  ok(Math.abs(gp2.left) <= 1 && Math.abs(gp2.right) <= 1, 'the add-number pop-up does too');
  await page.fill('.pop.open input', '5551234'); await page.click('.pop.open .pill-s'); await settle(900);
  ok(await page.locator('[data-box="special phone numbers"] .wpicker .tag', { hasText: '5551234' }).count() === 1, 'a number is added to its group');
  await page.locator('[data-box="special phone numbers"] .wpicker .tag', { hasText: '5551234' }).locator('button').click(); await settle(900);
  ok(await page.locator('[data-box="special phone numbers"] .wpicker .tag', { hasText: '5551234' }).count() === 0, 'and removed again');
  ok(await page.locator('text=No number').count() === 0, 'a group with no numbers shows no "No number" text');
  const hNum = await page.locator('[data-box="special phone numbers"] .wpicker .srow').first().evaluate(e => e.getBoundingClientRect().height);
  const hGpio = await page.locator('[data-box="gpio"] .srow', { hasText: 'Button 1' }).first().evaluate(e => e.getBoundingClientRect().height);
  ok(Math.abs(hNum - hGpio) <= 6, 'a phone number row is as high as a GPIO row (' + Math.round(hNum) + ' and ' + Math.round(hGpio) + ')');
  await page.locator('[data-box="special phone numbers"] .wpicker .infobtn').click(); await settle(300);
  ok(/numbers ending in the listed numbers/.test(await page.locator('.pop.open .infotext').textContent()), 'the (i) button opens the pop-up with the information text');
  ok(await page.locator('.pop.open button', { hasText: 'Done' }).count() === 0, 'the information pop-up has no Done button (nothing to save)');
  await page.keyboard.press('Escape'); await settle(200);
  // ---- favorite players and games: pick from the lists (not-online games can't be picked, work in progress is marked)
  const fav = page.locator('[data-box="favorites"] .wpicker');
  await fav.locator('.srow').first().locator('button').first().click(); await settle(500);
  ok(await page.locator('.pop.open .choice').count() >= 4, 'the favorite games pop-up lists the games of the list');
  ok(await page.locator('.pop.open .choice', { hasText: 'Dead Game Online' }).count() === 0, 'only games being played now are listed at first');
  ok(await page.locator('.pop.open .choice', { hasText: 'playing now' }).count() >= 4, 'and say that they are played now');
  await page.fill('.pop.open input', 'dead'); await settle(200);
  ok(await page.locator('.pop.open .choice:disabled', { hasText: 'Dead Game Online' }).count() === 1, 'searching finds the whole list; a game that is not online is greyed out');
  await page.fill('.pop.open input', 'outtr'); await settle(200);
  ok(await page.locator('.pop.open .choice', { hasText: 'work in progress' }).count() === 1, 'a work-in-progress game says so');
  ok(await page.locator('.pop.open .choice').count() === 1, 'typing filters the list');
  await page.locator('.pop.open .choice', { hasText: 'Outtrigger' }).click(); await settle(900);
  ok(await fav.locator('.tag', { hasText: 'Outtrigger (work in progress)' }).count() === 1, 'the picked game is a favorite, marked as work in progress');
  await fav.locator('.tag', { hasText: 'Outtrigger' }).locator('button').click(); await settle(900);
  ok(await fav.locator('.tag', { hasText: 'Outtrigger' }).count() === 0, 'and can be removed');
  // ---- Status LED: rows of colour + animation + level, each with the messages that light it
  const led = page.locator('[data-box="status led"]');
  const ledRows = led.locator('.srow:has(button[aria-label="Edit this colour"])');
  const rows0 = await ledRows.count();
  ok(rows0 === 6, 'the LED box starts with the six default colour rows (' + rows0 + ')');
  ok(await ledRows.first().locator('.tag', { hasText: 'DCNow! selected' }).count() === 1, 'the first row holds DCNow! selected');
  const lookOf = i => ledRows.nth(i).evaluate(e => { const b = e.querySelector('button.pill-s'), t = e.querySelector('.tag'), cs = getComputedStyle(b); return { bg: cs.backgroundColor, border: cs.borderTopColor, tag: t ? getComputedStyle(t).backgroundColor : '', blink: cs.animationName, dot: !!e.querySelector('.gdot') }; });
  const l0 = await lookOf(0), l4 = await lookOf(3), l5 = await lookOf(4);
  ok(!l0.dot && l0.bg !== l0.border && l0.bg === l0.tag, 'a row has no dot: its buttons and tags take the colour, with a lighter border (' + l0.bg + ' / ' + l0.border + ')');
  ok(l4.blink === 'lkblink' && l0.blink === 'none', 'a blinking look makes the row blink like the LED (Starting up blinks, DCNow! does not)');
  const samples = await ledRows.nth(3).evaluate(async e => { const b = e.querySelector('button.pill-s'), out = []; for (let i = 0; i < 30; i++) { const cs = getComputedStyle(b); out.push([cs.backgroundColor, cs.color, cs.opacity]); await new Promise(r => setTimeout(r, 70)); } return out; });
  const bgs = Array.from(new Set(samples.map(x => x[0])));
  ok(bgs.length === 2 && bgs.includes('rgba(42, 42, 42, 0.82)'), 'a blinking button goes between its colour and the default dark grey (' + bgs.join(' / ') + ')');
  ok(new Set(samples.map(x => x[1])).size === 1 && samples.every(x => x[2] === '1'), 'and its text keeps the same colour and brightness all the time');
  ok(l0.bg !== l5.bg, 'rows with different colours look different');
  await led.locator('button', { hasText: 'Add colour' }).click(); await settle(900);
  ok(await ledRows.count() === rows0 + 1, 'Add colour adds a row');
  await ledRows.last().locator('button[aria-label="Edit this colour"]').click(); await settle(300);
  const lg = await popGeo();
  ok(Math.abs(lg.w - gp1.w) <= 1 && Math.abs(lg.left) <= 1 && Math.abs(lg.right) <= 1, 'the colour pop-up has the same width as the others (' + lg.w + ')');
  await page.locator('.pop.open .swatch[aria-label="Green"]').click(); await settle(900);
  ok(/Green/.test(await ledRows.last().textContent()), 'picking a colour names it in the row');
  await page.locator('.pop.open button', { hasText: 'Remove' }).click(); await settle(900);
  ok(await ledRows.count() === rows0 && await page.locator('.pop.open').count() === 0, 'Remove deletes the row and closes the pop-up');
  await ledRows.first().locator('button[aria-label="Add messages to this colour"]').click(); await settle(300);
  await page.locator('.pop.open .srow', { hasText: 'Weak Wi-Fi signal' }).locator('button').click(); await settle(900);
  ok(await ledRows.first().locator('.tag', { hasText: 'Weak Wi-Fi signal' }).count() === 1, 'a message is added to the row it was added from');
  ok(await page.locator('.pop.open .srow', { hasText: 'Weak Wi-Fi signal' }).count() === 0, 'and is no longer on offer in the list');
  await page.keyboard.press('Escape'); await settle(200);
  await ledRows.first().locator('.tag', { hasText: 'Weak Wi-Fi signal' }).locator('button').click(); await settle(900);
  ok(await ledRows.first().locator('.tag', { hasText: 'Weak Wi-Fi signal' }).count() === 0, 'a message is taken out of its row with the x');
  await led.locator('.infobtn').click(); await settle(300);
  ok(await page.locator('.pop.open .infotext').count() === 1 && await page.locator('.pop.open button', { hasText: 'Done' }).count() === 0, 'the LED box has an information pop-up without a Done button');
  await page.keyboard.press('Escape'); await settle(200);
  await led.locator('button', { hasText: 'Add colour' }).click(); await settle(600);
  await led.locator('button', { hasText: 'Restore defaults' }).click(); await settle(900);
  ok(await ledRows.count() === rows0, 'Restore defaults brings the default rows back');
  // every animation of a row: its class says which, the buttons run it between the colour and the grey
  await ledRows.first().locator('button[aria-label="Edit this colour"]').click(); await settle(300);
  for (const [label, cls] of [['Fade', 'lk-fade'], ['Breathe', 'lk-breathe'], ['Short blink', 'lk-blink1'], ['Double blink', 'lk-blink2'], ['Triple blink', 'lk-blink3'], ['Rainbow', 'lk-rainbow']]) {
    await page.locator('.pop.open .seg button', { hasText: new RegExp('^' + label + '$') }).click(); await settle(500);
    ok(await ledRows.first().evaluate((e, c) => e.classList.contains(c) && getComputedStyle(e.querySelector('button.pill-s')).animationName !== 'none', cls), label + ' makes the row run its animation');
  }
  await page.locator('.pop.open .seg button', { hasText: /^Solid$/ }).click(); await settle(500);
  ok(await ledRows.first().evaluate(e => !e.classList.contains('lk-fx')), 'Solid stops it');
  await page.keyboard.press('Escape'); await settle(200);
  // the colours editor: the LED's red need not be the page's red
  await led.locator('button[aria-label="Adjust the colours"]').click(); await settle(600);
  const cg = await popGeo();
  ok(Math.abs(cg.w - gp1.w) <= 1, 'the colours pop-up has the same width as the others (' + cg.w + ')');
  ok(await page.locator('.pop.open .swatches .swatch').count() === 16, 'it has all 16 colours');
  await page.locator('.pop.open .swatch[aria-label="Selected network"]').click(); await settle(300);
  ok(await page.locator('.pop.open input[type=color]').count() === 0 && /follows the switch/.test(await page.locator('.pop.open').textContent()), 'Selected network has no value of its own to edit');
  await page.locator('.pop.open .swatch[aria-label="Red"]').click(); await settle(300);
  await page.locator('.pop.open input[aria-label="Red on the LED"]').fill('#e01000'); await settle(900);
  const led1 = await page.evaluate(async () => (await (await fetch('/ledcolours')).json()).colours.find(c => c.id === 'red'));
  ok(led1.led === '#e01000' && led1.ui === led1.ui_default, 'the LED value is saved and the page colour is not touched (' + led1.led + ' / ' + led1.ui + ')');
  await page.locator('.pop.open input[aria-label="Red on screen"]').fill('#aa2222'); await settle(900);
  ok(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--c-red').trim()) === '#aa2222', 'a page colour changes the page at once');
  await page.locator('.pop.open button', { hasText: 'Reset all' }).click(); await settle(900);
  const led2 = await page.evaluate(async () => (await (await fetch('/ledcolours')).json()).colours.find(c => c.id === 'red'));
  ok(led2.led === led2.led_default && led2.ui === led2.ui_default, 'Reset all puts the shipped colours back');
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await page.waitForLoadState('networkidle'); await settle(2000);
  ok(await page.locator('#settings.open').count() === 1, 'closing it after a change builds the page again with Settings still open');
  // Priority: put the messages in order, most important first
  await led.locator('button[aria-label="Edit the message priority"]').click(); await settle(500);
  const pg = await popGeo();
  ok(Math.abs(pg.w - gp1.w) <= 1, 'the priority pop-up has the same width as the others (' + pg.w + ')');
  const prio = () => page.locator('.pop.open .srow[data-id]').evaluateAll(els => els.map(e => e.getAttribute('data-id')));
  const p0 = await prio();
  ok(p0.length > 30 && p0[0] === 'reboot' && !p0.includes('off'), 'every message is in the list, most important first (' + p0.length + ', the first is ' + p0[0] + ')');
  await page.locator('.pop.open .srow[data-id] .grip').first().focus(); await page.keyboard.press('ArrowDown'); await settle(1500);
  const p1 = await prio();
  ok(p1[0] === p0[1] && p1[1] === p0[0], 'the arrow keys on a handle move a message down');
  const saved = await page.evaluate(async () => (await (await fetch('/ledconfig')).json()).config.priority);
  ok(saved[0] === p0[1] && saved[1] === p0[0], 'and the new order is saved');
  await page.locator('.pop.open button', { hasText: 'Restore default order' }).click(); await settle(1200);
  ok(JSON.stringify(await prio()) === JSON.stringify(p0), 'Restore default order puts it back');
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  // Appearance: a tick box left of each colour picks a coloured or a neutral background
  const appr = page.locator('[data-box="appearance"] .srow', { hasText: 'Online players colour' });
  ok(!(await appr.locator('input[type=checkbox]').isChecked()) && await page.locator('.dbox[data-box="players"].plain').count() === 1, 'a box starts neutral (Highlight off)');
  await appr.locator('input[type=checkbox]').check(); await settle(1300);
  ok(await page.locator('.dbox[data-box="players"].plain').count() === 0, 'ticking Highlight makes the box coloured');
  await appr.locator('input[type=checkbox]').uncheck(); await settle(1300);
  ok(await page.locator('.dbox[data-box="players"].plain').count() === 1, 'and unticking it makes it neutral again');
  const dc = page.locator('[data-box="appearance"] .srow', { hasText: 'DCNow! colour' });
  ok(await dc.locator('input[type=checkbox]').isChecked() && !(await page.locator('.pill').first().evaluate(e => e.classList.contains('plain'))), 'the network buttons are highlighted from the start');
  await dc.locator('input[type=checkbox]').uncheck(); await settle(1300);
  ok(await page.locator('.pill').first().evaluate(e => e.classList.contains('plain')) && !(await page.locator('.pill').nth(1).evaluate(e => e.classList.contains('plain'))), 'the network buttons have a background setting each');
  await dc.locator('input[type=checkbox]').check(); await settle(1000);
  // dividers: every row of a box has a line above it except the first, whichever module or widget it comes from
  const dividers = await page.evaluate(() => Array.from(document.querySelectorAll('#set-boxes .card')).filter(c => c.offsetParent).map(c => {
    const rows = Array.from(c.querySelectorAll('.srow')).filter(r => r.offsetParent && !r.closest('.pop') && !r.closest('.wlist.compact'));
    const atTop = rows.length && (c.firstElementChild === rows[0] || (c.firstElementChild.contains(rows[0]) && c.firstElementChild.querySelector('.srow') === rows[0]));   // a row below a table has a line above it
    return { box: c.parentNode.getAttribute('data-box'), bad: rows.map((r, i) => [i, parseFloat(getComputedStyle(r).borderTopWidth) > 0]).filter(x => ((x[0] === 0 && atTop) === x[1])).map(x => x[0]) };
  }));
  ok(dividers.every(d => d.bad.length === 0), 'every settings box has a divider above each row but the first' + JSON.stringify(dividers.filter(d => d.bad.length)));
  // ---- GPIO: every row is a title, a line that says what it does, and an Edit button with the dropdowns in a pop-up; it saves to the server
  const gpioRow = t => page.locator('[data-box="gpio"] .srow', { hasText: t }).first();
  ok(/^GPIO\d+ /.test((await gpioRow('Button 1').locator('.sub').textContent()).trim()), 'the line under Button 1 starts with its pin: ' + (await gpioRow('Button 1').locator('.sub').textContent()).trim());
  ok(/^\d+ [A-Z]{3} LEDs? connected to GPIO\d+$/.test((await gpioRow('LED').locator('.sub').textContent()).trim()), 'the LED line counts LEDs, order and pin: ' + (await gpioRow('LED').locator('.sub').textContent()).trim());
  ok(await page.locator('[data-box="gpio"] select').evaluateAll(els => els.every(e => !e.offsetParent)), 'the dropdowns are not in the rows, only in the pop-ups');
  await gpioRow('Button 2').locator('button').click(); await settle(400);
  await page.locator('.pop.open select[aria-label="Button 2: Function"]').selectOption({ label: 'Select DCNET' }); await settle(1000);
  ok(/GPIO\d+ selects DCNET/.test(await gpioRow('Button 2').locator('.sub').textContent()), 'the line under Button 2 follows its function');
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  await page.reload({ waitUntil: 'networkidle' }); await settle(800); await openSettings();
  await gpioRow('Button 2').locator('button').click(); await settle(400);
  ok((await page.locator('.pop.open select[aria-label="Button 2: Function"] option:checked').textContent()) === 'Select DCNET', 'the value was saved');
  await page.locator('.pop.open select[aria-label="Button 2: Function"]').selectOption({ label: 'Off' }); await settle(900);
  await page.locator('.pop.open button', { hasText: 'Done' }).click(); await settle(300);
  // ---- shared boxes: wifi, system and the update rows are one box
  ok(await page.locator('[data-box="system"]').count() === 1, 'one System box is shared by several modules');
  const boxIds = await page.locator('#set-boxes [data-box]').evaluateAll(els => els.map(e => e.getAttribute('data-box')));
  ok(boxIds.slice(-2).join() === 'about,system', 'Settings ends with About and System (last): ' + boxIds.join(' | '));
  ok(boxIds.includes('appearance') && !boxIds.includes('modules') && !boxIds.includes('network colours'), 'the colours are in Appearance, and the modules have no box of their own');
  ok(await page.locator('[data-box="gpio"] .wform').count() >= 2, 'and one GPIO box holds the forms of the buttons and the LED');
  // ---- Appearance also has the Dreamcast background's switch (the module is off in the demo)
  const bgToggle = page.locator('[data-box="appearance"] .srow:has-text("Dreamcast background") input[type=checkbox]');
  ok(await bgToggle.count() === 1 && !(await bgToggle.isChecked()), 'Appearance has a switch for the Dreamcast background, off');
  await bgToggle.check(); await page.waitForLoadState('networkidle'); await settle(2000);
  ok(await page.evaluate(() => document.body.classList.contains('dcbg') && !!document.getElementById('dcbg')), 'switching it on draws the background (the page was rebuilt with Settings open)');
  ok(await page.locator('#settings.open').count() === 1 && await page.locator('[data-box="appearance"] .srow:has-text("Dreamcast background") input[type=checkbox]').isChecked(), 'and the switch stays on');
  // Highlight (a coloured background) works over the background, a neutral one is the grey of the Dreamcast pop-ups
  await page.click('#close-settings'); await settle(400);
  const fill = sel => page.locator(sel).first().evaluate(e => getComputedStyle(e).backgroundColor);
  const hi = await fill('.dbox[data-box="network"] .now');
  ok(/^rgba\(\d+, \d+, \d+, 0\.\d+\)$/.test(hi) && hi !== 'rgba(20, 20, 20, 0.78)', 'over the Dreamcast background a highlighted box keeps its translucent colour (' + hi + ')');
  await page.evaluate(() => document.querySelector('.dbox[data-box="network"]').classList.add('plain'));
  ok(await fill('.dbox[data-box="network"] .now') === 'rgba(20, 20, 20, 0.78)', 'and a neutral one is the translucent grey');
  await page.evaluate(() => document.querySelector('.dbox[data-box="network"]').classList.remove('plain'));
  await openSettings();
  await page.locator('[data-box="appearance"] .srow:has-text("Dreamcast background") input[type=checkbox]').uncheck(); await page.waitForLoadState('networkidle'); await settle(2000);
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
    await page.locator('.pop.open').evaluate(e => e.scrollIntoView({ block: 'start' }));       // the rows being dragged stay clear of the edges (a drag near an edge scrolls the page)
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
  await tp.locator('.pop.open').evaluate(e => e.scrollIntoView({ block: 'start' }));
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
  await tp.locator('.pop.open').evaluate(e => e.scrollIntoView({ block: 'start' }));
  const g2 = await tp.locator('.pop.open .srow[data-id] .grip').nth(2).boundingBox(), r0 = await rowsT.nth(0).boundingBox();
  await touch('touchStart', g2.x + g2.width / 2, g2.y + g2.height / 2);
  for (let i = 1; i <= 14; i++) { await touch('touchMove', g2.x + g2.width / 2, g2.y + g2.height / 2 - (g2.y + g2.height / 2 - r0.y - 6) * i / 14); await tp.waitForTimeout(20); }
  await touch('touchEnd'); await tp.waitForTimeout(700);
  ok(JSON.stringify(await orderT()) === JSON.stringify(startT), 'and a drag up with a finger puts it back');
  await ctx2.close();
  // ---- wide screen: the settings flow into columns, and a pop-up must stay inside its own card (never be continued in the next column)
  const wide = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  wide.on('pageerror', e => errors.push('wide page: ' + String(e)));
  await wide.goto(URL, { waitUntil: 'networkidle' }); await wide.waitForTimeout(1200);
  await wide.click('#cog'); await wide.waitForTimeout(900);
  const inside = async (sel, what) => {
    const b = wide.locator(sel).first(); await b.scrollIntoViewIfNeeded(); await b.click(); await wide.waitForTimeout(500);
    const g = await wide.evaluate(() => { const p = document.querySelector('.pop.open'), c = p.closest('.card'), pr = p.getBoundingClientRect(), cr = c.getBoundingClientRect();
      return { top: pr.top - cr.top, bottom: cr.bottom - pr.bottom, left: pr.left - cr.left, right: cr.right - pr.right }; });
    ok(g.top >= -1 && g.bottom >= -1 && g.left >= -1 && g.right >= -1, 'the ' + what + ' pop-up stays inside its card on a wide screen (' + JSON.stringify(g) + ')');
    await wide.keyboard.press('Escape'); await wide.waitForTimeout(300);
  };
  await inside('[data-box="status led"] button[aria-label="Edit this colour"]', 'LED colour');
  await inside('[data-box="gpio"] button[aria-label="Edit Button 1"]', 'GPIO');
  await inside('[data-box="system"] [data-picker="modules"] button', 'modules');
  await wide.close();
  // ---- no errors anywhere
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

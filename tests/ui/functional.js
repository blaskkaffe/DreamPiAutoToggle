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
  const swatches = page.locator('[data-box="network colours"] .swatches').first().locator('.swatch');
  ok(await swatches.count() === 16, 'the palette has 16 colours');
  await swatches.nth(7).click(); await settle(1500);                       // pink (the 8 normal colours come first, then the bright ones)
  ok(await page.locator('.pill').nth(0).evaluate(e => e.classList.contains('c-pink')), 'DCNow! button follows the picked colour');
  ok(await page.evaluate(() => document.body.classList.contains('c-pink')), 'and so does the page primary while DCNow! is selected');
  await swatches.nth(1).click(); await settle(1200);                       // back to orange
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
  // ---- the module picker: move a module and switch one off
  const order = async () => page.locator('[data-box="modules"] .srow > span:first-child').evaluateAll(els => els.map(e => e.firstChild.textContent));
  const first = (await order())[0];
  await page.locator('[data-box="modules"] .mv[title="Move down"]').first().click(); await page.waitForLoadState('networkidle'); await settle(1500);
  ok((await order())[0] !== first, 'a module moves down in the picker (the page reloads in Settings)');
  ok(await page.locator('#settings.open').count() === 1, 'and Settings stays open');
  await page.locator('[data-box="modules"] .mv[title="Move up"]').nth(1).click(); await page.waitForLoadState('networkidle'); await settle(1500);
  ok((await order())[0] === first, 'and moves back up');
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

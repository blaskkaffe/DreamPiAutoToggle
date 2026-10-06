// Functional check of the page in a real browser, against the demo server (sh tests/ui/run.sh runs it after the audit): the check-in board
// (tap, status menu, several screens in step, the buildings filter, the settings, the CSV import) and the base's own controls.
// Exits 1 on the first failed expectation.
const { chromium } = require('playwright');
const PORT = process.env.PORT || 8734;
const URL = 'http://127.0.0.1:' + PORT + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error' && !/status of 400/.test(m.text())) errors.push(m.text().slice(0, 150)); });      // the refused import is a 400 on purpose
  page.on('dialog', d => d.accept());
  const settle = ms => page.waitForTimeout(ms || 1300);
  const openSettings = async () => { await page.click('#cog'); await settle(900); };
  const closeSettings = async () => { await page.click('#close-settings'); await settle(300); };
  const person = name => page.locator('.rp-r', { has: page.locator('.rp-n', { hasText: name }) });
  const cls = async name => (await page.locator('.rp-r', { has: page.locator('.rp-n', { hasText: name }) }).first().getAttribute('class')) || '';
  const bg = loc => loc.evaluate(e => getComputedStyle(e).backgroundColor);

  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1800);
  // ---- the board comes from the contacts
  ok(await page.locator('.dbox[data-box="checkin"]').count() === 1, 'the dashboard has the check-in box');
  ok(await page.locator('.rp-r').count() === 23, 'a row per person (23: two belong to one building only)');
  ok(await page.locator('.rp-box').count() === 5, 'one box per department (5)');
  ok(await page.locator('.rp-r.out').count() === 23, 'everybody starts out and grey');
  ok(await page.locator('.rp-chips button').count() === 3, 'two buildings and "All" are offered as a filter');
  const widthOf = sel => page.locator(sel).first().evaluate(e => Math.round(e.getBoundingClientRect().height));
  ok(await widthOf('.rp-r') >= 36, 'a person row is tall enough to tap (' + await widthOf('.rp-r') + 'px)');
  ok(await page.locator('.rp-n').first().evaluate(e => parseFloat(getComputedStyle(e).fontSize)) >= 20, 'the names are large (20px or more)');
  const alphas = await page.evaluate(() => Array.from(document.querySelectorAll('.rp-r, .pill-s')).filter(e => e.offsetParent).map(e => getComputedStyle(e).borderTopColor).filter(c => /^rgba\(/.test(c) && !/, 1\)$/.test(c)));
  ok(alphas.length === 0, 'the borders of the buttons are opaque');

  // ---- a tap switches in and out, in the colour of the department
  const grey = await bg(person('Anna Svensson'));
  await person('Anna Svensson').locator('.rp-t').click(); await settle(500);
  ok(/\bpri\b/.test(await cls('Anna Svensson')), 'a tap turns Anna in (coloured)');
  const colour = await bg(person('Anna Svensson'));
  ok(colour !== grey, 'in has another colour than out');
  await person('Johan Holm').locator('.rp-t').click(); await settle(500);   // Johan is in Kök, like Anna
  ok(await bg(person('Johan Holm')) === colour, 'people of one department share a colour');
  ok(await page.locator('.rp-box', { hasText: 'Kök' }).locator('.rp-gh .sub').textContent() === '2/4', 'the group counts who is in (2/4)');
  await person('Anna Svensson').locator('.rp-t').click(); await settle(500);
  ok(await bg(person('Anna Svensson')) === grey, 'a second tap turns Anna out again (grey)');

  // ---- the status menu
  await person('Erik Lindqvist').locator('.rp-e').click(); await settle(400);
  ok(await page.locator('.rp-menu.open').count() === 1, 'the small button opens the status menu');
  ok(await page.locator('.rp-menu button[data-code]').count() >= 12, 'the menu offers In, Out and the statuses of CheckinChicken');
  await page.locator('.rp-menu button[data-code="SICK"]').click(); await settle(500);
  ok(await page.locator('.rp-menu.open').count() === 0, 'picking a status closes the menu');
  const sick = person('Erik Lindqvist');
  ok((await sick.locator('.rp-s').textContent()) === 'Sjuk', 'the button names the status');
  ok(/c-red/.test(await sick.getAttribute('class')), 'and the row takes its colour (red)');
  await person('Erik Lindqvist').locator('.rp-e').click(); await settle(300);
  await page.locator('.rp-menu button[data-code="LATE"]').click(); await settle(300);
  ok(await page.locator('.rp-need input[type=time]').count() === 1, 'a status that needs a time asks for it');
  await page.locator('.rp-need input').fill('08:45'); await page.locator('.rp-need button[data-set]').click(); await settle(500);
  ok((await sick.locator('.rp-s').textContent()) === 'Kommer sent · 08:45', 'the time is part of the status text');
  await person('Erik Lindqvist').locator('.rp-t').click(); await settle(500);
  ok(await person('Erik Lindqvist').locator('.rp-s').textContent() === 'Medarbetare' || /pri/.test(await person('Erik Lindqvist').getAttribute('class')), 'a tap on a row with a status clears it (it is in, plain)');
  await person('Erik Lindqvist').locator('.rp-e').click(); await settle(300);
  await page.locator('.rp-menu button[data-code="OUT"]').click(); await settle(500);
  ok(/\bout\b/.test(await cls('Erik Lindqvist')), 'Out in the menu sets the person out');
  await person('Erik Lindqvist').locator('.rp-e').click(); await settle(300);
  await page.keyboard.press('Escape'); await settle(200);
  ok(await page.locator('.rp-menu.open').count() === 0, 'Escape closes the menu');

  // ---- a second screen follows the first within a couple of seconds
  const second = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await second.goto(URL, { waitUntil: 'networkidle' }); await second.waitForTimeout(1500);
  await person('Maja Berg').locator('.rp-t').click(); await settle(300);
  await second.waitForTimeout(2200);
  ok(await second.locator('.rp-r.pri', { has: second.locator('.rp-n', { hasText: 'Maja Berg' }) }).count() === 1, 'another screen shows the change without a reload');
  await second.locator('.rp-r', { has: second.locator('.rp-n', { hasText: 'Maja Berg' }) }).locator('.rp-t').click(); await second.waitForTimeout(300);
  await settle(2200);
  ok(/\bout\b/.test(await cls('Maja Berg')), 'and the other way round');
  await second.close();

  // ---- the buildings filter (kept in this browser) and the person that belongs to one building only
  ok(await page.locator('.rp-r').count() === 23, 'people who show in one building only are left out of "All" (23)');
  await page.locator('.rp-chips button', { hasText: 'Område B' }).click(); await settle(300);
  const shownB = await page.locator('.rp-r').count();
  ok(shownB > 0 && shownB < 23, 'a building shows its own people (' + shownB + ')');
  await page.reload({ waitUntil: 'networkidle' }); await settle(1500);
  ok(await page.locator('.rp-r').count() === shownB, 'the choice is kept after a reload');
  await page.locator('.rp-chips button', { hasText: 'All' }).click(); await settle(300);

  // ---- settings: the look, the colours, the import
  await openSettings();
  ok(await page.locator('[data-box="contacts"]').count() === 1 && await page.locator('[data-box="check-in"]').count() === 1, 'Settings has the contacts and the check-in boxes');
  await closeSettings(); await settle(1500);
  await openSettings();
  await page.selectOption('[data-box="check-in"] select[aria-label="Colour of Kök"]', { label: 'Bright pink' }); await settle(800);
  await closeSettings();
  const pink = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--c-bright-pink').trim());
  await person('Anna Svensson').locator('.rp-t').click(); await settle(500);
  ok(/c-bright-pink/.test(await person('Anna Svensson').getAttribute('class')), 'a colour picked for a department is used by its rows when in (' + pink + ')');
  await person('Anna Svensson').locator('.rp-t').click(); await settle(500);
  await openSettings();
  const csv = 'name,department,role,phone,location\nNy Person,Lager,Chef,,Område B\n';
  await page.fill('[data-box="contacts"] .ctext', csv); await page.click('[data-box="contacts"] .cgo'); await settle(1200);
  ok(/1 new/.test(await page.locator('[data-box="contacts"] .cmsg').textContent()), 'importing a CSV says what it did');
  ok(/26 people/.test(await page.locator('[data-box="contacts"] .wtext').first().textContent()), 'and the count follows (26 people)');
  await page.fill('[data-box="contacts"] .ctext', 'nothing here'); await page.click('[data-box="contacts"] .cgo'); await settle(800);
  ok(/must name the columns/.test(await page.locator('[data-box="contacts"] .cmsg').textContent()), 'a file that is not a roster is refused with a reason');
  await closeSettings(); await settle(1500);
  await settle(1200);
  ok(await page.locator('.rp-r').count() === 24, 'the new person is on the board (' + await page.locator('.rp-r').count() + ')');
  await openSettings();
  await page.click('[data-box="system"] .srow:has-text("Modules") > button'); await settle(500);
  ok(await page.locator('.mlist .srow').count() >= 5, 'the module picker lists the modules');
  await page.keyboard.press('Escape'); await closeSettings();

  ok(errors.length === 0, 'no JavaScript errors (' + errors.slice(0, 3).join(' | ') + ')');
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

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
  const person = name => page.locator('.rp-r', { hasText: name });
  const cls = async name => (await person(name).first().getAttribute('class')) || '';
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
  ok(await page.locator('.rp-n').first().evaluate(e => parseFloat(getComputedStyle(e).fontSize)) >= 26, 'the names are large (26px or more)');
  const alphas = await page.evaluate(() => Array.from(document.querySelectorAll('.rp-r, .pill-s')).filter(e => e.offsetParent).map(e => getComputedStyle(e).borderTopColor).filter(c => /^rgba\(/.test(c) && !/, 1\)$/.test(c)));
  ok(alphas.length === 0, 'the borders of the buttons are opaque');

  // ---- INNE / UTE at the right of a row switches in and out, in the colour of the department
  const grey = await bg(person('Anna Svensson'));
  ok((await person('Anna Svensson').locator('.rp-io').textContent()) === 'UTE' && /c-red/.test(await person('Anna Svensson').locator('.rp-io').getAttribute('class')), 'a person who is out has a red UTE button');
  await person('Anna Svensson').locator('.rp-io').click(); await settle(500);
  ok(/\bpri\b/.test(await cls('Anna Svensson')), 'INNE: the row is coloured');
  ok((await person('Anna Svensson').locator('.rp-io').textContent()) === 'INNE' && /c-green/.test(await person('Anna Svensson').locator('.rp-io').getAttribute('class')), 'and the button says INNE in green');
  const colour = await bg(person('Anna Svensson'));
  ok(colour !== grey, 'in has another colour than out');
  await person('Johan Holm').locator('.rp-io').click(); await settle(500);   // Johan is in Kök, like Anna
  ok(await bg(person('Johan Holm')) === colour, 'people of one department share a colour');
  ok(await page.locator('.rp-box', { hasText: 'Kök' }).locator('.rp-gh .sub').textContent() === '2/4', 'the group counts who is in (2/4)');
  await person('Anna Svensson').locator('.rp-io').click(); await settle(500);
  ok(await bg(person('Anna Svensson')) === grey, 'a second tap turns Anna out again (grey)');
  ok(await page.locator('.rp-modal:visible').count() === 0, 'the INNE / UTE button does not open the menu');

  // ---- a tap on the row opens the status menu in the middle of the screen
  await person('Erik Lindqvist').locator('.rp-t').click(); await settle(400);
  ok(await page.locator('.rp-modal:visible').count() === 1, 'a tap on the row opens the status menu');
  const sheet = await page.locator('.rp-sheet').boundingBox();
  ok(Math.abs(sheet.width / 1280 - 0.6) < 0.05 && Math.abs((sheet.x + sheet.width / 2) - 640) < 4, 'it is about 60% of the screen wide and centred (' + Math.round(sheet.width / 12.8) + '%)');
  const who = await page.locator('.rp-who').textContent();
  ok(/Erik Lindqvist/.test(who) && /Servering/.test(who) && /Område A/.test(who) && /Medarbetare|Chef|Vikarie/.test(who), 'it shows the name, department, building and role (' + who.trim().slice(0, 60) + ')');
  ok(await page.locator('.rp-who .rp-av').count() === 1, 'and a photo (the initials until there is one)');
  const sizes = await page.locator('.rp-so').evaluateAll(els => els.map(e => Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height)));
  ok(sizes.length >= 13 && new Set(sizes).size === 1, 'the status buttons are all the same size (' + sizes[0] + ')');
  const ys = await page.locator('.rp-so').evaluateAll(els => els.map(e => Math.round(e.getBoundingClientRect().top)));
  ok(ys.filter(y => y === ys[0]).length === 3, 'three in a row');
  await page.locator('.rp-x').click(); await settle(300);
  ok(await page.locator('.rp-modal:visible').count() === 0, 'the cross closes the menu');
  await person('Erik Lindqvist').locator('.rp-t').click(); await settle(300);
  await page.mouse.click(20, 20); await settle(300);
  ok(await page.locator('.rp-modal:visible').count() === 0, 'a click outside closes it too');
  await person('Erik Lindqvist').locator('.rp-t').click(); await settle(300);
  await page.locator('.rp-sheet button[data-code="SICK"]').click(); await settle(500);
  ok(await page.locator('.rp-modal:visible').count() === 0, 'picking a status closes the menu');
  const sick = person('Erik Lindqvist');
  ok(/Sjuk/.test(await sick.textContent()) && /c-red/.test(await sick.getAttribute('class')), 'the row names the status and takes its colour (red)');
  ok(await sick.locator('.rp-trk').count() === 1 && await sick.locator('.rp-trk').evaluate(e => getComputedStyle(e).animationName) === 'marquee', 'with a status the name and the status scroll round like a carousel');
  ok((await sick.locator('.rp-io').textContent()) === 'UTE', 'a status that checks out shows UTE');
  await sick.locator('.rp-t').click(); await settle(300);
  await page.locator('.rp-sheet button[data-code="LATE"]').click(); await settle(300);
  ok(await page.locator('.rp-need2 input[type=time]').count() === 1, 'a status that needs a time asks for it');
  await page.locator('.rp-need2 input').fill('08:45'); await page.locator('.rp-need2 button[data-set]').click(); await settle(500);
  ok(/Kommer sent \u00b7 08:45/.test(await sick.textContent()), 'the time is part of the status text');
  await sick.locator('.rp-io').click(); await settle(500);
  ok((await sick.locator('.rp-io').textContent()) === 'INNE', 'INNE / UTE changes in / out while the status stays');
  await sick.locator('.rp-t').click(); await settle(300);
  await page.locator('.rp-sheet button[data-code=""]').click(); await settle(500);
  ok(await person('Erik Lindqvist').locator('.rp-trk').count() === 0, 'Rensa status takes the status off');
  await person('Erik Lindqvist').locator('.rp-t').click(); await settle(300);
  await page.keyboard.press('Escape'); await settle(200);
  ok(await page.locator('.rp-modal:visible').count() === 0, 'Escape closes the menu');
  await person('Erik Lindqvist').locator('.rp-io').click(); await settle(400);
  // a photo
  await person('Erik Lindqvist').locator('.rp-t').click(); await settle(300);
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==', 'base64');
  await page.locator('.rp-sheet input[type=file]').setInputFiles({ name: 'p.png', mimeType: 'image/png', buffer: png }); await settle(2500);
  ok(await page.locator('.rp-sheet .rp-av[style*="contacts/photo"]').count() === 1, 'a photo chosen in the menu is kept and shown');
  await page.keyboard.press('Escape'); await settle(200);

  // ---- a second screen follows the first within a couple of seconds
  const second = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  await second.goto(URL, { waitUntil: 'networkidle' }); await second.waitForTimeout(1500);
  await person('Maja Berg').locator('.rp-io').click(); await settle(300);
  await second.waitForTimeout(2200);
  ok(await second.locator('.rp-r.pri', { hasText: 'Maja Berg' }).count() === 1, 'another screen shows the change without a reload');
  await second.locator('.rp-r', { hasText: 'Maja Berg' }).locator('.rp-io').click(); await second.waitForTimeout(300);
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
  await page.locator('[data-box="check-in"] .srow:has-text("Title") input[type=checkbox]').uncheck(); await settle(900);
  await closeSettings(); await settle(1300);
  ok(!(await page.locator('header h1').first().isVisible()), 'Show the title off hides the title (the board starts at the top)');
  await openSettings();
  await page.locator('[data-box="check-in"] .srow:has-text("Title") input[type=checkbox]').check(); await settle(900);
  ok(await page.locator('[data-box="contacts"] .cpeople .srow').count() === 25, 'Settings lists the people on file, a switch each');
  await page.locator('[data-box="contacts"] .cpeople .srow').first().locator('input').uncheck(); await settle(1500);
  ok(/24 people/.test(await page.locator('[data-box="contacts"] .wtext').first().textContent()) || /switched off/.test(await page.locator('[data-box="contacts"] .wtext').first().textContent()), 'switching a person off takes them off the board');
  await page.locator('[data-box="contacts"] .cpeople .srow').first().locator('input').check(); await settle(1200);
  await page.locator('[data-box="contacts"] .cpeople .srow').first().locator('span').first().click(); await settle(400);
  ok(await page.locator('.rp-need2 input[data-f=name]').count() === 1 && await page.locator('.rp-need2 input[data-f=name]').isVisible(), 'a tap on a person in the list opens the editor');
  await page.locator('.rp-need2 input[data-f=role]').fill('Testroll'); await page.locator('.rp-need2 [data-save]').click(); await settle(1500);
  ok(await page.locator('.rp-modal:visible').count() === 0, 'saving closes the editor');
  ok((await page.evaluate(() => fetch('/contacts').then(r => r.json()))).people.some(p => p.role === 'Testroll'), 'the edit is kept on the host');
  await page.locator('[data-box="contacts"] .cpeople .srow').first().locator('span').first().click(); await settle(400);
  await page.locator('.rp-need2 input[data-f=name]').fill(''); await page.locator('.rp-need2 [data-save]').click(); await settle(800);
  ok(/needs a name/.test(await page.locator('.rp-cmsg').textContent()), 'an empty name is refused with a message in the editor');
  await page.keyboard.press('Escape'); await settle(300);
  ok(await page.locator('.rp-modal:visible').count() === 0, 'Esc closes the editor');
  await closeSettings(); await settle(1300);
  ok(await page.locator('header h1').first().isVisible(), 'and the title is back when it is switched on');
  await openSettings();
  await page.selectOption('[data-box="check-in"] select[aria-label="Colour of Kök"]', { label: 'Bright pink' }); await settle(800);
  await closeSettings();
  const pink = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--c-bright-pink').trim());
  await person('Anna Svensson').locator('.rp-io').click(); await settle(500);
  ok(/c-bright-pink/.test(await person('Anna Svensson').getAttribute('class')), 'a colour picked for a department is used by its rows when in (' + pink + ')');
  await person('Anna Svensson').locator('.rp-io').click(); await settle(500);
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

  // ---- roles and buildings on the rows, the touch keyboard, the carousel in a wide row
  const cfg = v => page.evaluate(x => fetch('/checkin/config', { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify({ values: x }) }).then(r => r.status), v);
  await cfg({ show_buildings: true, roles_shown: ['Chef'] }); await page.reload({ waitUntil: 'networkidle' }); await settle(1500);
  const sides = await page.locator('.rp-r .rp-s').allTextContents();
  ok(sides.some(t => /Chef . Område/.test(t)) && sides.every(t => !/Vikarie|Medarbetare/.test(t)) && sides.some(t => /^Område/.test(t)), 'a row shows the building after the role, and only the roles picked in Settings');
  await cfg({ show_roles: false }); await page.reload({ waitUntil: 'networkidle' }); await settle(1500);
  ok((await page.locator('.rp-r .rp-s').allTextContents()).every(t => !/Chef/.test(t)), 'Display roles off hides the roles');
  await openSettings();
  ok(await page.locator('[data-box="check-in"] .srow:has-text("Display roles") button:has-text("Edit")').count() === 1, 'Display roles has an Edit button');
  await page.locator('[data-box="check-in"] .srow:has-text("Display buildings") button:has-text("Edit")').click(); await settle(300);
  ok(await page.locator('.pop.open .chkbox input[type=checkbox]').count() >= 2, 'Display buildings lists the buildings to pick from');
  await page.keyboard.press('Escape'); await closeSettings();
  await cfg({ show_roles: true, show_buildings: false, roles_shown: null, keyboard: true }); await page.reload({ waitUntil: 'networkidle' }); await settle(1500);
  await page.locator('.rp-t').nth(3).click(); await settle(300);
  await page.locator('.rp-sheet button[data-code="DOCTOR"]').click(); await settle(300);
  ok(await page.locator('.rp-need2 .rp-kb [data-k=d5]').count() === 1 && await page.locator('.rp-need2 input').count() === 0, 'with the touch keyboard on, a time is typed on a number pad');
  for (const k of ['d0', 'd9', 'd1', 'd5']) await page.click('[data-k="' + k + '"]');
  await page.click('.rp-need2 [data-set]'); await settle(700);
  ok((await page.evaluate(() => fetch('/api').then(r => r.json()))).checkin.groups.some(g => g.people.some(p => p.text === 'L\u00e4karbes\u00f6k \u00b7 09:15')), 'the time typed on the pad is kept (24 h clock)');
  await page.locator('.rp-t').nth(4).click(); await settle(300);
  await page.locator('.rp-sheet button[data-code="OTHER"]').click(); await settle(300);
  for (const k of ['shift', 'cO', 'ck', 'layersym', 'c7', 'c!']) await page.click('[data-k="' + k + '"]');
  await page.click('.rp-need2 [data-k=done]'); await settle(700);
  ok((await page.evaluate(() => fetch('/api').then(r => r.json()))).checkin.groups.some(g => g.people.some(p => p.text === 'Annat \u00b7 Ok7!')), 'a note is typed on the text keyboard (letters, numbers, special characters)');
  await page.locator('.rp-t').nth(5).click(); await settle(300);
  await page.locator('.rp-sheet button[data-code="DOCTOR"]').click(); await settle(300);
  await page.click('.rp-need2 [data-set]'); await settle(300);
  ok(/Type the time/.test(await page.locator('.rp-cmsg').textContent()) && await page.locator('.rp-need2').count() === 1, 'an unfinished time is refused with a message');
  await page.keyboard.press('Escape'); await page.keyboard.press('Escape');
  await cfg({ keyboard: false });
  await page.setViewportSize({ width: 1500, height: 900 });
  await page.evaluate(() => Promise.all([['/screen', { values: { dash_cols: 2 } }], ['/screen/stretch', { value: true }]].map(([u, b]) => fetch(u, { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify(b) }))));
  await page.reload({ waitUntil: 'networkidle' }); await settle(1500);
  const fills = await page.evaluate(() => Array.from(document.querySelectorAll('#dash .rp-mq')).map(mq => { const t = mq.querySelector('.rp-trk'); return { have: t.children.length, want: 2 * Math.max(1, Math.ceil(mq.getBoundingClientRect().width / t.firstChild.getBoundingClientRect().width)) }; }));
  ok(fills.length > 0 && fills.every(f => f.have === f.want) && fills.some(f => f.have > 2), 'in a stretched wide row the carousel has enough copies of its text to fill it (' + fills.map(f => f.have + '/' + f.want).join(' ') + ')');
  await page.evaluate(() => Promise.all([['/screen', { values: { dash_cols: 1 } }], ['/screen/stretch', { value: false }]].map(([u, b]) => fetch(u, { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify(b) }))));

  // ---- delete a person (the editor, two taps), the CSV box in the app's own look
  await openSettings();
  const nBefore = (await page.evaluate(() => fetch('/contacts').then(r => r.json()))).people.length;
  ok(await page.locator('[data-box="contacts"] .cpick').count() === 1 && await page.locator('[data-box="contacts"] input[type=file]').isHidden(), 'the CSV box has a styled Choose file button instead of the browser one');
  await page.locator('[data-box="contacts"] .cpeople .srow').last().locator('span').first().click(); await settle(400);
  await page.locator('.rp-need2 [data-del]').click(); await settle(300);
  ok(/Delete/.test(await page.locator('.rp-need2 [data-del]').textContent()) && await page.locator('.pinm .rp-sheet').count() === 1 && (await page.evaluate(() => fetch('/contacts').then(r => r.json()))).people.length === nBefore, 'Delete asks in a pop-up first');
  await page.locator('.pinm button', { hasText: 'Cancel' }).click(); await settle(300);
  ok((await page.evaluate(() => fetch('/contacts').then(r => r.json()))).people.length === nBefore && await page.locator('.rp-need2 [data-del]').count() === 1, 'Cancel keeps the person');
  const order = await page.locator('.rp-need2 .rp-nb button').allTextContents();
  ok(order.join() === 'Delete,Cancel,Save', 'Delete is to the left of Cancel (' + order.join() + ')');
  await page.locator('.rp-need2 [data-del]').click(); await settle(300);
  await page.locator('.pinm button', { hasText: /^Delete$/ }).click(); await settle(1200);
  ok((await page.evaluate(() => fetch('/contacts').then(r => r.json()))).people.length === nBefore - 1 && await page.locator('.rp-modal:visible').count() === 0, 'confirming deletes the person');
  await closeSettings();

  // ---- the status editor (Settings > Statuses)
  await openSettings();
  const nSt = await page.locator('[data-box="statuses"] .cstatuses .srow').count();
  ok(nSt >= 12, 'Settings > Statuses lists the statuses (' + nSt + ')');
  await page.locator('[data-box="statuses"] button', { hasText: 'Add status' }).click(); await settle(300);
  ok(parseFloat(await page.locator('.rp-need2 input[data-f=label]').evaluate(e => getComputedStyle(e).fontSize)) >= 18, 'the editor fields have a readable font size');
  await page.locator('.rp-need2 input[data-f=label]').fill('Testst\u00e4ll'); await page.selectOption('.rp-need2 select[data-f=needs]', 'time');
  ok(await page.locator('.rp-need2 [data-row=default]').isVisible() && !(await page.locator('.rp-need2 [data-row=prefix]').isVisible()), 'a time status asks for a start time, not a date prefix');
  await page.selectOption('.rp-need2 select[data-f=dots]', '2'); await page.locator('.rp-need2 input[data-f=sticky]').check(); await page.locator('.rp-need2 [data-save]').click(); await settle(1200);
  const made = (await page.evaluate(() => fetch('/api').then(r => r.json()))).checkin.statuses.find(x => x.label === 'Testst\u00e4ll');
  ok(made && made.sticky && made.dots === 2 && made.needs === 'time', 'the new status is saved with its settings (' + JSON.stringify(made) + ')');
  await page.locator('[data-box="statuses"] .cstatuses .srow', { hasText: 'Testst\u00e4ll' }).locator('button[aria-label$="up"]').click(); await settle(1000);
  const labels = (await page.evaluate(() => fetch('/api').then(r => r.json()))).checkin.statuses.map(x => x.label);
  ok(labels.indexOf('Testst\u00e4ll') === labels.length - 2, 'the arrows move a status');
  await page.locator('[data-box="statuses"] .cstatuses .srow', { hasText: 'Testst\u00e4ll' }).locator('span').first().click(); await settle(300);
  await page.locator('.rp-need2 [data-del]').click(); await settle(300);
  await page.locator('.pinm button', { hasText: /^Delete$/ }).click(); await settle(1200);
  ok((await page.evaluate(() => fetch('/api').then(r => r.json()))).checkin.statuses.length === nSt, 'a status is deleted after a question');
  await closeSettings();

  ok(errors.length === 0, 'no JavaScript errors (' + errors.slice(0, 3).join(' | ') + ')');
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

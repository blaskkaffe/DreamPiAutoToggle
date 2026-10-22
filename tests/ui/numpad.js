// The number pad on the board (type a person's 3-digit number, then 1 / 0 / # or a two-digit status number) and the optimistic INNE / UTE button.
// Run by run.sh against its own demo server.
const { chromium } = require('playwright');
const BASE = 'http://127.0.0.1:' + (process.env.PORT || 8741);
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error' && !/status of (400|401|409)|ERR_FAILED/.test(m.text())) errors.push(m.text().slice(0, 150)); });
  const post = (path, body) => page.evaluate(([p, b]) => fetch(p, { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.status), [path, body]);
  const board = () => page.evaluate(() => fetch('/api').then(r => r.json()).then(d => d.checkin));
  const person = async name => { const b = await board(); let f = null; b.groups.forEach(g => g.people.forEach(p => { if (p.name === name) f = p; })); return f; };
  await page.goto(BASE + '/', { waitUntil: 'networkidle' }); await settle(800);
  const anna = await person('Anna Svensson');
  ok(await post('/contacts/person', { id: anna.id, code: '127' }) === 200, 'Anna gets the number 127');
  ok(await post('/contacts/person', { id: (await person('Erik Lindqvist')).id, code: '127' }) === 400, 'the same number for somebody else is refused');
  await page.reload({ waitUntil: 'networkidle' }); await settle(1200);
  const menu = page.locator('.rp-modal:not(.rp-modal2) .rp-sheet');

  await page.keyboard.type('1'); await settle(100);
  ok(await page.locator('.rp-typed').isVisible() && (await page.locator('.rp-typed').textContent()) === '1', 'a digit shows what has been typed');
  await page.keyboard.press('Backspace'); await settle(100);
  ok(!(await page.locator('.rp-typed').isVisible()), 'Backspace takes it back');
  await page.keyboard.type('999'); await settle(200);
  ok(/No such number/.test(await page.locator('.rp-typed').textContent()) && !(await menu.isVisible()), 'an unknown number says so and opens nothing');
  await settle(1700);

  await page.keyboard.type('127'); await settle(300);
  ok(await menu.isVisible() && /Anna Svensson/.test(await menu.textContent()), 'the person\'s number opens their status menu');
  ok(await menu.locator('.rp-num').first().textContent() === '20', 'the status buttons show their numbers, from 20');
  await page.keyboard.press('1'); await settle(700);
  ok(!(await menu.isVisible()) && (await person('Anna Svensson')).in === true, '1 checks them in and closes the menu');
  await page.keyboard.type('127'); await page.keyboard.press('0'); await settle(700);
  ok((await person('Anna Svensson')).in === false, '0 checks them out');
  await page.keyboard.type('127'); await page.keyboard.press('#'); await settle(700);
  ok((await person('Anna Svensson')).in === true, '# switches them');
  await page.keyboard.type('127'); await page.keyboard.type('20'); await settle(700);
  const a = await person('Anna Svensson');
  const first = (await board()).statuses[0].code;
  ok(a.status === first, 'two digits pick a status (20 is the first: ' + first + ')');
  await page.keyboard.type('127'); await page.keyboard.press('*'); await settle(200);
  ok(!(await menu.isVisible()), '* with nothing typed closes the menu');
  await page.keyboard.type('127'); await page.keyboard.press('5'); await page.keyboard.press('9'); await settle(300);
  ok(await menu.isVisible() && /No such number/.test(await page.locator('.rp-typed').textContent()), 'an unknown status number says so and the menu stays');
  await page.keyboard.press('Escape'); await settle(200);
  ok(!(await menu.isVisible()), 'Esc closes the menu');

  // the setting switches it off
  await post('/checkin/config', { values: { numpad: false } }); await settle(1500);
  await page.keyboard.type('127'); await settle(300);
  ok(!(await menu.isVisible()), 'with the number pad off nothing happens');
  await post('/checkin/config', { values: { numpad: true } }); await settle(1500);

  // a field that has the keyboard keeps its digits
  await page.click('#cog'); await settle(800);
  await page.keyboard.type('127'); await settle(300);
  ok(!(await menu.isVisible()), 'with Settings open the digits are not taken');
  await page.keyboard.press('Escape'); await page.reload({ waitUntil: 'networkidle' }); await settle(1200);

  // the INNE / UTE button switches at once, before the answer comes
  await page.route('**/checkin/toggle', async route => { await settle(1500); route.continue(); });
  const row = page.locator('.rp-r', { hasText: 'Erik Lindqvist' }), btn = row.locator('.rp-io');
  const before = (await btn.textContent()).trim();
  await btn.click(); await settle(250);
  const after = (await row.locator('.rp-io').textContent()).trim();
  ok(before !== after, 'the button switched within 250 ms although the answer takes 1.5 s (' + before + ' -> ' + after + ')');
  await settle(2200);
  ok((await row.locator('.rp-io').textContent()).trim() === after, 'and stays switched when the answer arrives');
  await page.unroute('**/checkin/toggle');
  await page.route('**/checkin/toggle', route => route.abort());
  await row.locator('.rp-io').click(); await settle(500);
  ok((await row.locator('.rp-io').textContent()).trim() === after, 'a request that fails puts the row back');

  ok(errors.length === 0, 'no page errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' FAILED' : 'all ok');
  process.exit(failed ? 1 : 0);
})();

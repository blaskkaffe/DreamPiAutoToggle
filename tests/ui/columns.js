// Long groups and the order of the boxes (run by run.sh against a demo server with long.csv: 30 + 4 + 3 people):
// a group too tall for one column's height is cut into near-equal parts in the next columns; No scrolling keeps the main screen still;
// the order the boxes are dragged into is kept on the host.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8741) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  const post = (path, body) => page.evaluate(([p, b]) => fetch(p, { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then(r => r.status), [path, body]);
  const load = async () => { await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1500); };
  const tiles = () => page.evaluate(() => Array.from(document.querySelectorAll('#dash .rp-tile')).sort((a, b) => a._ord - b._ord).map(t => {
    const r = t.getBoundingClientRect(), col = t.closest('.dcol');
    return { title: t.querySelector('.rp-gt').textContent, rows: t.querySelectorAll('.rp-r').length, bottom: Math.round(r.bottom), col: col ? Array.from(col.parentNode.children).indexOf(col) : 0 };
  }));
  await load();
  await post('/screen', { values: { dash_cols: 3 } });
  await post('/screen/stretch', { value: true });
  await load();
  let t = await tiles();
  const kok = t.filter(x => x.title.startsWith('Kök'));
  ok(kok.length >= 2 && kok.reduce((a, x) => a + x.rows, 0) === 30, 'the 30 people of Kök are cut into parts (' + JSON.stringify(kok) + ')');
  ok(kok[0].title.indexOf('(1/' + kok.length + ')') > 0, 'the parts are numbered');
  ok(Math.max(...kok.map(x => x.rows)) - Math.min(...kok.map(x => x.rows)) <= 1, 'the parts are near-equal');
  ok(t.every(x => x.bottom <= 1080), 'every part fits in the screen height (' + t.map(x => x.bottom).join(',') + ')');
  ok(new Set(kok.map(x => x.col)).size === kok.length, 'the parts are in different columns');
  // one column: nothing is cut
  await post('/screen', { values: { dash_cols: 1 } });
  await load();
  t = await tiles();
  ok(t.filter(x => x.title.startsWith('Kök')).length === 1, 'one column: Kök is a single box');
  // No scrolling
  await post('/screen', { values: { dash_cols: 3 } });
  await post('/screen/noscroll', { value: true });
  await load();
  ok(await page.evaluate(() => document.documentElement.classList.contains('noscroll') && getComputedStyle(document.body).overflow === 'hidden'), 'No scrolling: the main screen does not scroll');
  ok(await page.evaluate(() => getComputedStyle(document.documentElement).overflow === 'hidden'), 'there is no scrollbar and no wheel / touch scrolling');
  await page.click('#cog'); await settle(900);
  ok(await page.evaluate(() => getComputedStyle(document.documentElement).overflow !== 'hidden'), 'Settings can scroll again');
  await page.click('#close-settings'); await settle(300);
  ok(await page.evaluate(() => (window.pageYOffset || 0) === 0), 'closing Settings brings the main screen back to the top');
  await post('/screen/noscroll', { value: false });
  // the order of the boxes
  const before = (await tiles()).map(x => x.title).filter(x => !x.startsWith('Kök'));
  await post('/checkin/order', { order: ['Servering', 'Kontor', 'Kök'] });
  await load();
  t = await tiles();
  ok(t.map(x => x.title)[0] === 'Servering' && t[1].title === 'Kontor', 'the saved order is drawn: ' + t.map(x => x.title).join(' | ') + ' (was ' + before.join(' | ') + ')');
  await page.screenshot({ path: '/tmp/dpns-columns.png' });
  ok(errors.length === 0, 'no JS errors ' + errors.join('; '));
  await browser.close();
  process.exit(failed ? 1 : 0);
})();

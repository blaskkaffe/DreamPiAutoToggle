// A tall screen (1080 x 1920) with two columns and N people (run.sh runs it for 20, 40, 60 and 80; N comes from the environment, the roster from make_people.py:
// groups of 1 to 15, mostly 6 to 12): Stretch + two columns + Fit to screen must show everybody without scrolling, in two balanced columns, with every name whole.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8741) + '/', N = +(process.env.N || 40);
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  const post = (path, body) => page.evaluate(([p, b]) => fetch(p, { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.status), [path, body]);
  await page.goto(URL, { waitUntil: 'networkidle' });
  await post('/screen', { values: { dash_cols: 2 } }); await post('/screen/stretch', { value: true }); await post('/screen/fit', { value: true });
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(2500);
  const m = await page.evaluate(() => {
    const d = document.getElementById('dash'), cols = Array.from(d.querySelectorAll(':scope > .dcol')), boxes = Array.from(document.querySelectorAll('.rp-box')).filter(b => b.offsetHeight);
    const colH = cols.map(c => { const b = Array.from(c.querySelectorAll('.rp-box')).filter(x => x.offsetHeight), r = b.length ? b[b.length - 1].getBoundingClientRect().bottom - b[0].getBoundingClientRect().top : 0; return Math.round(r); });
    const rows = Array.from(document.querySelectorAll('.rp-r')).filter(r => r.offsetHeight), n = Array.from(document.querySelectorAll('.rp-n')).filter(e => e.offsetHeight);
    const sizes = boxes.map(b => b.querySelectorAll('.rp-r').length).sort((a, b) => a - b);
    return { people: rows.length, cols: cols.length, colH, sizes, scrollH: document.documentElement.scrollHeight, vh: innerHeight, scrollW: document.documentElement.scrollWidth, vw: innerWidth,
             cut: n.filter(e => e.scrollWidth > e.clientWidth + 1).length, minRow: Math.min.apply(null, rows.map(r => Math.round(r.getBoundingClientRect().height))), maxRow: Math.max.apply(null, rows.map(r => Math.round(r.getBoundingClientRect().height))),
             font: getComputedStyle(document.querySelector('.rp-t')).fontSize, z: d.style.getPropertyValue('--z'), fz: d.style.getPropertyValue('--fz') };
  });
  console.log('     ' + JSON.stringify(m));
  ok(m.people === N, N + ' people are on the board (' + m.people + ')');
  ok(m.cols === 2 && m.colH.every(h => h > 0), 'two columns, both used (' + m.colH.join(' / ') + ' px)');
  ok(m.sizes[0] <= 15 && m.sizes[m.sizes.length - 1] <= 15 && (N < 36 || (m.sizes[0] === 1 && m.sizes[m.sizes.length - 1] === 15)), 'the groups run from ' + m.sizes[0] + ' to ' + m.sizes[m.sizes.length - 1] + ' people (' + m.sizes.join(',') + ')');
  ok(m.scrollW <= m.vw, 'nothing sticks out sideways (' + m.scrollW + ' of ' + m.vw + ' px)');
  ok(m.scrollH <= m.vh + 2, 'everybody is on the screen at once, no scrolling (' + m.scrollH + ' of ' + m.vh + ' px; text ' + m.font + ')');
  ok(Math.min.apply(null, m.colH) >= 0.78 * Math.max.apply(null, m.colH), 'the two columns are about equally tall (' + m.colH.join(' / ') + ')');
  ok(m.cut === 0, 'every name is shown whole (' + m.cut + ' cut)');
  ok(m.minRow >= 30, 'a row is tall enough to tap (' + m.minRow + ' px at the smallest)');
  await page.screenshot({ path: '/tmp/dpns-portrait-' + N + '.png' });
  // people go in and out and a status is set: the layout holds (nothing jumps to another column or scrolls)
  const before = await page.evaluate(() => Array.from(document.querySelectorAll('.rp-box')).map(b => b.getBoundingClientRect().top + ':' + b.parentNode.className).join());
  await page.locator('.rp-io').first().click(); await settle(1500);
  ok(await page.evaluate(() => document.documentElement.scrollHeight) <= 1922, 'a person checked in: still no scrolling');
  ok(await page.evaluate(() => Array.from(document.querySelectorAll('.rp-box')).map(b => b.getBoundingClientRect().top + ':' + b.parentNode.className).join()) === before, 'and no box has moved');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.slice(0, 2).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

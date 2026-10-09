// The look of the board (run by run.sh against its own demo server): text colour and size, Classic boxes, corners and gaps, the theme by the time of day,
// button sounds and the Snow background.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8741) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  const post = (path, body) => page.evaluate(([p, b]) => fetch(p, { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify(b) }).then(r => r.status), [path, body]);
  const load = async () => { await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1500); };
  const css = (sel, prop) => page.evaluate(([s, p]) => getComputedStyle(document.querySelector(s))[p], [sel, prop]);
  const cfg = v => page.evaluate(x => fetch('/checkin/config', { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify({ values: x }) }).then(r => r.status), v);
  await load();

  // ---- the boxes: the original dark grey in the dark theme (the page starts dark), light grey in the light theme; the text follows (automatic: the original greys / black)
  const rows = () => page.evaluate(() => document.documentElement.getAttribute('data-rows'));
  ok(await rows() === 'dark' && await css('.rp-box', 'backgroundColor') === 'rgb(27, 27, 27)', 'in the dark theme the boxes are the original dark grey (' + await css('.rp-box', 'backgroundColor') + ')');
  ok(await css('.rp-r.out .rp-n', 'color') === 'rgb(204, 204, 204)' && await css('.rp-r.out', 'backgroundColor') === 'rgba(42, 42, 42, 0.82)', 'with the original row greys and the original text colours');
  ok(await css('.rp-gh', 'backgroundColor') === 'rgba(0, 0, 0, 0)', 'no coloured title row (that is the board colour setting)');
  await post('/screen', { values: { theme: 'light' } }); await settle(1500);
  ok(await rows() === 'light' && await css('.rp-n', 'color') === 'rgb(0, 0, 0)' && await css('.rp-box', 'backgroundColor') === 'rgb(236, 236, 236)', 'in the light theme: light grey boxes and black text (automatic)');
  await cfg({ box: 'dark' }); await page.reload({ waitUntil: 'networkidle' }); await settle(1500);
  ok(await rows() === 'dark' && await css('.rp-box', 'backgroundColor') === 'rgb(27, 27, 27)', 'the box colour can be dark grey also in the light theme');
  await post('/screen', { values: { theme: 'dark' } }); await cfg({ box: 'light' }); await page.reload({ waitUntil: 'networkidle' }); await settle(1500);
  ok(await rows() === 'light' && await css('.rp-n', 'color') === 'rgb(0, 0, 0)', 'and light grey (with black text) in the dark theme');
  await cfg({ box: 'auto' }); await page.reload({ waitUntil: 'networkidle' }); await settle(1500);
  ok(await post('/screen', { values: { font_colour: 'black' } }) === 200, 'a text colour can be chosen by hand');
  await settle(1500);
  ok(await css('.rp-n', 'color') === 'rgb(0, 0, 0)' && await rows() === 'light', 'black text brings light boxes (it could not be read on dark ones)');
  ok(await post('/screen', { values: { font_colour: 'white' } }) === 200 && (await settle(1500), await css('.rp-n', 'color')) === 'rgb(255, 255, 255)' && await rows() === 'dark', 'white text on the dark ones');
  ok(await post('/screen', { values: { font_colour: 'red' } }) === 200 && (await settle(1500), await css('.rp-n', 'color')) !== 'rgb(255, 255, 255)', 'any palette colour can be the text colour');
  await post('/screen', { values: { font_colour: 'auto' } });

  // ---- text size: its own scaler; Stretch, Scale content and Fit never change it
  await settle(1500);
  ok(await css('.rp-t', 'fontSize') === '28px', 'the names are 28 px at the normal size');
  await post('/screen', { values: { font_scale: 2 } }); await settle(1500);
  ok(await css('.rp-t', 'fontSize') === '56px', 'text size 2x doubles the text');
  await post('/screen', { values: { font_scale: 0.5 } }); await settle(1500);
  ok(await css('.rp-t', 'fontSize') === '14px', 'text size 0.5x halves it');
  ok(await post('/screen', { values: { font_scale: 9 } }) === 200 && (await settle(1200), await css('.rp-t', 'fontSize')) === '56px', 'more than 2x is held at 2x');
  await post('/screen', { values: { font_scale: 1 } });
  await post('/screen/stretch', { value: true }); await post('/screen/scale', { value: true }); await post('/screen', { values: { dash_cols: 3 } }); await settle(1800);
  ok(await css('.rp-t', 'fontSize') === '28px', 'stretched and scaled, the text is still 28 px (it was the text that grew before)');

  // ---- corners and gaps
  const g = await page.evaluate(() => {
    const cols = Array.from(document.querySelectorAll('#dash > .dcol')), boxes = c => Array.from(c.querySelectorAll('.rp-box')).filter(b => b.offsetHeight);
    const colGap = cols.length > 1 ? cols[1].getBoundingClientRect().left - cols[0].getBoundingClientRect().right : null;
    const withTwo = cols.map(boxes).find(b => b.length > 1), inGap = withTwo ? withTwo[1].getBoundingClientRect().top - withTwo[0].getBoundingClientRect().bottom : null;
    return { colGap, inGap, radius: getComputedStyle(document.querySelector('.rp-box')).borderTopLeftRadius, cols: cols.length };
  });
  ok(g.cols === 3 && g.radius === '29px', 'the corners keep their radius when the boxes are stretched and scaled (' + g.radius + ')');
  ok(g.colGap !== null && g.inGap !== null && Math.abs(g.colGap - g.inGap) < 1.5, 'the space between columns is the same as between the boxes of a column (' + g.colGap + ' / ' + g.inGap + ')');
  await post('/screen/stretch', { value: false }); await post('/screen/scale', { value: false }); await post('/screen', { values: { dash_cols: 1 } });

  // ---- Settings: the new rows
  await load(); await page.click('#cog'); await settle(1200);
  const app = page.locator('[data-box="appearance"]');
  ok(await app.locator('.wmenu').count() === 4, 'Appearance has four menus (Layout, Text, Colours, Background)');
  await page.evaluate(() => document.querySelectorAll('.wmenu .menubtn[aria-expanded="false"]').forEach(b => b.click())); await settle(300);
  for (const t of ['Theme', 'Hide the top bar', 'Max columns: dashboard', 'Stretch boxes', 'Fit to screen', 'Rearrange the main screen', 'No scrolling', 'Text size', 'Text colour', 'Button sounds', 'Colour palette', 'Global main colour', 'Check-in board colour']) ok(await app.locator('.srow', { hasText: t }).count() >= 1, 'Appearance has a "' + t + '" row');
  ok(await page.locator('[data-box="colours"], [data-box="about"]').count() === 0, 'the Global colours and About boxes are gone');
  ok(await page.locator('[data-box="system"] .srow', { hasText: 'Time zone' }).count() === 1 && await page.locator('[data-box="system"] .srow', { hasText: 'Ask for the PIN' }).count() === 1, 'the time zone and the PIN are in System');
  const sub = await app.locator('.wmenu').filter({ has: page.locator('.menuhead', { hasText: /^Text/ }) }).locator('.menuhead .sub').textContent();
  ok(/Text size 1\u00d7/.test(sub) && /Automatic/.test(sub), 'a menu shows what is chosen in it as its subtitle (' + sub + ')');
  await page.click('#close-settings'); await settle(300);

  // ---- the theme by the time of day
  ok(await post('/screen', { values: { theme: 'time' } }) === 200, 'the theme can follow the time of day');
  await settle(1500); await load();
  const dl = await page.evaluate(() => ({ day: S.daylight.day, elev: S.daylight.elev, theme: document.documentElement.getAttribute('data-theme') }));
  ok(typeof dl.elev === 'number' && dl.theme === (dl.day ? 'light' : 'dark'), 'light while the sun is up, dark at night (' + JSON.stringify(dl) + ')');
  await post('/screen', { values: { theme: 'dark' } });

  // ---- button sounds
  await load();
  const snd = await page.evaluate(() => new Promise(res => setTimeout(() => res({ keys: Object.keys(Snd.buf), on: Snd.on, vol: Snd.vol, want: Snd.want }), 1500)));
  ok(snd.on && snd.keys.indexOf('pop.wav') >= 0 && snd.want === 'pop.wav', 'the pop sound is loaded (' + JSON.stringify(snd) + ')');
  const list = await page.evaluate(() => fetch('/screen').then(r => r.json()));
  ok(list.options.sounds.map(s => s.value).join() === 'off,bubble.wav,pop.wav,tick.wav', 'the sounds folder is listed in Settings, with Off (' + list.options.sounds.map(s => s.value).join() + ')');
  ok(await page.evaluate(() => fetch('/sounds/tick.wav').then(r => r.headers.get('content-type'))) === 'audio/wav', 'a sound is served as audio');
  await post('/screen', { values: { sound_name: 'off' } }); await post('/screen', { values: { sound_volume: 0.3 } }); await settle(1500); await load();
  ok(await page.evaluate(() => fetch('/screen').then(r => r.json()).then(j => j.values.sound_name)) === 'off', 'Off in the sound list switches the button sounds off');
  await post('/screen', { values: { sound_name: 'tick.wav' } }); await settle(1500); await load();
  await post('/screen', { values: { sound_name: 'off' } }); await settle(1500); await load();
  ok(await page.evaluate(() => !Snd.on && Snd.want === 'tick.wav' && Math.abs(Snd.vol - 0.3) < 0.001), 'sound off, another sound and a volume are applied');
  await post('/screen/sound', { value: true }); await post('/screen', { values: { sound_name: 'pop.wav', sound_volume: 0.6 } });

  // ---- the Snow background
  ok(await post('/modules', { name: 'snow', enabled: true }) === 200, 'the Snow background module can be switched on');
  await settle(800); await post('/snow', { values: { amount: 'heavy', fog: 'thick', wind: 'storm', time: 'night' } }); await load(); await settle(2500);
  const sn = await page.evaluate(() => { const c = document.getElementById('snowbg'); return { has: !!c, w: c ? c.width : 0, on: document.body.classList.contains('snow-on'), bg: getComputedStyle(document.body).backgroundColor, fixed: c ? getComputedStyle(c).position : '' }; });
  ok(sn.has && sn.w > 300 && sn.on && sn.fixed === 'fixed' && sn.bg === 'rgba(0, 0, 0, 0)', 'a canvas behind the page draws the snow (' + JSON.stringify(sn) + ')');
  ok(await page.evaluate(() => { const c = document.createElement('canvas'); return !!c.getContext('webgl'); }), 'WebGL is available in this browser, so it is the 3D version that runs');
  const frames = await page.evaluate(() => new Promise(res => { let n = 0; const t0 = performance.now(); (function f() { n++; if (performance.now() - t0 < 1000) requestAnimationFrame(f); else res(n); })(); }));
  ok(frames >= 5, 'the page stays responsive while it draws (' + frames + ' frames in a second, software GL)');
  await post('/snow', { values: { time: 'day' } }); await settle(300);
  await post('/modules', { name: 'snow', enabled: false }); await load();
  ok(await page.evaluate(() => !document.getElementById('snowbg') && !document.body.classList.contains('snow-on')), 'switched off, the page is as before');

  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

// The Background image module in the browser (run by run.sh against a demo server started with IMGBG=1): choosing a picture makes it the
// page's background, a big one is shrunk before it is sent, fit and darken change the look, and Remove brings the normal page back.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8742) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 420, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  page.on('dialog', d => d.accept());
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1000);
  const look = () => page.evaluate(() => { const p = document.getElementById('imgbg'), d = document.getElementById('imgbg-dim');
    return { on: document.body.classList.contains('imgbg-on'), shown: p ? getComputedStyle(p).display : '', img: p ? p.style.backgroundImage : '', size: p ? p.style.backgroundSize : '', dim: d ? d.style.opacity : '', bodyBg: getComputedStyle(document.body).backgroundColor }; });
  let l = await look();
  ok(!l.on && l.shown === 'none', 'without a picture the page looks as usual (' + JSON.stringify(l) + ')');
  await page.click('#cog'); await settle(1200);
  const box = page.locator('[data-box="background-image"]');
  ok(await box.count() === 1, 'Settings has a Background image box');
  const row = box.locator('.srow', { hasText: 'Picture' });
  ok(!(await row.locator('button', { hasText: 'Remove' }).isVisible()), 'with no picture there is no Remove button');
  // a small picture: a 40x30 PNG made in the page
  const png = async (w, h, noise) => Buffer.from((await page.evaluate(([w, h, noise]) => { const c = document.createElement('canvas'); c.width = w; c.height = h; const x = c.getContext('2d');
    const img = x.createImageData(w, h); for (let i = 0; i < img.data.length; i += 4) { const v = noise ? Math.random() * 255 : (i / 4) % 255; img.data[i] = v; img.data[i + 1] = 255 - v; img.data[i + 2] = 120; img.data[i + 3] = 255; } x.putImageData(img, 0, 0);
    return c.toDataURL('image/png').split(',')[1]; }, [w, h, noise])), 'base64');
  await page.locator('.imgbg-file').setInputFiles({ name: 'small.png', mimeType: 'image/png', buffer: await png(40, 30, false) }); await settle(1800);
  l = await look();
  ok(l.on && l.shown === 'block' && /\/imagebg\/image\?v=\d+/.test(l.img), 'the picture becomes the background (' + l.img + ')');
  ok(l.size === 'cover' && l.dim === '0.25', 'cover and 25 % darker to start with');
  ok(l.bodyBg === 'rgba(0, 0, 0, 0)', 'the page itself is see-through then');
  const got = await page.evaluate(() => fetch(document.getElementById('imgbg').style.backgroundImage.slice(5, -2)).then(r => r.headers.get('content-type')));
  ok(got === 'image/png', 'the computer serves it as an image (' + got + ')');
  ok(await row.locator('button', { hasText: 'Remove' }).isVisible(), 'now there is a Remove button');
  // fit and darken
  await box.locator('.srow', { hasText: 'Fit' }).locator('button').click(); await settle(300);
  await page.locator('.pop.open .optrow button', { hasText: 'Stretch' }).click(); await settle(1500);
  ok((await look()).size === '100% 100%', 'Stretch changes how it is fitted');
  await box.locator('.srow', { hasText: 'Darken' }).locator('button').click(); await settle(300);
  await page.locator('.pop.open .optrow button', { hasText: '75 %' }).click(); await settle(1500);
  ok((await look()).dim === '0.75', 'Darken changes how dark it is');
  // a big picture is shrunk first
  const big = await png(3600, 2400, true);
  ok(big.length > 8000000 || big.length > 1500000, 'a big test picture (' + Math.round(big.length / 1000) + ' KB)');
  await page.locator('.imgbg-file').setInputFiles({ name: 'big.png', mimeType: 'image/png', buffer: big }); await settle(5000);
  const info = await page.evaluate(() => fetch(document.getElementById('imgbg').style.backgroundImage.slice(5, -2)).then(r => r.blob()).then(b => createImageBitmap(b).then(i => ({ type: b.type, w: i.width, h: i.height, size: b.size }))));
  ok(info.type === 'image/jpeg' && Math.max(info.w, info.h) <= 2560 && info.size < 8000000, 'it arrives as a JPEG of at most 2560 px (' + JSON.stringify(info) + ')');
  // remove
  await row.locator('button', { hasText: 'Remove' }).click(); await settle(1800);
  l = await look();
  ok(!l.on && l.shown === 'none', 'Remove brings the usual page back');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

// The Dreamcast background must cover the whole window, in portrait and landscape and after the window is turned or resized (run by run.sh
// against a demo server started with BG=1; WebGL runs in software here).
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8738) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ args: ['--use-gl=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(3000);
  const cover = () => page.evaluate(() => { const l = document.getElementById('dcbg'), c = l && l.querySelector('canvas'), r = l.getBoundingClientRect();
    return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, w: innerWidth, h: innerHeight, cw: c ? c.clientWidth : 0, ch: c ? c.clientHeight : 0, lw: Math.round(r.width), lh: Math.round(r.height) }; });
  for (const [name, w, h] of [['portrait', 390, 844], ['a tall phone', 360, 1000], ['landscape', 844, 390], ['portrait again', 390, 844], ['desktop', 1280, 720]]) {
    await page.setViewportSize({ width: w, height: h }); await settle(1200);
    const c = await cover();
    ok(c.top <= 0 && c.bottom >= c.h && c.left <= 0 && c.right >= c.w, name + ' (' + w + 'x' + h + '): the background layer covers the whole window (' + Math.round(c.top) + '..' + Math.round(c.bottom) + ')');
    ok(c.cw === c.lw && c.ch === c.lh && c.ch >= c.h, name + ': the scene is drawn at the layer\'s size (' + c.cw + 'x' + c.ch + ')');
  }
  ok(errors.length === 0, 'no JavaScript errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

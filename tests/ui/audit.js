const { chromium } = require('playwright');
const AUDIT = () => {
  const out = [];
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0'; };
  const sel = el => { let s = el.tagName.toLowerCase(); if (el.id) s += '#' + el.id; else if (el.className && typeof el.className === 'string') s += '.' + el.className.trim().split(/\s+/).slice(0,2).join('.'); return s; };
  const W = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > W + 1) out.push(['page-hscroll', document.documentElement.scrollWidth + ' > ' + W]);
  const all = Array.from(document.querySelectorAll('body *')).filter(vis);
  const inSettings = !!document.querySelector('#settings.open');
  all.forEach(el => {
    if (el.closest('svg') && el.tagName !== 'svg') return;
    if (inSettings && !el.closest('#settings')) return;
    if (!inSettings && el.closest('#settings')) return;
    const r = el.getBoundingClientRect();
    if (el.closest('#log')) return;
    if (el.closest('.mq') || el.matches('.v')&&el.querySelector('.mq')) return;   // the scrolling games line is meant to run past its box
    if (r.right > W + 1 || r.left < -1) out.push(['outside-viewport', sel(el) + ' ' + Math.round(r.left) + '..' + Math.round(r.right)]);
    const card = el.closest('.card, .pill, .wide, .warnbox, .now');
    if (card && card !== el) { const c = card.getBoundingClientRect(); if (r.right > c.right + 1 || r.left < c.left - 1) out.push(['overflows-box', sel(el) + ' in ' + sel(card) + ' by ' + Math.round(Math.max(r.right - c.right, c.left - r.left)) + 'px']); }
    const cs = getComputedStyle(el);
    if ((cs.overflow !== 'visible' || cs.overflowX !== 'visible') && el.scrollWidth > el.clientWidth + 1 && cs.textOverflow !== 'ellipsis' && !el.matches('textarea,select,input,pre,#settings,.in'))
      out.push(['clipped-or-scrolling', sel(el) + ' ' + el.scrollWidth + '>' + el.clientWidth]);
    if (/^(BUTTON|A|INPUT|SELECT|SUMMARY)$/.test(el.tagName) && !(el.type === 'checkbox' && el.classList.contains('cbox'))) {
      if (Math.min(r.width, r.height) < 28) out.push(['small-tap-target', sel(el) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height) + ' "' + (el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 20) + '"']);
    }
    if (/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName) && el.type !== 'hidden') {
      const named = el.getAttribute('aria-label') || el.getAttribute('title') || (el.labels && el.labels.length) || el.closest('label');
      if (!named) out.push(['unlabelled-control', sel(el) + ' ' + (el.type || '')]);
    }
    if (el.tagName === 'BUTTON' && !(el.textContent || '').trim() && !el.getAttribute('aria-label') && !el.getAttribute('title')) out.push(['unlabelled-button', sel(el)]);
    const fs = parseFloat(cs.fontSize);
    if (fs < 11.5 && el.childNodes.length && Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim())) out.push(['tiny-text', sel(el) + ' ' + fs + 'px "' + el.textContent.trim().slice(0, 20) + '"']);
    if (el.classList.contains('pill-s') && el.closest('.srow, .nadd, .bar') && r.width > 240 && !el.closest('.pop, #wifi-networks, .now')) out.push(['pill-stretched', sel(el) + ' w=' + Math.round(r.width) + ' "' + el.textContent.trim().slice(0, 20) + '"']);
    // wrapped single-word buttons (a pill whose label breaks onto 2 lines)
    if (/^(BUTTON|A)$/.test(el.tagName) && el.classList.contains('pill-s') && r.height > 46) out.push(['pill-wraps', sel(el) + ' h=' + Math.round(r.height) + ' "' + el.textContent.trim() + '"']);
  });
  const ids = {}; document.querySelectorAll('[id]').forEach(e => { ids[e.id] = (ids[e.id] || 0) + 1; });
  Object.keys(ids).filter(k => ids[k] > 1).forEach(k => out.push(['duplicate-id', k]));
  return out;
};
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const summary = {};
  for (const [w, h] of [[360, 800], [420, 900], [768, 1000], [1280, 900]]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    const problems = [];
    page.on('pageerror', e => problems.push(['js-error', String(e)]));
    page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') problems.push(['console-' + m.type(), m.text().slice(0, 120)]); });
    page.on('response', r => { if (r.status() >= 400 && !/favicon|apple-touch/.test(r.url())) problems.push(['http-' + r.status(), r.url()]); });
    page.on('dialog', d => d.accept());
    await page.goto('http://127.0.0.1:' + (process.env.PORT || 8734) + '/', { waitUntil: 'networkidle' });
    await page.waitForTimeout(1200);
    const check = async (label) => { const res = await page.evaluate(AUDIT); res.forEach(r => problems.push([r[0], label + ': ' + r[1]])); };
    await check('main closed');
    await page.click('#net'); await page.waitForTimeout(300); await check('main net open');
    await page.click('#pl-toggle'); await page.waitForTimeout(2500); await check('main players open');
    await page.click('#show-debug'); await page.waitForTimeout(500); await check('main debug open');
    await page.screenshot({ path: `/tmp/dpns-audit-main-${w}.png`, fullPage: true });
    await page.click('#cog'); await page.waitForTimeout(1500); await check('settings');
    // wifi flow states
    await page.click('#wifi-b'); await page.waitForTimeout(4500); await check('settings wifi list');
    await page.click('.wnet:nth-child(4)'); await page.waitForTimeout(300); await check('settings wifi chosen long ssid');
    await page.screenshot({ path: `/tmp/dpns-audit-settings-${w}.png`, fullPage: true });
    await page.click('#wifi-b'); await page.waitForTimeout(1500);
    // popups
    await page.evaluate(() => { const b = document.querySelector('#led-rows .fx'); if (b) b.click(); }); await page.waitForTimeout(300); await check('fx popup');
    await page.keyboard.press('Escape');
    // switch button functions
    await page.selectOption('#btn1-fn', 'sw_wifi'); await page.waitForTimeout(500); await check('switch fn selected');
    await page.selectOption('#btn1-fn', 'toggle'); await page.waitForTimeout(500);
    summary[w] = problems;
    await page.close();
  }
  let bad = 0;
  for (const w of Object.keys(summary)) {
    const seen = {};
    summary[w].forEach(p => { const k = p[0] + ' | ' + p[1]; seen[k] = (seen[k] || 0) + 1; });
    console.log('=== width ' + w + ': ' + Object.keys(seen).length + ' distinct findings');
    Object.keys(seen).filter(k => !k.startsWith('tiny-text') && !/small-tap-target \| .*input#(wb-[rgb]|led-bright|lvl-r)/.test(k)).forEach(k => { console.log('  ' + k); bad++; });
  }
  await browser.close();
  console.log(bad ? bad + ' finding(s)' : 'no findings (tiny text and native range sliders are ignored)');
  process.exit(bad ? 1 : 0);
})();

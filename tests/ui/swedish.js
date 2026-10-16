// The page in Swedish (run with LANG_UI=sv): the language can be switched in Settings (the page loads again, every screen follows), and no English is left in
// Settings, the status menus, the pop-ups and the keyboards (window.TRMISS lists what went through tr() without a translation).
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8741) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
// texts that are Swedish already, or data (status names, the INNE / UTE of the board, file names of sounds) or put together from translated parts
const FINE = /^(INNE|UTE|FYS|VAB|Annat|Sjuk|Semester|Tjänsteresa|Jobbar hemifrån|Kommer sent|Går tidigare|Läkarbesök|Föräldraledig|Personlig dag|bubble|pop|tick|Ubuntu .*|\d{4}-\d\d-\d\d .*|window\.LAYOUT.*)$/;
const ENGLISH = /\b(the|and|to|of|is|for|with|or|on|in|an|your|you|are|not|this|that|it|add|edit|delete|settings|colour|status)\b/i;
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('dialog', d => d.dismiss().catch(() => {}));
  const click = async (sel, t) => { try { await page.locator(sel).first().click({ timeout: t || 3000 }); await settle(350); return true; } catch (e) { return false; } };
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1500);
  ok(await page.evaluate(() => document.documentElement.lang === 'sv' && I18N.lang === 'sv'), 'the page is in Swedish');
  const api = await page.evaluate(() => fetch('/api').then(r => r.json()));
  const ppl = api.checkin.groups.flatMap(g => g.people);
  const post = (p, b) => page.evaluate(([p, b]) => fetch(p, { method: 'POST', headers: { 'X-Requested-With': 'x', 'Content-Type': 'application/json' }, body: JSON.stringify(b || {}) }).then(r => r.text()), [p, b]);
  await post('/checkin/status', { id: ppl[1].id, code: 'OTHER', detail: 'Hej' });
  await settle(1500);
  // the board and the status menu
  await page.locator('.rp-r[data-id="' + ppl[2].id + '"] .rp-t').click(); await settle(400);
  ok(/Aktuell status/.test(await page.locator('.rp-sheet').innerText()) && /Rensa status/.test(await page.locator('.rp-sheet').innerText()), 'the status menu is in Swedish');
  await page.locator('.rp-sheet button[data-code="LATE"]').click(); await settle(400);
  ok(/Vilken tid\?/.test(await page.locator('.rp-need2').innerText()) && /Avbryt/.test(await page.locator('.rp-need2').innerText()), 'the time pop-up is in Swedish');
  await page.keyboard.press('Escape'); await page.keyboard.press('Escape'); await settle(300);
  // Settings: every menu and pop-up
  await click('#cog'); await settle(1500);
  ok((await page.locator('#settings h1').textContent()) === 'Inställningar', 'Settings has its title in Swedish');
  const EDIT = '#settings .srow.edit:not(:has-text("Språk")) > button';       // every Edit button (not the language's: that one is tried below)
  const n = await page.locator(EDIT).count();
  for (let i = 0; i < n; i++) { try { const b = page.locator(EDIT).nth(i); if (await b.isVisible()) { await b.click({ timeout: 1500 }); await settle(250); } } catch (e) {} }
  await page.keyboard.press('Escape'); await settle(200);
  for (const box of ['contacts', 'statuses']) { await click('[data-box="' + box + '"] .srow.edit button'); await click('[data-box="' + box + '"] .olist .srow[data-id] >> nth=0'); await page.keyboard.press('Escape'); await page.keyboard.press('Escape'); await settle(200); }
  const miss = (await page.evaluate(() => Object.keys(window.TRMISS || {}))).filter(t => !FINE.test(t) && ENGLISH.test(t) && !/^[A-ZÅÄÖ][a-zåäö]+ [A-ZÅÄÖ][a-zåäö]+$/.test(t));
  ok(miss.length === 0, 'nothing in English is left in Settings' + (miss.length ? ': ' + miss.slice(0, 8).join(' | ') : ''));
  // a choice keeps its value when its label is translated ("off" was once turned into "av", which the server refused)
  ok(await page.evaluate(() => { const o = [{ value: 'off', label: 'Off' }, { value: 'on', label: 'On (always)' }]; trTree(o); return o[0].value === 'off' && o[1].value === 'on' && o[0].label === 'Av'; }), 'translating the options of a choice leaves their values alone');
  if (!(await page.evaluate(() => document.getElementById('settings').classList.contains('open')))) { await click('#cog'); await settle(1500); }
  const scrollSel = page.locator('[data-box="check-in"] .srow:has-text("Rullande text") select');
  await scrollSel.selectOption({ label: 'Av' }); await settle(1500);
  ok((await page.evaluate(() => fetch('/api').then(r => r.json()))).checkin.scroll === 'off', 'Rullande text: Av is saved as off');
  await scrollSel.selectOption({ label: 'På (alltid)' }); await settle(1500);
  ok((await page.evaluate(() => fetch('/api').then(r => r.json()))).checkin.scroll === 'on', 'and På (alltid) as on');
  // the language toggle: English, then Swedish again (the page loads again each time)
  if (!(await page.evaluate(() => document.getElementById('settings').classList.contains('open')))) { await click('#cog'); await settle(1500); }
  await click('[data-box="appearance"] .srow:has-text("Språk") button'); await click('.pop.open button:has-text("English")'); await settle(2500);
  ok(await page.evaluate(() => I18N.lang === 'en' && document.documentElement.lang === 'en'), 'English can be chosen in Settings');
  await click('#cog'); await settle(1500);
  ok((await page.locator('#settings h1').textContent()) === 'Settings', 'and Settings is then in English');
  await click('[data-box="appearance"] .srow:has-text("Language") button'); await click('.pop.open button:has-text("Svenska")'); await settle(2500);
  ok(await page.evaluate(() => I18N.lang === 'sv'), 'Swedish can be chosen again');
  ok(errors.length === 0, 'no JavaScript errors' + (errors.length ? ': ' + errors.slice(0, 3).join(' | ') : ''));
  await browser.close();
  console.log(failed ? 'FAILED' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

// Settings > DC Bridge (run by run.sh against a demo server started with DCBRIDGE=new, where the setup script is a stand-in that takes
// about 3 s): before the install there is an Install button and no save manager, pressing it shows the running setup and its log, and
// afterwards the Uninstall button and the save manager rows appear; Uninstall takes them away again.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8742) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 420, height: 1100 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  page.on('dialog', d => d.accept());
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(1000);
  const vis = async (loc) => (await loc.count()) > 0 && await loc.first().isVisible();
  const dash = page.locator('[data-box="dc bridge"]').first();
  ok(/Not installed/.test(await dash.innerText()), 'the dashboard box says the bridge is not installed');
  await page.click('#cog'); await settle(1200);
  const box = page.locator('#set-boxes [data-box="dc bridge"]');
  ok(await vis(box.locator('button', { hasText: 'Install' })), 'there is an Install button');
  ok(!(await vis(box.locator('button', { hasText: 'Uninstall' }))), 'and no Uninstall button');
  ok(!(await vis(box.locator('.srow', { hasText: 'Save manager' }))), 'and no save manager row');
  await box.locator('button', { hasText: 'Install' }).first().click();
  let running = false;
  for (let i = 0; i < 8 && !running; i++) { await settle(400); running = await page.evaluate(() => !!(S.dcbridge && S.dcbridge.setup && S.dcbridge.setup.running)); }
  ok(running, 'pressing Install shows the running setup');
  ok(await box.locator('button', { hasText: 'Install' }).first().isDisabled(), 'and the button is disabled meanwhile');
  let done = false;
  for (let i = 0; i < 20 && !done; i++) { await settle(500); done = await vis(box.locator('button', { hasText: 'Uninstall' })); }
  ok(done, 'when it has finished there is an Uninstall button');
  ok(await vis(box.locator('.srow', { hasText: 'Save manager' })), 'and the save manager row');
  ok(/Done\./.test(await box.innerText()), 'the setup log is shown');
  const modeRow = box.locator('.srow', { hasText: 'Bridge mode' });
  ok(await vis(modeRow), 'the Bridge mode row shows once it is installed');
  await modeRow.first().locator('button').first().click(); await settle(500);
  await page.locator('button', { hasText: 'W5500 only' }).first().click(); await settle(2500);
  ok(await page.evaluate(() => S.dcbridge && S.dcbridge.mode && S.dcbridge.mode.id === 'w5500'), 'choosing W5500 only reaches the service and the dashboard shows it');
  ok(/set by hand/.test(await page.evaluate(() => S.dcbridge.mode.text)), 'as set by hand');
  await box.locator('button', { hasText: 'Uninstall' }).first().click();
  let gone = false;
  for (let i = 0; i < 20 && !gone; i++) { await settle(500); gone = await vis(box.locator('button', { hasText: 'Install' })) && !(await vis(box.locator('button', { hasText: 'Uninstall' }))); }
  ok(gone, 'Uninstall brings the Install button back');
  ok(!(await vis(box.locator('.srow', { hasText: 'Save manager' }))), 'and takes the save manager row away');
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

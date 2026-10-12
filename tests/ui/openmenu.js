// The openMenu link box (run by run.sh against a demo server started with OPENMENU=1 FAKEPLAYERS=1): the Dreamcast's status, the players who
// can be joined, the card's games with a search box, and Start / Join asking first and queueing the launch.
const { chromium } = require('playwright');
const URL = 'http://127.0.0.1:' + (process.env.PORT || 8740) + '/';
let failed = 0;
const ok = (cond, what) => { console.log((cond ? 'ok   ' : 'FAIL ') + what); if (!cond) failed++; };
const settle = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium', args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 420, height: 1400 } });
  const errors = [];
  const questions = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 150)); });
  page.on('dialog', d => { questions.push(d.message()); d.accept(); });
  await page.goto(URL, { waitUntil: 'networkidle' }); await settle(5500);
  const box = page.locator('.dbox[data-box="openmenu"] .now');
  ok(await box.count() === 1, 'the openMenu link has a box on the main page');
  ok((await box.locator('.nlabel').textContent()).includes('Dreamcast (openMenu)'), 'with its own top line');
  ok((await box.locator('b').first().textContent()).trim() === 'Connected', 'the title says the Dreamcast is connected');
  ok(/72 games on the card/.test(await box.textContent()), 'and the note counts the games');
  // the line under the title is one line, closed or open: it scrolls like the title when it is too long
  const noteLook = async text => page.evaluate(async t => { const real = window.render; window.render = () => {}; S.openmenu = Object.assign({}, S.openmenu, { note: t }); engineUpdate();
    await new Promise(r => setTimeout(r, 300)); const c = document.querySelector('.dbox[data-box="openmenu"] .row.main .carousel'), out = { sc: !!c && c.classList.contains('sc'), anim: c ? getComputedStyle(c.querySelector('.trk')).animationName : '', text: c ? c.innerText : '', open: document.querySelector('.dbox[data-box="openmenu"] .now').classList.contains('open'), w: c ? [c.querySelector('.t').offsetWidth, c.parentNode.clientWidth] : 0 };
    window.render = real; return out; }, text);
  const longNote = await noteLook('No game list yet. It arrives when openMenu connects with DCNow! on, which can take a little while after the modem link is up.');
  ok(longNote.sc && longNote.anim === 'marquee', 'a long note under the title scrolls round like a carousel ' + JSON.stringify(longNote).slice(0, 120));
  const shortNote = await noteLook('72 games on the card');
  ok(!shortNote.sc && shortNote.text.trim() === '72 games on the card', 'and a short one stands still ' + JSON.stringify(shortNote));
  await box.click({ position: { x: 20, y: 10 } }); await settle(700);
  ok(await box.evaluate(e => e.classList.contains('open')), 'tapping opens the box');
  const openNote = await noteLook('A long note that can never fit in the box, open or closed, however wide the phone is');
  ok(openNote.open && openNote.sc, 'and an open box scrolls it the same way ' + JSON.stringify(openNote));
  await settle(5500);       // the page's own refresh puts the real note back
  const games = box.locator('.wlist').nth(0);
  ok(await games.locator('.p').count() === 60, 'the games list stops at 60 rows (' + await games.locator('.p').count() + ')');
  ok(/12 more: use the search/.test(await box.textContent()), 'with a hint to search');
  await box.locator('input[aria-label="Search the card"]').fill('crazy'); await settle(300);
  ok(await games.locator('.p').count() === 1 && /Crazy Taxi/.test(await games.textContent()), 'the search narrows the list');
  await page.evaluate(() => { S.openmenu = Object.assign({}, S.openmenu, { connected: false }); engineUpdate(); });
  ok(await games.locator('button').first().isDisabled(), 'while the Dreamcast is not connected the buttons are off');
  await page.evaluate(() => { S.openmenu = Object.assign({}, S.openmenu, { connected: true }); engineUpdate(); });
  await settle(300);
  ok(await games.locator('button').first().isEnabled(), 'and on again when it is');
  await games.locator('.p', { hasText: 'Crazy Taxi' }).locator('button', { hasText: 'Start' }).click(); await settle(2500);
  ok(questions.length === 1 && /Start Crazy Taxi on the Dreamcast\?/.test(questions[0]), 'Start asks first, naming the game (' + questions.join('|') + ')');
  ok(/Waiting for the Dreamcast to start Crazy Taxi|Starting Crazy Taxi|Sent\./.test(await box.textContent()), 'and the box says the game is on its way');
  // the Online players box gets a Join button for the games the openMenu link announces: on the card AND in the table of games that work online,
  // and only while the Dreamcast is connected
  await page.evaluate(() => reloadData('om_games')); await settle(1500);
  const announced = await page.evaluate(() => launcherGames().map(g => g.name).sort());
  ok(announced.includes('Quake III Arena') && !announced.includes('Crazy Taxi'), 'only the card games that are in the online table are announced (' + announced.length + ': ' + announced.slice(0, 3).join(', ') + ')');
  const pbox = page.locator('.dbox[data-box="players"] .now');
  await pbox.click({ position: { x: 20, y: 10 } }); await settle(700);
  const quakeRows = pbox.locator('.wlist .p', { hasText: 'Quake III Arena' });
  ok(await quakeRows.count() >= 2 && await quakeRows.locator('button.join').count() === await quakeRows.count(), 'the game and the player in it have a Join button (' + await quakeRows.count() + ' rows)');
  ok((await quakeRows.first().locator('button.join').textContent()).trim() === 'Join', 'that says Join');
  const heights = await quakeRows.first().evaluate(r => ({ join: r.querySelector('.join').getBoundingClientRect().height, star: r.querySelector('.ibtn.star').getBoundingClientRect().height, joinLeft: r.querySelector('.join').getBoundingClientRect().right <= r.querySelector('.ibtn.star').getBoundingClientRect().left }));
  ok(Math.abs(heights.join - heights.star) <= 1 && heights.joinLeft, 'as high as the star button, and before it so the stars line up (' + JSON.stringify(heights) + ')');
  ok(await pbox.locator('.wlist .p', { hasText: 'Daytona' }).locator('button.join').count() === 0, 'a game that is not on the card has none');
  ok(await pbox.locator('.wlist .p', { hasText: 'Dead Game' }).locator('button.join').count() === 0, 'and neither has one the table lists as offline');
  const joins = async connected => page.evaluate(c => { S.openmenu = Object.assign({}, S.openmenu, { connected: c }); engineUpdate();       // counted at once: the page's own data refresh must not put the real state back first
    return document.querySelectorAll('.dbox[data-box="players"] button.join').length; }, connected);
  ok(await joins(false) === 0, 'while the Dreamcast is not connected there is no Join button at all');
  ok(await joins(true) >= 2, 'and they are back when it is');
  const matches = await page.evaluate(() => ({ name: (launcherGame({ game: 'title' }, { title: 'Quake III Arena Ver.2' }) || {}).name, none: launcherGame({ game: 'title' }, { title: 'Crazy Taxi' }),
    text: (launcherGame({ game: 'title', text: 'sub' }, { title: 'Friday night', sub: 'Come and play Quake III Arena with us' }) || {}).name, textNone: launcherGame({ game: 'title', text: 'sub' }, { title: 'Movie night', sub: 'Discord' }) }));
  ok(matches.name === 'Quake III Arena' && matches.none === null && matches.text === 'Quake III Arena' && matches.textNone === null, 'a name is matched like the card does, and an event by the game named in its text ' + JSON.stringify(matches));
  questions.length = 0;
  await quakeRows.first().locator('button.join').click(); await settle(2500);
  ok(questions.length === 1 && /Start Quake III Arena on the Dreamcast\?/.test(questions[0]), 'Join asks first (' + questions.join('|') + ')');
  ok(/Waiting for the Dreamcast to start Quake III Arena|Starting Quake III Arena/.test(await page.locator('.dbox[data-box="openmenu"] .now').textContent()), 'and the openMenu box says it is on its way');
  // long names scroll, short ones stand still
  const names = await page.evaluate(async () => { const real = window.render; window.render = () => {};
    S.players = Object.assign({}, S.players, { list: [{ title: 'Eve_with_a_really_long_gamertag_that_never_fits', sub: 'A game with a very long name that does not fit either', tag: 'DCNow!', colour: 'switcher.dcnow', starred: false },
                                                       { title: 'Al', sub: 'Quake', tag: 'DCNET', colour: 'switcher.dcnet', starred: false }] });
    engineUpdate(); await new Promise(r => setTimeout(r, 500));
    const rows = Array.from(document.querySelectorAll('.dbox[data-box="players"] .now .row .wlist .p')).filter(r => /Eve_with|Al\b/.test(r.textContent));
    const out = rows.map(r => ({ name: r.querySelector('.pn > .carousel').classList.contains('sc'), game: r.querySelector('.pg .carousel').classList.contains('sc'),
      anim: getComputedStyle(r.querySelector('.pn > .carousel .trk')).animationName, right: r.querySelector('.ibtn').getBoundingClientRect().right <= r.getBoundingClientRect().right + 1 }));
    window.render = real; return out; });
  ok(names.length === 2 && names[0].name && names[0].game && names[0].anim === 'marquee' && names[0].right, 'a long player name and a long game name scroll round ' + JSON.stringify(names[0]));
  ok(!names[1].name && !names[1].game, 'short ones stand still');
  // the box title with the network counts is as big as the names, bold; the refreshing spinner sits next to the row's title
  const look = await page.evaluate(() => { const q = s => { const e = document.querySelector('.dbox[data-box="players"] ' + s); const c = getComputedStyle(e); return [c.fontSize, c.fontWeight]; };
    return { title: q('.now b'), name: q('.wlist .p .pn'), tag: q('.wlist .p .pw') }; });
  ok(look.title[0] === look.name[0] && Number(look.title[1]) >= 700 && look.tag[0] === look.name[0], 'the network names in the box title are as big as the names, in bold ' + JSON.stringify(look));
  const spin = await page.evaluate(async () => { const real = window.render; window.render = () => {}; S.players = Object.assign({}, S.players, { busy: true }); engineUpdate(); await new Promise(r => setTimeout(r, 200));
    const row = Array.from(document.querySelectorAll('.dbox[data-box="players"] .now .row')).filter(r => r.querySelector('.k') && r.querySelector('.k').textContent.trim() === 'Players')[0];
    const sp = row.querySelector('.k .spin'), k = row.querySelector('.k').getBoundingClientRect(), r2 = sp.getBoundingClientRect(), alt = row.querySelector('.spin.alt');
    const out = { inTitle: !!sp, visible: getComputedStyle(sp).display !== 'none', nextToLabel: r2.left >= k.left && r2.right <= k.right + 1, altHidden: getComputedStyle(alt).display === 'none' };
    S.players = Object.assign({}, S.players, { busy: false }); engineUpdate(); window.render = real; return out; });
  ok(spin.inTitle && spin.visible && spin.nextToLabel && spin.altHidden, 'the refreshing spinner is next to the row title, not at the far right ' + JSON.stringify(spin));
  ok(errors.length === 0, 'no JavaScript or console errors' + (errors.length ? ': ' + errors.join(' | ') : ''));
  await browser.close();
  console.log(failed ? failed + ' check(s) failed' : 'all checks passed');
  process.exit(failed ? 1 : 0);
})();

// Block pop-ups (ROADMAP 9.1): the player is sandboxed, so an embed's window.open / top.location
// do nothing; the switch beside the sources turns it off (saved on the profile). Remote only:
// arrows / OK / Back (inside the fake player, its buttons are pressed with Enter, never clicked).
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

const API = 'http://localhost:8101/api';

// An embed with ads: a button that opens a pop-up, one that sends the whole page elsewhere, and
// the progress events the watch page reads (CineSrc format).
const NOISY_PLAYER = `<!doctype html><html><body style="margin:0;background:#111;color:#eee;font:20px sans-serif">
<button id="ad">Ad</button> <button id="redirect">Redirect</button>
<p id="log"></p>
<script>
  const log = (s) => { document.getElementById('log').textContent += s + ' '; };
  document.getElementById('ad').onclick = () => {
    let w = null;
    try { w = window.open('https://ads.e2e.test/popup', '_blank'); } catch (e) {}
    log(w ? 'opened' : 'blocked');
  };
  document.getElementById('redirect').onclick = () => {
    try { top.location.href = 'https://ads.e2e.test/landing'; log('redirecting'); } catch (e) { log('redirect-blocked'); }
  };
  parent.postMessage({ type: 'cinesrc:timeupdate', currentTime: 42, duration: 6000 }, '*');
</script></body></html>`;

async function heatId(page) {
  const res = await page.request.get(`${API}/titles/`, { params: { q: 'Heat', type: 'movie' } });
  const data = await res.json();
  const list = Array.isArray(data) ? data : data.results;
  return list.find((t) => t.title === 'Heat').id;
}

let session;
let profile;

async function openPlayer(page, profileName = 'Alex') {
  await page.route(/^https:\/\/player\.e2e\.test\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/html', body: NOISY_PLAYER })
  );
  await page.route(/^https:\/\/ads\.e2e\.test\//, (route) =>
    route.fulfill({ status: 200, contentType: 'text/html', body: '<title>Ad landing</title><h1>An ad</h1>' })
  );
  const id = await heatId(page);
  ({ session, profile } = await signInAs(page, profileName, `/watch/${id}`));
  await expect(page.locator('iframe.watchpage__iframe')).toBeVisible();
  return id;
}

const playerFrame = (page) => page.frameLocator('iframe.watchpage__iframe');
const popupSwitch = (page) => page.getByRole('switch', { name: 'Block pop-ups' });

/**
 * The remote hands itself to the player (OK on the player tile = full screen, the keys then go to
 * the player), then presses one of the fake player's buttons with Enter. Outside full screen the
 * app takes the focus back from an embedded player on purpose: the remote never gets stuck in it.
 */
async function pressInPlayer(page, selector) {
  await page.locator('.watchpage__playerWrap').focus();
  await remote(page, 'OK');
  await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(true);
  await playerFrame(page).locator(selector).press('Enter');
}

/** From the sources: the last chip, then Right = the switch */
async function focusSwitch(page) {
  await page.locator('.watchpage__chip').last().focus();
  await remote(page, 'Right');
  await expect.poll(() => focused(page)).toMatch(/^BUTTON Block pop-ups/);
}

test.afterEach(async ({ page }) => {
  if (!session) return;
  const headers = { Authorization: `Bearer ${session.access}` };
  // the profile as the other tests expect it: pop-ups blocked, no watch history from this player
  await page.request.patch(`${API}/users/${session.user.id}/profiles/${profile.id}/`, { data: { block_popups: true }, headers });
  await page.request.delete(`${API}/history/`, { params: { profileId: String(profile.id) }, headers });
  session = null;
});

test('on by default: the player is sandboxed, its pop-up and redirect do nothing, progress still arrives', async ({ page }) => {
  const progress = page.waitForRequest((r) => /\/watch-progress\//.test(r.url()) && r.postDataJSON()?.position === 42);
  await openPlayer(page);
  const frame = page.locator('iframe.watchpage__iframe');
  await expect(popupSwitch(page)).toHaveAttribute('aria-checked', 'true');
  const sandbox = await frame.getAttribute('sandbox');
  expect(sandbox.split(' ').sort()).toEqual(['allow-forms', 'allow-presentation', 'allow-same-origin', 'allow-scripts']);
  expect(await frame.getAttribute('allow')).toContain('fullscreen');
  await progress; // the player's postMessage events still reach the page (sandboxed)

  // the sources: CineSrc plays sandboxed (scout), Noisy doesn't: last, with a note
  await expect(page.locator('.watchpage__chip', { hasText: 'CineSrc' })).toContainText('No pop-ups');
  await expect(page.locator('.watchpage__chip').nth(-2)).toContainText('Noisy Player');
  await expect(page.locator('.watchpage__chip').nth(-2)).toContainText('may open pop-ups');

  let popups = 0;
  page.on('popup', () => (popups += 1));
  await pressInPlayer(page, '#ad');
  await expect(playerFrame(page).locator('#log')).toContainText('blocked');
  await pressInPlayer(page, '#redirect');
  await page.waitForTimeout(1000);
  expect(popups).toBe(0);
  await expect(page).toHaveURL(/\/watch\/\d+/);
});

test('the switch: reached from the sources, OK turns it off, the focus stays, pop-ups go through', async ({ page }) => {
  await openPlayer(page);
  await focusSwitch(page);
  const saved = page.waitForResponse((r) => /\/profiles\/\d+\/$/.test(r.url()) && r.request().method() === 'PATCH');
  await remote(page, 'OK');
  await expect(popupSwitch(page)).toHaveAttribute('aria-checked', 'false');
  expect((await saved).ok()).toBeTruthy();
  const frame = page.locator('iframe.watchpage__iframe');
  await expect(frame).not.toHaveAttribute('sandbox', /.*/); // a new frame, without the sandbox
  await expect(playerFrame(page).locator('#ad')).toBeVisible();
  expect(await focused(page)).toMatch(/^BUTTON Block pop-ups/); // the remote is still on the switch
  // switched off, the sources keep the server's order (Noisy first), no notes
  await expect(page.locator('.watchpage__chip').first()).toContainText('Noisy Player');
  await expect(page.locator('.watchpage__chip', { hasText: 'may open pop-ups' })).toHaveCount(0);

  // saved on the profile: still off after a reload
  const me = await page.request.get(`${API}/users/${session.user.id}/profiles/${profile.id}/`, {
    headers: { Authorization: `Bearer ${session.access}` },
  });
  expect((await me.json()).block_popups).toBe(false);
  await page.reload();
  await page.waitForLoadState('networkidle'); // the app refreshes the profile on start: the page settles first
  await expect(popupSwitch(page)).toHaveAttribute('aria-checked', 'false');
  await expect(page.locator('iframe.watchpage__iframe')).not.toHaveAttribute('sandbox', /.*/);
  await expect(playerFrame(page).locator('#ad')).toBeVisible();

  // the same embed now opens its pop-up and moves the page
  const popup = page.waitForEvent('popup');
  await pressInPlayer(page, '#ad');
  await popup;
  await expect(playerFrame(page).locator('#log')).toContainText('opened');
  await page.bringToFront();
  await pressInPlayer(page, '#redirect');
  await expect(page).toHaveURL(/ads\.e2e\.test\/landing/);
});

test('OK again turns it back on, and Back still leaves the page from the switch', async ({ page }) => {
  await openPlayer(page);
  await focusSwitch(page);
  await remote(page, 'OK');
  await expect(popupSwitch(page)).toHaveAttribute('aria-checked', 'false');
  await remote(page, 'OK');
  await expect(popupSwitch(page)).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('sandbox', /allow-scripts/);
  expect(await focused(page)).toMatch(/^BUTTON Block pop-ups/);
  await remote(page, 'Left'); // back to the sources
  expect(await focused(page)).toMatch(/^BUTTON/);
  expect(await focused(page)).not.toMatch(/Block pop-ups/);
  await focusSwitch(page);
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/movies\/\d+$/);
});

test('a source that may open pop-ups: "Allow pop-ups for this source" once, the setting stays on', async ({ page }) => {
  await openPlayer(page);
  await page.locator('.watchpage__chip', { hasText: 'Noisy Player' }).focus();
  await remote(page, 'OK');
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('src', /\/noisy\/movie\/949/);
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('sandbox', /allow-scripts/);
  const offer = page.locator('.watchpage__popupOffer');
  await expect(offer).toContainText('Noisy Player may not play with pop-ups blocked.');

  await remote(page, 'Down');
  await expect.poll(() => focused(page)).toMatch(/^BUTTON Allow pop-ups for this source/);
  await remote(page, 'OK');
  await expect(offer).toHaveCount(0);
  await expect(page.locator('iframe.watchpage__iframe')).not.toHaveAttribute('sandbox', /.*/);
  await expect(popupSwitch(page)).toHaveAttribute('aria-checked', 'true'); // only this source, this time
  await expect.poll(() => focused(page)).toMatch(/^BUTTON Noisy Player/); // the remote lands on the source

  // another source is sandboxed again
  await page.locator('.watchpage__chip', { hasText: 'CineSrc' }).focus();
  await remote(page, 'OK');
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('sandbox', /allow-scripts/);
});

test('Arabic: the switch at the end of the row (on the left), the thumb in its track, the remote reaches it', async ({ page }) => {
  await openPlayer(page, 'Layla');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  const sw = page.getByRole('switch', { name: 'حظر النوافذ المنبثقة' });
  await expect(sw).toHaveAttribute('aria-checked', 'true');
  await expect(page.locator('.watchpage__chip', { hasText: 'CineSrc' })).toContainText('بلا نوافذ منبثقة');
  const rect = (l) => l.evaluate((el) => el.getBoundingClientRect().toJSON());
  const row = await rect(page.locator('.watchpage__providerRow'));
  const swBox = await rect(sw);
  expect(swBox.right).toBeLessThanOrEqual(row.left); // right to left: the switch after the sources = on their left
  const track = await rect(sw.locator('.ui-switch__track'));
  const thumb = await rect(sw.locator('.ui-switch__thumb'));
  expect(thumb.left).toBeGreaterThanOrEqual(track.left);
  expect(thumb.right).toBeLessThanOrEqual(track.right);
  expect(thumb.left - track.left).toBeLessThan(track.right - thumb.right); // on = toward the end (left)

  await page.locator('.watchpage__chip').last().focus();
  await remote(page, 'Left');
  await expect.poll(() => focused(page)).toMatch(/^BUTTON حظر النوافذ المنبثقة/);
  await remote(page, 'OK');
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  expect(await focused(page)).toMatch(/^BUTTON حظر النوافذ المنبثقة/);
  expect(await focusOverlaps(page, { scope: '.watchpage__sources' })).toEqual([]);
});

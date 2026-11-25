// Next episode by the app, for every source (ROADMAP 9.3): at an episode's end (the player's
// "ended" event, or its last 30 s from the times it sends) a "Next episode in 10" card, Play now /
// Cancel, then S/E+1 on the same source; "Still watching?" after 3 episodes started by
// themselves; the show's end. Driven with the remote only (arrows / OK / Back), never the mouse.
// The page's clock is fast-forwarded through the countdown instead of waiting for it.
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

const API = 'http://localhost:8101/api';
// a player that plays, and says so (like CineSrc): the tests then tell it the episode ended
const PLAYS = `<!doctype html><html><body style="margin:0;background:#111;color:#eee">
<p id="state">playing</p><script>parent.postMessage({ type: 'cinesrc:play' }, '*');</script></body></html>`;

/** Breaking Bad (2 seasons of 3 episodes, e2e_prepare) at S/E, no memory of earlier plays */
async function openEpisode(page, season, episode) {
  await page.clock.install();
  const serve = (route) => route.fulfill({ status: 200, contentType: 'text/html', body: PLAYS });
  await page.route(/^https:\/\/player\.e2e\.test\//, serve);
  await page.route(/^https:\/\/cinesrc\.st\//, serve);
  await page.route(`${API}/playback/**`, (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ json: { title: null, profile: null, failed: [] } })
      : route.fulfill({ json: { ok: true } })
  );
  const { session, profile } = await signInAs(page, 'Alex', '/');
  const res = await page.request.get(`${API}/titles/search/`, {
    params: { q: 'Breaking Bad', limit: '5' },
    headers: { Authorization: `Bearer ${session.access}` },
  });
  const found = await res.json();
  const id = (Array.isArray(found) ? found : found.results).find((t) => t.title === 'Breaking Bad').id;
  await page.goto(`/watch/${id}?season=${season}&episode=${episode}`);
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('src', new RegExp(`/tv/1396/${season}/${episode}`));
  return { id, session, profile };
}

/** The player (whatever source plays) sends `msg` to the page */
async function playerSays(page, msg) {
  await page.clock.fastForward(4_000); // past the first seconds of an episode (no stale "ended")
  await expect.poll(() => page.frames().some((f) => /player\.e2e\.test|cinesrc\.st/.test(f.url()))).toBe(true);
  const frame = page.frames().find((f) => /player\.e2e\.test|cinesrc\.st/.test(f.url()));
  await frame.evaluate((m) => parent.postMessage(m, '*'), msg);
}

/** The countdown, second by second (each tick is a new timer) */
async function countDown(page) {
  for (let i = 0; i < 11; i++) {
    await page.clock.fastForward(1_000);
    await page.waitForTimeout(50);
  }
}

const card = (page) => page.locator('.up-next');

/** Presses `keys` in turn (at most `max` each) until the focus is on `what` */
async function moveTo(page, keys, what, max = 5) {
  for (const key of keys) {
    for (let i = 0; i < max && !(await focused(page)).startsWith(what); i++) await remote(page, key);
    if ((await focused(page)).startsWith(what)) break;
  }
  expect(await focused(page)).toMatch(new RegExp(`^${what}`));
}

test('last 30 s: "Next episode in 10", Back cancels it, then Play now on the same source', async ({ page }) => {
  await openEpisode(page, 1, 2);
  await remote(page, 'Down'); // the remote is on the page
  // the player sends times: 20 s before the end of a 47 min episode
  await playerSays(page, { type: 'cinesrc:timeupdate', currentTime: 2800, duration: 2820 });

  await expect(card(page)).toContainText('Next episode in 10');
  await expect(card(page)).toContainText('S1 · E3 · S1 episode 3');
  await expect.poll(() => focused(page)).toBe('BUTTON Play now'); // the card takes the remote
  expect(await focusOverlaps(page, { scope: '.watchpage__playerWrap' })).toEqual([]);
  await card(page).getByRole('button', { name: 'Play now' }).focus(); // focusOverlaps moved the focus around

  await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Cancel');
  await remote(page, 'Left');
  expect(await focused(page)).toBe('BUTTON Play now');

  // Back = Cancel: the card goes, the episode stays, the remote is on the player
  await remote(page, 'Back');
  await expect(card(page)).toHaveCount(0);
  await expect(page).toHaveURL(/season=1&episode=2/);
  expect(await focused(page)).toMatch(/^DIV Player/);
  // ...and it doesn't come back for this episode (its "ended" after the credits)
  await playerSays(page, { type: 'cinesrc:ended' });
  await page.waitForTimeout(300);
  await expect(card(page)).toHaveCount(0);

  // the header's "Next episode" still works, with the remote: Up from the player, Right to it
  await remote(page, 'Up');
  await moveTo(page, ['Right', 'Left'], 'BUTTON Next episode');
  await remote(page, 'OK');
  await expect(page).toHaveURL(/season=1&episode=3/);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('E2E Player');
});

test('the countdown ends: season end -> next season E1, on the source the viewer chose', async ({ page }) => {
  await openEpisode(page, 1, 3);
  // CineSrc, chosen with the remote: Down from the player to the source chips, Right, OK
  await remote(page, 'Down');
  await moveTo(page, ['Down', 'Left'], 'BUTTON E2E Player');
  await remote(page, 'Right');
  expect(await focused(page)).toMatch(/^BUTTON CineSrc/);
  await remote(page, 'OK');
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('src', /cinesrc\.st\/embed\/tv\/1396\/1\/3/);
  await remote(page, 'Up'); // back on the player
  expect(await focused(page)).toMatch(/^DIV Player/);

  await playerSays(page, { type: 'cinesrc:ended' });
  await expect(card(page)).toContainText('S2 · E1 · S2 episode 1');
  await countDown(page);
  await expect(page).toHaveURL(/season=2&episode=1/);
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('src', /cinesrc\.st\/embed\/tv\/1396\/2\/1/);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('CineSrc');
  await expect(card(page)).toHaveCount(0);
  expect(await focused(page)).toMatch(/^DIV Player/); // never lost
});

test('"Still watching?" after 3 episodes without a key, then the show\'s end', async ({ page }) => {
  await openEpisode(page, 1, 1);
  await remote(page, 'Down');
  // three episodes start by themselves, nobody touches the remote
  for (const [s, e] of [[1, 2], [1, 3], [2, 1]]) {
    await playerSays(page, { type: 'cinesrc:ended' });
    await expect(card(page)).toContainText('Next episode in');
    await countDown(page);
    await expect(page).toHaveURL(new RegExp(`season=${s}&episode=${e}`));
  }
  // the fourth one asks first, and doesn't start by itself
  await playerSays(page, { type: 'cinesrc:ended' });
  await expect(card(page)).toContainText('Still watching?');
  await expect.poll(() => focused(page)).toBe('BUTTON Continue watching');
  await countDown(page);
  await expect(page).toHaveURL(/season=2&episode=1/);
  await remote(page, 'OK');
  await expect(page).toHaveURL(/season=2&episode=2/);
  expect(await focused(page)).toMatch(/^DIV Player/);

  // the key press counted: the next end counts down again
  await playerSays(page, { type: 'cinesrc:ended' });
  await expect(card(page)).toContainText('Next episode in 10');
  await remote(page, 'OK'); // Play now
  await expect(page).toHaveURL(/season=2&episode=3/);

  // the last episode: no next one, "More like this" instead
  await playerSays(page, { type: 'cinesrc:ended' });
  await expect(card(page)).toContainText('That was the last episode of Breaking Bad');
  await expect.poll(() => focused(page)).toMatch(/^BUTTON /);
  expect(await focusOverlaps(page, { scope: '.watchpage__playerWrap' })).toEqual([]);
  await card(page).locator('button').first().focus();
  await remote(page, 'Back'); // closes the card, stays on the episode
  await expect(card(page)).toHaveCount(0);
  await expect(page).toHaveURL(/season=2&episode=3/);
  expect(await focused(page)).toMatch(/^DIV Player/);
  await remote(page, 'Back'); // and Back again leaves for the show
  await expect(page).toHaveURL(/\/tv\/\d+$/);
});

test('"Play next episode automatically" off: the card waits for Play now', async ({ page }) => {
  const { session, profile } = await openEpisode(page, 1, 1);
  const url = `${API}/users/${session.user.id}/profiles/${profile.id}/`;
  const headers = { Authorization: `Bearer ${session.access}` };
  expect((await page.request.patch(url, { data: { autoplay_next: false }, headers })).ok()).toBeTruthy();
  try {
    await page.reload(); // the app reads the profile again
    await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('src', /\/tv\/1396\/1\/1/);
    await expect.poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('activeProfile')).autoplay_next)).toBe(false);
    await page.reload(); // the watch page reads the setting when it opens
    await remote(page, 'Down');
    await playerSays(page, { type: 'cinesrc:ended' });
    await expect(card(page).locator('.up-next__title')).toHaveText('Next episode');
    await countDown(page);
    await expect(page).toHaveURL(/season=1&episode=1/); // nothing started by itself
    await expect.poll(() => focused(page)).toBe('BUTTON Play now');
    await remote(page, 'OK');
    await expect(page).toHaveURL(/season=1&episode=2/);
  } finally {
    await page.request.patch(url, { data: { autoplay_next: true }, headers });
  }
});

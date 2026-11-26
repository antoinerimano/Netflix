// Sources switch by themselves (ROADMAP 9.2): a source that doesn't play -> the next one, with Undo;
// none plays -> one clear screen. Driven with the remote only (arrows / OK / Back).
// The page's clock is fast-forwarded past the 15 s "never loaded" wait instead of waiting for it.
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

const API = 'http://localhost:8101/api';
const PLAYS = `<!doctype html><html><body style="margin:0;background:#111;color:#eee">
<p id="state">playing</p><script>parent.postMessage({ type: 'cinesrc:play' }, '*');</script></body></html>`;

/** A player that plays, or one that never answers (the iframe never loads) */
async function players(page, { e2eplayer, cinesrc }) {
  const serve = (how) => (route) => {
    if (how === 'plays') return route.fulfill({ status: 200, contentType: 'text/html', body: PLAYS });
    return undefined; // never answered: the page stays blank, like a dead embed
  };
  await page.route(/^https:\/\/player\.e2e\.test\//, serve(e2eplayer));
  await page.route(/^https:\/\/cinesrc\.st\//, serve(cinesrc));
}

/** The watch page of a movie, with no memory of earlier plays (other tests report some) */
async function openPlayer(page, name) {
  await page.clock.install();
  await page.route(`${API}/playback/**`, (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ json: { title: null, profile: null, failed: [] } })
      : route.fulfill({ json: { ok: true } })
  );
  const { session } = await signInAs(page, 'Alex', '/');
  const res = await page.request.get(`${API}/titles/search/`, {
    params: { q: name, limit: '5' },
    headers: { Authorization: `Bearer ${session.access}` },
  });
  const found = await res.json();
  const list = Array.isArray(found) ? found : found.results;
  const id = list.find((t) => t.title === name).id;
  await page.goto(`/watch/${id}`);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('E2E Player');
}

/** Presses `key` until the focus is on `what` (at most `max` times) */
async function moveTo(page, key, what, max = 6) {
  for (let i = 0; i < max && !(await focused(page)).includes(what); i++) await remote(page, key);
  expect(await focused(page)).toContain(what);
}

test('a source that never loads: the next one by itself, Undo goes back and stays', async ({ page }) => {
  await players(page, { e2eplayer: 'hangs', cinesrc: 'plays' });
  await openPlayer(page, 'Interstellar');
  await remote(page, 'Down'); // the remote is on the page
  await page.clock.fastForward(16_000);

  await expect(page.locator('.watchpage__softHintText')).toHaveText("E2E Player didn't play, trying CineSrc…");
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('CineSrc');
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('src', /cinesrc\.st\/embed\/movie\/157336/);
  // the source that plays keeps playing (no other switch), and Undo stays a while (10 s)
  await page.clock.fastForward(6_000);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('CineSrc');

  // Undo, with the remote: it's at the top of the player, Up from the player reaches it
  await page.locator('.watchpage__chip').first().focus(); // where a viewer sits: on the sources
  await remote(page, 'Up');
  expect(await focused(page)).toMatch(/^DIV Player/);
  await remote(page, 'Up');
  expect(await focused(page)).toBe('BUTTON Undo');
  expect(await focusOverlaps(page, { scope: '.watchpage__main' })).toEqual([]);
  await page.locator('.watchpage__softHintBtn').focus(); // focusOverlaps moved the focus around
  await remote(page, 'OK');
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('E2E Player');
  await expect(page.getByRole('button', { name: 'Undo' })).toHaveCount(0); // ("Loading source..." may show there)
  expect(await focused(page)).toMatch(/^DIV Player/); // the remote stays on the player, never lost

  // the viewer chose it: it isn't left again by itself, the next one is only offered
  await page.clock.fastForward(16_000);
  await expect(page.locator('.watchpage__softHintText')).toHaveText('Not playing on E2E Player?');
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('E2E Player');
});

test('no source plays: one clear screen, Try again and Choose a source with the remote', async ({ page }) => {
  await players(page, { e2eplayer: 'hangs', cinesrc: 'hangs' });
  await openPlayer(page, 'Interstellar');
  await remote(page, 'Down');
  await page.clock.fastForward(16_000); // E2E Player -> CineSrc
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('CineSrc');
  await page.clock.fastForward(16_000); // CineSrc -> nothing left

  const screen = page.locator('.watchpage__allFailed');
  await expect(screen).toContainText('No source played this');
  await expect.poll(() => focused(page)).toBe('BUTTON Try again'); // the remote is on it

  // Try again: the whole list once more, from the best one
  await remote(page, 'OK');
  await expect(screen).toHaveCount(0);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('E2E Player');
  expect(await focused(page)).toMatch(/^DIV Player/);
  await page.clock.fastForward(16_000);
  await page.clock.fastForward(16_000);
  await expect(screen).toBeVisible();
  await expect.poll(() => focused(page)).toBe('BUTTON Try again');
  expect(await focusOverlaps(page, { scope: '.watchpage__playerWrap' })).toEqual([]);
  await screen.getByRole('button', { name: 'Try again' }).focus(); // focusOverlaps moved the focus around

  // Choose a source: the remote goes to the sources under the player
  await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Choose a source');
  await remote(page, 'OK');
  await expect.poll(() => focused(page)).toMatch(/^BUTTON (E2E Player|CineSrc)/);
  await moveTo(page, 'Left', 'E2E Player');
  await remote(page, 'OK');
  await expect(screen).toHaveCount(0);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('E2E Player');
  expect(await focused(page)).not.toMatch(/^(IFRAME|BODY)/);

  // Back still leaves the player for the title
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/movies\/\d+$/);
});

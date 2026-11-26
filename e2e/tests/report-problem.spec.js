// "Playback problem?" + the status page (ROADMAP 9.8). Driven with the remote only (arrows / OK /
// Back): the report dialog on the watch page (saved with the source + title, then "Try <next>"),
// and /status signed out ("Test from my connection": down for me or everyone?), in Arabic too.
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

const API = 'http://localhost:8101/api';
const PLAYS = `<!doctype html><html><body style="margin:0;background:#111;color:#eee">
<p>playing</p><script>parent.postMessage({ type: 'cinesrc:play' }, '*');</script></body></html>`;

/** Both fake players play; no memory of earlier plays, and this test leaves none (plays, progress)
 * for the specs after it: only the report reaches the server */
async function players(page) {
  const plays = (route) => route.fulfill({ status: 200, contentType: 'text/html', body: PLAYS });
  await page.route(/^https:\/\/player\.e2e\.test\//, plays);
  await page.route(/^https:\/\/cinesrc\.st\//, plays);
  await page.route(/\/api\/playback\/(\?.*)?$/, (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ json: { title: null, profile: null, failed: [] } })
      : route.fulfill({ json: { ok: true } })
  );
  await page.route(/\/api\/watch-progress\//, (route) => route.fulfill({ json: { ok: true } }));
}

/** Presses `key` until the focus is on `what` (at most `max` times) */
async function moveTo(page, key, what, max = 8) {
  for (let i = 0; i < max && !(await focused(page)).includes(what); i++) await remote(page, key);
  expect(await focused(page)).toContain(what);
}

async function movieId(page, session, name) {
  const res = await page.request.get(`${API}/titles/search/`, {
    params: { q: name, limit: '5' },
    headers: { Authorization: `Bearer ${session.access}` },
  });
  const found = await res.json();
  return (Array.isArray(found) ? found : found.results).find((t) => t.title === name).id;
}

test('report a problem with the remote: saved with the source, then the next source', async ({ page }) => {
  await players(page);
  const { session, profile } = await signInAs(page, 'Alex', '/');
  const id = await movieId(page, session, 'Interstellar');
  await page.goto(`/watch/${id}`);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('E2E Player');

  // from the sources, Right reaches "Playback problem?" (at the end of their line)
  await page.locator('.watchpage__chip').first().focus();
  await moveTo(page, 'Right', 'Playback problem?', 4);
  await remote(page, 'OK');
  const dialog = page.getByRole('dialog', { name: 'Playback problem?' });
  await expect(dialog).toContainText("What's wrong on E2E Player?");
  await expect.poll(() => focused(page)).toBe("BUTTON It doesn't play"); // the remote is in the dialog
  expect(await focusOverlaps(page, { scope: '.ui-modal' })).toEqual([]);
  await dialog.getByRole('button', { name: "It doesn't play" }).focus(); // focusOverlaps moved the focus

  // Back closes it, the focus goes back to the button; OK opens it again
  await remote(page, 'Back');
  await expect(dialog).toHaveCount(0);
  expect(await focused(page)).toBe('BUTTON Playback problem?');
  await remote(page, 'OK');
  await expect.poll(() => focused(page)).toBe("BUTTON It doesn't play");

  // Down to "No sound", OK: sent with the source and the title
  await remote(page, 'Down');
  expect(await focused(page)).toBe('BUTTON Wrong film or episode');
  await remote(page, 'Down');
  expect(await focused(page)).toBe('BUTTON No sound');
  const sent = page.waitForResponse((r) => r.url().includes('/api/playback/report/') && r.request().method() === 'POST');
  await remote(page, 'OK');
  const res = await sent;
  expect(res.status()).toBe(201);
  expect(res.request().postDataJSON()).toEqual({
    provider: 'e2eplayer', problem: 'no_sound', title_id: id, profile_id: profile.id,
  });
  await expect(dialog).toContainText("Thanks, it's noted. E2E Player is checked again first tonight.");
  await expect.poll(() => focused(page)).toBe('BUTTON Try CineSrc'); // never lost when the list goes
  await remote(page, 'Right');
  expect(await focused(page)).toBe('A Source status');
  expect(await focusOverlaps(page, { scope: '.ui-modal' })).toEqual([]);
  await dialog.getByRole('button', { name: 'Try CineSrc' }).focus();

  // Try CineSrc: the dialog closes on the next source, the remote is back on the page
  await remote(page, 'OK');
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('CineSrc');
  expect(await focused(page)).not.toMatch(/^(BODY|IFRAME)/);

  // Back still leaves the player for the title
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/movies\/\d+$/);
});

test('status page signed out: down for me or everyone, with the remote', async ({ page }) => {
  // from this browser the E2E Player answers, CineSrc can't be reached (a blocker, a DNS filter...)
  await page.route(/^https:\/\/player\.e2e\.test\//, (route) => route.fulfill({ status: 404, body: '' }));
  await page.route(/^https:\/\/cinesrc\.st\//, (route) => route.abort('namenotresolved'));
  await page.goto('/status');
  await expect(page.getByRole('heading', { name: 'Taurus is up' })).toBeVisible();
  await expect(page.locator('.status-source')).toHaveCount(2);
  await expect(page.locator('.status-source').first()).toContainText('Not checked yet');

  await moveTo(page, 'Down', 'Test from my connection');
  await remote(page, 'OK');
  await expect(page.locator('.status__testResult')).toContainText('not reachable from your connection: 1.');
  const cine = page.locator('.status-source', { hasText: 'CineSrc' });
  await expect(cine).toContainText('Not reachable from your connection');
  await expect(page.locator('.status-source', { hasText: 'E2E Player' })).toContainText('Reachable from your connection');
  expect(await focused(page)).toMatch(/^BUTTON Test again/); // the button stays, with its new name

  // Down goes through the sources (each is a stop: the remote can read them all)
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^LI (E2E Player|CineSrc): Not checked/);
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^LI (E2E Player|CineSrc): Not checked/);
  expect(await focusOverlaps(page, { scope: '.status' })).toEqual([]);
});

test('status page in Arabic: right to left', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('lang', 'ar'));
  await page.goto('/status');
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl');
  await expect(page.getByRole('heading', { name: 'Taurus يعمل' })).toBeVisible();
  // a source's name on the right, its state at the left end of the line
  const row = page.locator('.status-source').first();
  const name = await row.locator('.status-source__name').boundingBox();
  const state = await row.locator('.status-source__state').boundingBox();
  expect(state.x + state.width).toBeLessThan(name.x);
  const rowBox = await row.boundingBox();
  expect(name.x + name.width).toBeGreaterThan(rowBox.x + rowBox.width * 0.7);
  expect(await focusOverlaps(page, { scope: '.status' })).toEqual([]);
});

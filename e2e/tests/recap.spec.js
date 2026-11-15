// "Catch me up" with the TV remote: on a show the profile is part way through (Alex at Breaking
// Bad S2 E2), the button in the hero's action row opens the recap of everything before that
// episode, the focus starts on "Resume S2 E2", Back closes it and gives the focus back to the
// button, Resume opens the player on that episode. The recap was written beforehand
// (e2e_prepare): no AI call. Alex's history is cleared at the end, passed or failed.
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

async function idOf(page, name) {
  const found = await (await page.request.get(`${API}/titles/search/`, { params: { q: name } })).json();
  return (found.results || found).find((t) => t.title === name).id;
}

let cleanup = null;
test.afterEach(async ({ page }) => {
  if (cleanup) await cleanup(page);
  cleanup = null;
});

test('catch me up on a show, then resume it', async ({ page }) => {
  const { session, profile } = await signInAs(page, 'Alex', '/');
  const auth = { headers: { Authorization: `Bearer ${session.access}` } };
  cleanup = (p) => p.request.delete(`${API}/history/`, { ...auth, params: { profileId: String(profile.id) } });
  const show = await idOf(page, 'Breaking Bad');

  // never started: no button
  await page.goto(`/tv/${show}`);
  await expect(page.locator('#detail-title')).toHaveText('Breaking Bad');
  await expect(page.getByRole('button', { name: /^Watch$/ })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Catch me up' })).toHaveCount(0);

  // part way through season 2
  const saved = await page.request.post(`${API}/watch-progress/`, {
    ...auth,
    data: { profile_id: profile.id, title_id: show, season: 2, episode: 2 },
  });
  expect(saved.ok()).toBeTruthy();
  await page.goto(`/tv/${show}`);
  await expect(page.getByRole('button', { name: 'Catch me up' })).toBeVisible();
  expect(await focusOverlaps(page)).toEqual([]); // the new button's focus covers no neighbour

  await page.reload(); // the check moved the focus around: start again like a remote would
  await expect(page.getByRole('button', { name: 'Catch me up' })).toBeVisible();
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Watch/);
  await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Catch me up');
  await remote(page, 'OK');

  const dialog = page.getByRole('dialog', { name: 'Catch me up' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('Everything before season 2, episode 2: no spoilers.');
  await expect(dialog).toContainText('a chemistry teacher starts cooking with a former student');
  await expect(dialog.locator('.recap-dialog__text p')).toHaveCount(3); // two paragraphs + the AI note
  await expect.poll(() => focused(page)).toBe('BUTTON Resume S2 E2');

  // Back closes the dialog, the focus is back on the button
  await remote(page, 'Back');
  await expect(dialog).toHaveCount(0);
  expect(await focused(page)).toBe('BUTTON Catch me up');
  await expect(page).toHaveURL(new RegExp(`/tv/${show}$`));

  // again (already loaded), then Resume: the player on S2 E2
  await remote(page, 'OK');
  await expect(dialog).toContainText('a chemistry teacher');
  await expect.poll(() => focused(page)).toBe('BUTTON Resume S2 E2');
  await remote(page, 'OK');
  await expect(page).toHaveURL(new RegExp(`/watch/${show}\\?season=2&episode=2$`));
});

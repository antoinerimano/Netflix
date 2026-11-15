// Content notes on title pages (roadmap 8.4), with the TV remote: Heat (tagged in e2e_prepare)
// says "Contains: violence and strong language" under its genres, as plain text the remote never
// stops on (Down from the top lands on Watch, Up comes back past it); a title without notes
// (Inception) has no such line; the French profile reads it in French.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

async function idOf(page, name) {
  const found = await (await page.request.get(`${API}/titles/search/`, { params: { q: name } })).json();
  return (found.results || found).find((t) => t.title === name).id;
}

test('content notes under the genres, never in the way of the remote', async ({ page }) => {
  await signInAs(page, 'Alex', '/');
  const heat = await idOf(page, 'Heat');

  await page.goto(`/movies/${heat}`);
  await expect(page.locator('#detail-title')).toHaveText('Heat');
  const notes = page.locator('.detail-hero__notes');
  await expect(notes).toHaveText('Contains: violence and strong language');
  // shown between the genres and the actions
  const genresBox = await page.locator('.detail-hero__genres').boundingBox();
  const notesBox = await notes.boundingBox();
  const actionsBox = await page.locator('.detail-hero__actions').boundingBox();
  expect(notesBox.y).toBeGreaterThan(genresBox.y);
  expect(actionsBox.y).toBeGreaterThan(notesBox.y);

  // the remote goes from the top straight to Watch, and the notes never take the focus
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Watch/);
  await remote(page, 'Right Left');
  expect(await focused(page)).toMatch(/^BUTTON Watch/);
  await remote(page, 'Up');
  expect(await focused(page)).not.toMatch(/Contains/);
  await expect(notes.locator('[tabindex], button, a')).toHaveCount(0);

  // a title without notes: no line at all
  const inception = await idOf(page, 'Inception');
  await page.goto(`/movies/${inception}`);
  await expect(page.locator('#detail-title')).toHaveText('Inception');
  await expect(page.locator('.detail-hero__notes')).toHaveCount(0);
});

test('content notes in the profile language', async ({ page }) => {
  await signInAs(page, 'Camille', '/');
  const heat = await idOf(page, 'Heat');
  await page.goto(`/movies/${heat}`);
  await expect(page.locator('.detail-hero__notes')).toHaveText('Contient : violence et langage grossier');
});

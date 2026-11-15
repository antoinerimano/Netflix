// Free TMDB data (roadmap 8.8), with the TV remote: search finds a title by another name
// ("Der Pate" -> The Godfather, with "Also known as Der Pate"), OK opens it; Heat's "More like this"
// shows TMDB's recommendation (Inception), reached with the remote. Data seeded by e2e_prepare.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

async function idOf(page, name) {
  const found = await (await page.request.get(`${API}/titles/search/`, { params: { q: name } })).json();
  return (found.results || found).find((t) => t.title === name).id;
}

test('search by another name, then open it with the remote', async ({ page }) => {
  await signInAs(page, 'Alex', '/search');
  // the page's big field takes the focus by itself: type straight away, like with a TV keyboard
  await expect.poll(() => focused(page)).toMatch(/^INPUT/);
  await page.keyboard.type('der pate');
  const card = page.locator('.poster-card', { hasText: 'The Godfather' }).first();
  await expect(card).toBeVisible();
  await expect(page.getByText('Also known as Der Pate')).toBeVisible();

  // down to the results, OK opens the title
  for (let i = 0; i < 6 && !/The Godfather/.test(await focused(page)); i += 1) await remote(page, 'Down');
  expect(await focused(page)).toMatch(/The Godfather/);
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/movies\/\d+$/);
  await expect(page.locator('#detail-title')).toHaveText('The Godfather');
});

test("TMDB's recommendation in More like this, reached with the remote", async ({ page }) => {
  await signInAs(page, 'Alex', '/');
  const heat = await idOf(page, 'Heat');
  const inception = await idOf(page, 'Inception');
  await page.goto(`/movies/${heat}`);
  const row = page.locator('.detail-section', { has: page.locator('.detail-similar') });
  await expect(row).toContainText('Inception');

  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Watch/);
  for (let i = 0; i < 6 && !/Inception/.test(await focused(page)); i += 1) await remote(page, 'Down');
  expect(await focused(page)).toMatch(/Inception/);
  await remote(page, 'OK');
  await expect(page).toHaveURL(new RegExp(`/movies/${inception}$`));
});

// Franchises in watch order, with the TV remote: the movie page's "Part of The Godfather
// Collection" (numbered row ending with "Watch order"), the collection page (main button, parts, Back returns to the
// part), and after watching part 1: "1 of 2 watched", "Watch next", "Next movie" in the player
// and the home row "Next in your collections". Profile "Sam"; its history is cleared at the end.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

async function idOf(page, name) {
  const found = await (await page.request.get(`${API}/titles/search/`, { params: { q: name } })).json();
  return (found.results || found).find((t) => t.title === name).id;
}

/** Presses `key` until the focus matches (at most `max` times). */
async function moveUntil(page, key, pattern, max = 8) {
  for (let i = 0; i < max && !pattern.test(await focused(page)); i += 1) await remote(page, key);
  expect(await focused(page)).toMatch(pattern);
}

test('collection: movie page, collection page, what comes next', async ({ page }) => {
  const { session, profile } = await signInAs(page, 'Sam', '/');
  const auth = { headers: { Authorization: `Bearer ${session.access}` } };
  const first = await idOf(page, 'The Godfather');
  const second = await idOf(page, 'The Godfather Part II');

  // the movie page: the numbered row, starting on this movie, ending with "Watch order"
  await page.goto(`/movies/${first}`);
  await expect(page.locator('.coll-section')).toContainText('Part of The Godfather Collection');
  await expect(page.locator('.coll-section')).toContainText('0 of 2 watched');
  await moveUntil(page, 'Down', /^BUTTON Part 1, The Godfather, 1972, This one/);
  await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Part 2, The Godfather Part II, 1974');
  await remote(page, 'Right'); // the row's last tile
  expect(await focused(page)).toBe('BUTTON Watch order');
  await remote(page, 'OK');
  await expect(page).toHaveURL(new RegExp(`/collection/230$`));

  // the collection page: starts on its main button, then the parts
  await expect(page.getByRole('heading', { name: 'The Godfather Collection' })).toBeVisible();
  await remote(page, 'Down');
  expect(await focused(page)).toBe('BUTTON Start with The Godfather');
  await remote(page, 'Down Right');
  expect(await focused(page)).toBe('BUTTON Part 2, The Godfather Part II, 1974');
  await remote(page, 'OK');
  await expect(page).toHaveURL(new RegExp(`/movies/${second}$`));
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/collection\/230$/);
  await expect.poll(() => focused(page)).toBe('BUTTON Part 2, The Godfather Part II, 1974');

  // after part 1: the player offers part 2, the collection says what's next, so does the home
  await page.goto(`/watch/${first}`);
  await expect(page.getByRole('button', { name: 'Next movie' })).toBeVisible();
  await page.goto('/collection/230');
  await expect(page.getByText('1 of 2 watched').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Watch next: The Godfather Part II' })).toBeVisible();
  await page.goto('/');
  const row = page.locator('.row', { hasText: 'Next in your collections' });
  await expect(row).toBeVisible();
  await expect(row).toContainText('The Godfather Part II');

  await page.request.delete(`${API}/history/`, { ...auth, params: { profileId: String(profile.id) } });
});

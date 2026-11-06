// "Your year" (/stats) with the TV remote: Down walks through the recap (the focus is never lost)
// down to "Share my year", Right reaches the card beside; a title opens its page and Back returns. Profile "Kids" watches two titles first; its history is cleared at the end.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

test('walk through the recap with the remote', async ({ page }) => {
  const { session, profile } = await signInAs(page, 'Kids', '/');
  const auth = { headers: { Authorization: `Bearer ${session.access}` } };
  const watch = async (name) => {
    const found = await (await page.request.get(`${API}/titles/search/`, { params: { q: name } })).json();
    const id = (found.results || found).find((t) => t.title === name).id;
    await page.request.post(`${API}/watch-progress/`, { ...auth, data: { profile_id: profile.id, title_id: id } });
  };
  await watch('Toy Story');
  await watch('Spirited Away');

  await page.goto('/stats');
  await expect(page.locator('.stats-hero__value')).toHaveText(/^About \d+ hours$/);
  await expect(page.locator('.stats-tile', { hasText: 'Titles' })).toContainText('2');

  // every section, top to bottom
  const seen = [];
  for (let i = 0; i < 12 && !/Share my year/.test(seen[seen.length - 1] || ''); i += 1) {
    await remote(page, 'Down');
    const f = await focused(page);
    expect(f).not.toBe('BODY');
    if (seen[seen.length - 1] !== f) seen.push(f);
  }
  const walk = seen.join(' | ');
  for (const part of ['Longest streak', 'Time watched by month', 'Favourite genres', 'Share my year']) {
    expect(walk).toContain(part);
  }
  expect(walk).toMatch(/BUTTON (Toy Story|Spirited Away)/); // the most watched row is on the way

  // "First of the year" sits beside "Longest streak": Right reaches it
  await page.locator('.stats-card', { hasText: 'Longest streak' }).focus();
  await remote(page, 'Right');
  expect(await focused(page)).toMatch(/^SECTION First of the year/);
  await page.locator('.stats-share .ui-btn').focus();

  // a title opens its page, Back comes back to it
  await remote(page, 'Up');
  for (let i = 0; i < 3 && !/^BUTTON (Toy Story|Spirited Away)/.test(await focused(page)); i += 1) await remote(page, 'Up');
  const card = await focused(page);
  expect(card).toMatch(/^BUTTON (Toy Story|Spirited Away)/);
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/movies\/\d+$/);
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/stats$/);
  await expect.poll(() => focused(page)).toBe(card);

  await page.request.delete(`${API}/history/`, { ...auth, params: { profileId: String(profile.id) } });
});

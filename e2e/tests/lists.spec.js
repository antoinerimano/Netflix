// Lists with the TV remote: "Add to a list" on a title page (a new list starts with the title),
// the same from a card's options sheet, the list in My List, sharing it (the address shown to
// type on a phone), the shared page for someone signed out, and "Save a copy". Profile "Sam";
// its lists are deleted at the end.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

async function idOf(page, name) {
  const found = await (await page.request.get(`${API}/titles/search/`, { params: { q: name } })).json();
  return (found.results || found).find((t) => t.title === name).id;
}

test('make a list, share it, open it signed out, save a copy', async ({ page, browser }) => {
  const { session, profile } = await signInAs(page, 'Sam', '/');
  const auth = { headers: { Authorization: `Bearer ${session.access}` }, params: { profileId: String(profile.id) } };
  const heat = await idOf(page, 'Heat');

  // a title page: the button beside My List opens the picker on its name field (no list yet)
  await page.goto(`/movies/${heat}`);
  await expect(page.locator('#detail-title')).toHaveText('Heat');
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Watch/);
  await remote(page, 'Right Right');
  expect(await focused(page)).toBe('BUTTON Add to a list');
  await remote(page, 'OK');
  await expect(page.locator('.list-picker')).toBeVisible();
  await expect(page.locator('#list-new-name')).toBeFocused();
  await page.keyboard.type('Heist night'); // the TV's on-screen keyboard
  await remote(page, 'OK');
  await expect(page.getByRole('button', { name: /Heist night/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('Added to Heist night')).toBeVisible();
  await remote(page, 'Back');
  await expect(page.locator('.list-picker')).toHaveCount(0);

  // a card's options sheet (hold OK): the list is there, OK adds the title to it
  await page.goto('/movies');
  const card = page.locator('.poster-card', { hasText: 'Inception' }).first();
  await card.click({ button: 'right' });
  await expect(page.locator('.title-options')).toBeVisible();
  await page.getByRole('button', { name: 'Add to a list' }).focus();
  await remote(page, 'OK');
  await expect(page.locator('.list-picker')).toBeVisible();
  await expect.poll(() => focused(page)).toMatch(/^BUTTON Heist night/); // starts on the first list
  await remote(page, 'OK');
  await expect(page.getByText('Added to Heist night')).toBeVisible();
  await remote(page, 'Back');

  // My List: "Your lists" first, the remote starts on it
  await page.goto('/list');
  await expect(page.locator('.list-card').first()).toBeVisible();
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Heist night2 titles/);
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/lists\/\d+$/);
  await expect(page.locator('.history-row')).toHaveCount(2);

  // share: the switch, then the address in big letters
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Share this list/);
  await remote(page, 'OK');
  const url = page.locator('.list-share__url');
  await expect(url).toHaveText(/\/l\/[a-z0-9]{10}$/);
  const shareId = (await url.textContent()).split('/l/')[1];

  // someone signed out opens the link
  const visitor = await browser.newContext();
  const other = await visitor.newPage();
  await other.goto(`/l/${shareId}`);
  await expect(other.getByRole('heading', { name: 'Heist night' })).toBeVisible();
  await expect(other.getByText('A list by Sam · 2 titles')).toBeVisible();
  await expect(other.locator('.public-item').first()).toBeVisible();
  await other.keyboard.press('ArrowDown');
  await expect(other.getByRole('link', { name: 'Make your own lists' })).toBeFocused();
  await other.keyboard.press('ArrowDown');
  await other.keyboard.press('Enter');
  await expect(other).toHaveURL(/\/movies\/\d+$/);
  await visitor.close();

  // signed in: save a copy, it opens in your lists
  await page.goto(`/l/${shareId}`);
  await expect(page.getByRole('button', { name: 'Save a copy' })).toBeVisible();
  await remote(page, 'Down');
  expect(await focused(page)).toBe('BUTTON Save a copy');
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/lists\/\d+$/);
  await expect(page.locator('.history-row')).toHaveCount(2);

  const lists = await (await page.request.get(`${API}/lists/`, auth)).json();
  for (const l of lists.lists) await page.request.delete(`${API}/lists/${l.id}/`, auth);
});

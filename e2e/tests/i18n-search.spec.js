// Languages and search: a profile's language drives the whole app, catalog included.
const { test, expect, signInAs } = require('../fixtures');

test('a French profile gets the app and the catalog in French', async ({ page }) => {
  await signInAs(page, 'Camille');
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
  await expect(page.getByRole('navigation').getByText('Accueil')).toBeVisible();
  await expect(page).toHaveTitle(/Films et séries/);

  await page.goto('/search?q=Parrain'); // the French name finds it
  const card = page.locator('.poster-card', { hasText: 'Le Parrain' }).first();
  await expect(card).toBeVisible();
  await card.click();
  await expect(page.locator('#detail-title')).toHaveText('Le Parrain');
  await expect(page.getByText("Le patriarche d'une dynastie")).toBeVisible();
  await expect(page.getByRole('button', { name: 'Regarder' })).toBeVisible();
});

test('switching to an English profile switches the app back', async ({ page }) => {
  await signInAs(page, 'Camille', '/profiles');
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');
  await page.getByRole('button', { name: /Alex/ }).click();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
  await expect(page.getByRole('navigation').getByText('Home')).toBeVisible();
});

test('search: by title, typo tolerant, with a reason', async ({ page }) => {
  await signInAs(page, 'Alex', '/search?q=godfather');
  await expect(page.locator('.poster-card', { hasText: 'The Godfather' }).first()).toBeVisible();

  await page.goto('/search?q=interstelar'); // typo
  await expect(page.locator('.poster-card', { hasText: 'Interstellar' }).first()).toBeVisible();

  await page.goto('/search?q=zzzzqqqq');
  await expect(page.getByText('No results for')).toBeVisible();
});

test('browse filters by genre', async ({ page }) => {
  await signInAs(page, 'Alex', '/movies');
  await page.getByRole('button', { name: 'Animation', exact: true }).click();
  await expect(page).toHaveURL(/genre=Animation/);
  await expect(page.locator('.poster-card', { hasText: 'Spirited Away' })).toBeVisible();
  await expect(page.locator('.poster-card', { hasText: 'Heat' })).toHaveCount(0);
});

test('my list: add from the details, find it in My List', async ({ page }) => {
  await signInAs(page, 'Alex', '/search?q=Toy Story');
  await page.locator('.poster-card', { hasText: 'Toy Story' }).first().click();
  await page.getByRole('button', { name: 'Add to My List' }).click();
  await expect(page.getByRole('button', { name: 'In My List' })).toBeVisible();
  await page.goto('/list');
  await expect(page.locator('.poster-card', { hasText: 'Toy Story' })).toBeVisible();
});

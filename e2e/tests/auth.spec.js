// Signing in: the way into the app must always work.
const { test, expect, USER } = require('../fixtures');

test('sign in, choose a profile, land on the home page', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Email').fill(USER.email);
  await page.getByLabel('Password', { exact: true }).fill(USER.password);
  await page.getByRole('button', { name: 'Sign in' }).click();

  // several profiles: "Who's watching?"
  await expect(page.getByRole('heading', { name: "Who's watching?" })).toBeVisible();
  await page.getByRole('button', { name: 'Watch as Alex' }).click();

  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator('.hero__title')).toBeVisible();
  await expect(page.locator('.row').first()).toBeVisible();
});

test('a wrong password says so and stays on the page', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Email').fill(USER.email);
  await page.getByLabel('Password', { exact: true }).fill('not-the-password');
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page.getByRole('alert')).toContainText("don't match");
  await expect(page).toHaveURL(/\/login$/);
});

test('the sign-in page links to sign up', async ({ page }) => {
  await page.goto('/login');
  await page.getByRole('link', { name: 'Create an account' }).click();
  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible();
});

test('signed out pages can change language', async ({ page }) => {
  await page.goto('/login');
  await page.locator('.language-picker__select').selectOption('fr');
  await expect(page.getByRole('heading', { name: 'Bon retour parmi nous' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'fr');

  // other scripts too (Devanagari, Cyrillic)
  await page.locator('.language-picker__select').selectOption('hi');
  await expect(page.getByRole('heading', { name: 'फिर से स्वागत है' })).toBeVisible();
  await page.locator('.language-picker__select').selectOption('ru');
  await expect(page.getByRole('heading', { name: 'С возвращением' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'ru');
});

test('pages need a signed-in user', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login$/);
});

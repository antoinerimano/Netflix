// The app on a TV: everything with arrows / OK / Back, the focus always visible and never lost.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

// many TV browsers lay pages out at 1280 x 720 (720p, or 1080p at 150 %): the tightest TV screen
test.use({ viewport: { width: 1280, height: 720 } });

test('home: banner, rows, back up to the banner, never lost', async ({ page }) => {
  await signInAs(page, 'Alex');
  await expect(page.locator('.row').first()).toBeVisible();

  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Play/); // the page's main action first

  await remote(page, 'Down');
  const firstCard = await focused(page);
  expect(firstCard).toMatch(/^DIV /);
  await expect(page.locator('.row').first().locator('.movie-card:focus')).toHaveCount(1);

  await remote(page, 'Right Right Right Right');
  expect(await focused(page)).not.toBe(firstCard);
  // a card on the right of the screen, under the navbar's search box / profile button
  expect(await page.evaluate(() => document.activeElement.getBoundingClientRect().left)).toBeGreaterThan(800);

  await remote(page, 'Up');
  // the banner above the rows, not the navbar (regression: the fixed navbar always looked closer)
  expect(await focused(page)).toMatch(/^BUTTON (Play|More info|Sound on|Sound off)/);

  await remote(page, 'Up Up Up Down Down Down Right Left');
  expect(await focused(page)).not.toBe('BODY');
});

test('OK opens a title, Back returns to the card it came from', async ({ page }) => {
  await signInAs(page, 'Alex');
  await expect(page.locator('.row').first()).toBeVisible();
  await remote(page, 'Down Down Right');
  const card = await focused(page);

  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/(movies|tv)\/\d+$/);
  await expect(page.locator('#detail-title')).toBeVisible();

  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/$/);
  await expect.poll(() => focused(page)).toBe(card);
});

test('holding OK on a card opens its options, Back closes them', async ({ page }) => {
  await signInAs(page, 'Alex');
  await expect(page.locator('.row').first()).toBeVisible();
  await remote(page, 'Down Down');
  const card = await focused(page);

  await page.keyboard.down('Enter');
  await page.waitForTimeout(800);
  await page.keyboard.up('Enter');
  await expect(page.locator('.title-options')).toBeVisible();
  expect(await focused(page)).toMatch(/Play|Resume/); // held OK must not have pressed Play
  await expect(page).toHaveURL(/\/$/);

  await remote(page, 'Back');
  await expect(page.locator('.title-options')).toHaveCount(0);
  expect(await focused(page)).toBe(card);
});

test('the profile menu keeps the remote inside, Back closes it', async ({ page }) => {
  await signInAs(page, 'Alex');
  await page.locator('.profile-icon').focus();
  await remote(page, 'OK');
  await expect(page.locator('.profile-dropdown')).toBeVisible();
  await remote(page, 'Down Down Down Down Down Down Down Down Left Right');
  expect(await page.evaluate(() => !!document.activeElement.closest('.profile-container'))).toBe(true);
  await remote(page, 'Back');
  await expect(page.locator('.profile-dropdown')).toHaveCount(0);
  expect(await focused(page)).toMatch(/Profiles and account/);
});

test('arrows never change the language picker by themselves', async ({ page }) => {
  await signInAs(page, 'Alex');
  const picker = page.locator('.language-picker__select');
  await picker.focus();
  await remote(page, 'Down Down Down');
  await expect(picker).toHaveValue('en');
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});

test('browse page: grid, sticky filter bar, filters dialog', async ({ page }) => {
  await signInAs(page, 'Alex', '/movies');
  await expect(page.locator('.poster-card').first()).toBeVisible();
  await remote(page, 'Down Down Down Up Up Up');
  // up from the grid: the filter bar, then the page's own search box (not a card scrolled away)
  expect(await focused(page)).toMatch(/^(INPUT|BUTTON) /);
  await page.getByRole('button', { name: 'Filters' }).focus();
  await remote(page, 'OK');
  await expect(page.locator('.ui-modal')).toBeVisible();
  await remote(page, 'Down Down Down Down Down Down');
  expect(await page.evaluate(() => !!document.activeElement.closest('.ui-modal'))).toBe(true);
  await remote(page, 'Back');
  await expect(page.locator('.ui-modal')).toHaveCount(0);
  expect(await focused(page)).toMatch(/Filters/);
});

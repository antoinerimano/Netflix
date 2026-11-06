// "What do you like to watch?" (/taste) with the TV remote only: reached from the home banner,
// Back leaves without saving, posters picked with OK, Continue reached with Down (never hidden
// under the pinned bar), then a home page without the banner. Profile "Sam" starts with no likes.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

test.use({ viewport: { width: 1280, height: 720 } }); // the tightest TV screen

test('home banner opens the picker, Back returns without saving', async ({ page }) => {
  await signInAs(page, 'Sam');
  await expect(page.locator('.taste-banner')).toBeVisible();

  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Play/); // the page's main action first
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^A Pick titles/); // right under it, not skipped
  await remote(page, 'Right');
  expect(await focused(page)).toMatch(/^BUTTON Not now/);
  await remote(page, 'Down');
  await expect(page.locator('.row').first().locator('.movie-card:focus')).toHaveCount(1);
  await remote(page, 'Up');
  // back on the banner (between the hero and the rows), on the button it left from
  expect(await focused(page)).toMatch(/^BUTTON Not now/);
  await remote(page, 'Left');
  expect(await focused(page)).toMatch(/^A Pick titles/);

  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/taste$/);
  await expect(page.locator('.taste-card').first()).toBeVisible();

  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator('.taste-banner')).toBeVisible(); // nothing was saved
});

test('pick with OK, Continue with Down, then a personal home page', async ({ page }) => {
  await signInAs(page, 'Sam', '/taste');
  const cards = page.locator('.taste-card');
  await expect(cards.first()).toBeVisible();

  await remote(page, 'Down');
  await expect(cards.first()).toBeFocused(); // starts on the first poster
  await remote(page, 'OK Right OK Right OK');
  await expect(page.locator('.taste-card[aria-pressed="true"]')).toHaveCount(3);

  // down to the pinned bar: every poster on the way stays clear of it, and the bar is entered
  // on Continue (not Skip, which is closer on screen)
  const barTop = await page.locator('.taste__bar').evaluate((el) => el.getBoundingClientRect().top);
  let inBar = false;
  for (let i = 0; i < 8 && !inBar; i += 1) {
    await remote(page, 'Down');
    const box = await page.evaluate(() => {
      const r = document.activeElement.getBoundingClientRect();
      return { bottom: r.bottom, inBar: !!document.activeElement.closest('.taste__bar') };
    });
    inBar = box.inBar;
    if (!inBar) expect(box.bottom).toBeLessThanOrEqual(barTop);
  }
  expect(await focused(page)).toMatch(/^BUTTON Continue/);
  // Up returns to the poster it came from, Down to Continue again
  await remote(page, 'Up');
  await expect(page.locator('.taste-card:focus')).toHaveCount(1);
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Continue/);

  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/$/, { timeout: 30_000 }); // the home page is rebuilt first
  await expect(page.locator('.row').first()).toBeVisible();
  await expect(page.locator('.taste-banner')).toHaveCount(0);
});

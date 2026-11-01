// Watching: details -> player -> external player, and the remote always comes back.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

async function openTitle(page, name) {
  const { session } = await signInAs(page, 'Alex', '/search?q=' + encodeURIComponent(name));
  await page.locator('.poster-card', { hasText: name }).first().click();
  await expect(page.locator('#detail-title')).toHaveText(name);
  return session;
}

test('movie: details, Watch, the player loads the first source', async ({ page }) => {
  await openTitle(page, 'Inception');
  await expect(page.getByText('Science Fiction').first()).toBeVisible();
  await page.getByRole('button', { name: 'Watch' }).click();
  await expect(page).toHaveURL(/\/watch\/\d+/);
  const frame = page.locator('iframe.watchpage__iframe');
  await expect(frame).toHaveAttribute('src', /player\.e2e\.test\/movie\/27205/);
  await expect(page.locator('.watchpage__chip.is-selected')).toContainText('E2E Player');
});

test('show: seasons and episodes, an episode opens the player on it', async ({ page }) => {
  await openTitle(page, 'Breaking Bad');
  await expect(page.getByRole('button', { name: 'Season 2' })).toBeVisible();
  await page.getByRole('button', { name: 'Season 2' }).click();
  await page.locator('.tvd-ep-card').first().click();
  await expect(page).toHaveURL(/season=2&episode=1/);
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('src', /\/tv\/1396\/2\/1/);
});

test('switching source changes the player', async ({ page }) => {
  await openTitle(page, 'Heat');
  await page.getByRole('button', { name: 'Watch' }).click();
  await page.locator('.watchpage__chip', { hasText: 'CineSrc' }).click();
  await expect(page.locator('iframe.watchpage__iframe')).toHaveAttribute('src', /cinesrc\.st\/embed\/movie\/949/);
});

test('OK on the player never traps the remote in it', async ({ page }) => {
  await openTitle(page, 'Heat');
  await page.getByRole('button', { name: 'Watch' }).click();
  await expect(page.locator('iframe.watchpage__iframe')).toBeVisible();
  await page.locator('.watchpage__playerWrap').focus();
  await remote(page, 'OK');
  await page.waitForTimeout(800);

  const fullscreen = await page.evaluate(() => !!document.fullscreenElement);
  if (fullscreen) {
    // the player has the remote. Back / Escape leave full screen in the browser itself (a key sent
    // by the test doesn't trigger that browser shortcut, so leave it the way the browser does):
    // the app must then take the remote back
    await page.evaluate(() => document.exitFullscreen());
    await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBe(false);
  } else {
    await expect(page.locator('.watchpage__softHintText')).toContainText("Full screen isn't available");
  }
  await expect.poll(() => focused(page)).not.toMatch(/^(IFRAME|BODY)/);
  await remote(page, 'Down');
  expect(await focused(page)).not.toMatch(/^(IFRAME|BODY)/);
});

test('CineSrc: the remote drives the player, the focus stays in the app', async ({ page }) => {
  await openTitle(page, 'Heat');
  await page.getByRole('button', { name: 'Watch' }).click();
  await page.locator('.watchpage__chip', { hasText: 'CineSrc' }).click();
  const player = page.frameLocator('iframe.watchpage__iframe');
  await expect(player.locator('#state')).toBeVisible();

  await page.locator('.watchpage__playerWrap').focus();
  await page.keyboard.press('Space'); // play / pause on a remote / keyboard
  await expect(player.locator('#state')).toContainText('play');
  await page.keyboard.press('Space');
  await expect(player.locator('#state')).toContainText('pause');
  expect(await focused(page)).toMatch(/^DIV Player/);
});

test('Back on the player returns to the title', async ({ page }) => {
  await openTitle(page, 'Heat');
  await page.getByRole('button', { name: 'Watch' }).click();
  await expect(page).toHaveURL(/\/watch\//);
  await page.locator('.watchpage__chip').first().focus();
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/movies\/\d+$/);
});

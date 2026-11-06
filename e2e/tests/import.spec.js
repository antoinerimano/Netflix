// "Import your history" (/import) with the TV remote: the sources are reachable and selectable,
// Down reaches the source's action, and after an import the remote lands on "Go to your home
// page". Files can't be picked with a remote: the upload itself is done like a phone would.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

test.use({ viewport: { width: 1280, height: 720 } });

const LETTERBOXD = [
  'Date,Name,Year,Letterboxd URI,Rating',
  '2024-01-02,Toy Story,1995,https://boxd.it/1,4.5', // 9/10: liked
  '2024-01-03,Spirited Away,2001,https://boxd.it/2,3', // 6/10: watched
  '2024-01-04,Not A Real Film,1999,https://boxd.it/3,4', // not in the catalog
].join('\n');

test('import with the remote: sources, upload, summary, then home', async ({ page }) => {
  await signInAs(page, 'Kids', '/import');
  const sources = page.locator('.import-source');
  await expect(sources).toHaveCount(2); // Letterboxd, IMDb

  await remote(page, 'Down');
  await expect(sources.nth(0)).toBeFocused(); // starts on the selected source
  await remote(page, 'Right OK');
  await expect(sources.nth(1)).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('On imdb.com, open Your ratings')).toBeVisible();
  await remote(page, 'Left OK');
  await expect(sources.nth(0)).toHaveAttribute('aria-pressed', 'true');

  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Choose files/);

  // the phone / computer part: choosing the file
  await page.locator('.import-panel input[type="file"]').setInputFiles({
    name: 'ratings.csv', mimeType: 'text/csv', buffer: Buffer.from(LETTERBOXD),
  });
  await expect(page.locator('.import-result')).toBeVisible({ timeout: 30_000 });
  expect(await focused(page)).toMatch(/^BUTTON Go to your home page/); // the remote lands on the next step
  await expect(page.locator('.import-stat--liked dd')).toHaveText('1');
  await expect(page.locator('.import-stat--watched dd')).toHaveText('2');
  await expect(page.locator('.import-stat--notFound dd')).toHaveText('1');

  await remote(page, 'Right OK');
  await expect(page.locator('.import-result__missing')).toContainText('Not A Real Film (1999)');
  await remote(page, 'Left OK');
  await expect(page).toHaveURL(/\/$/);
  await expect(page.locator('.row').first()).toBeVisible();
});

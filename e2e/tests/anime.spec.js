// Anime and K-dramas (ROADMAP 9.5), with the TV remote only: arrows / OK / Back. e2e_prepare.py
// seeds Spirited Away (a film), Frieren, Chainsaw Man (adults only) and the K-drama Crash Landing
// on You; Mika played an anime and listed another (the "Popular anime" home row).
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

test.use({ viewport: { width: 1280, height: 720 } }); // the tightest TV screen

/** Presses `key` until the focus is on `label` (at most `max` presses). */
async function pressUntil(page, key, label, max = 14) {
  for (let i = 0; i < max; i += 1) {
    if ((await focused(page)) === label) return;
    await remote(page, key);
  }
  throw new Error(`the remote never reached ${label} (focus: ${await focused(page)})`);
}

/** Down until the focus is in `selector`. */
async function downTo(page, selector, max = 14) {
  for (let i = 0; i < max; i += 1) {
    if (await page.evaluate((s) => !!document.activeElement?.closest(s), selector)) return;
    await remote(page, 'Down');
  }
  throw new Error(`the remote never reached ${selector} (focus: ${await focused(page)})`);
}

const titles = (page) => page.locator('.poster-card').allInnerTexts();

test('the Anime nav entry and the TV page chips, then Back', async ({ page }) => {
  await signInAs(page, 'Alex', '/tv');
  await expect(page.locator('.poster-card').first()).toBeVisible();

  // up into the bar (its search box first), then left: "Anime" sits after "TV Shows"
  await pressUntil(page, 'Up', 'INPUT Search movies and TV shows');
  await pressUntil(page, 'Left', 'LI Anime');
  expect(await focusOverlaps(page, { scope: '.navbar' })).toEqual([]);
  await page.locator('.nav-links li', { hasText: 'Anime' }).focus(); // focusOverlaps moved the focus
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/anime$/);
  await expect(page.locator('.browse__title')).toHaveText('Anime');
  await expect(page.locator('.nav-links li[aria-current="page"]')).toHaveText('Anime');
  // movies and shows; the genre every anime has isn't a chip
  await expect(page.locator('.poster-card')).toHaveCount(3);
  expect((await titles(page)).join(' ')).toMatch(/Spirited Away[\s\S]*Frieren[\s\S]*Chainsaw Man/);
  await expect(page.locator('.browse__genres .ui-chip', { hasText: /^Animation$/ })).toHaveCount(0);

  // the TV Shows page: its genre bar opens Anime / K-dramas
  await page.goto('/tv');
  await expect(page.locator('.poster-card').first()).toBeVisible();
  await pressUntil(page, 'Up', 'BUTTON All'); // the first key lands on the grid, Up on the genre bar
  await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Anime');
  await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON K-dramas');
  expect(await focusOverlaps(page, { scope: '.browse__bar' })).toEqual([]);
  await page.locator('.browse__section-link', { hasText: 'K-dramas' }).focus();
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/kdrama$/);
  await expect(page.locator('.browse__title')).toHaveText('K-dramas');
  await expect(page.locator('.poster-card')).toHaveCount(1);
  await expect(page.locator('.poster-card').first()).toContainText('Crash Landing on You');

  // OK on the show, Back to the K-dramas, Back to the TV page on the chip it came from
  await downTo(page, '.poster-card');
  await remote(page, 'OK');
  await expect(page.locator('#detail-title')).toHaveText('Crash Landing on You');
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/kdrama$/);
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/tv$/);
  await expect.poll(() => focused(page)).toBe('BUTTON K-dramas');
});

test('a Kids profile sees the kids anime only', async ({ page }) => {
  await signInAs(page, 'Kids', '/anime');
  await expect(page.locator('.poster-card').first()).toBeVisible();
  const shown = (await titles(page)).join(' ');
  expect(shown).toContain('Frieren');
  expect(shown).not.toContain('Chainsaw Man');
});

test('home: "Popular anime" for a profile that watches anime, OK and Back', async ({ page }) => {
  const home = page.waitForResponse((r) => r.url().includes('/api/reco/home/'));
  await signInAs(page, 'Mika');
  const rows = (await (await home).json()).rows.map((r) => r.row_type);
  expect(rows).toContain('anime');
  expect(rows).not.toContain('kdrama');
  const row = page.locator('section[aria-label="Popular anime"]');
  await expect(row).toBeVisible();
  // the one it played isn't offered again; the one it listed is
  await expect(row).not.toContainText('Spirited Away');

  await downTo(page, 'section[aria-label="Popular anime"]');
  const card = await focused(page);
  expect(card).toMatch(/^DIV .*(Frieren|Chainsaw Man)/);
  expect(await focusOverlaps(page, { scope: 'section[aria-label="Popular anime"]' })).toEqual([]);
  await row.locator('.movie-card').first().focus();
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/tv\/\d+$/);
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/$/);
  await expect.poll(() => focused(page)).toBe(card);
});

const MAL = `<?xml version="1.0" encoding="UTF-8" ?>
<myanimelist>
  <anime><series_title><![CDATA[Frieren]]></series_title><series_type>TV</series_type>
    <my_score>9</my_score><my_status>Completed</my_status></anime>
  <anime><series_title><![CDATA[Not A Real Anime]]></series_title><series_type>TV</series_type>
    <my_score>0</my_score><my_status>Watching</my_status></anime>
</myanimelist>`;

test('import: AniList by user name and a MyAnimeList file, with the remote', async ({ page }) => {
  await signInAs(page, 'Kids', '/import');
  const sources = page.locator('.import-source');
  await expect(sources).toHaveCount(4); // Letterboxd, IMDb, MyAnimeList, AniList

  await remote(page, 'Down');
  await expect(sources.nth(0)).toBeFocused();
  await pressUntil(page, 'Right', 'BUTTON AniListYour public list, by user name');
  await remote(page, 'OK');
  await expect(sources.nth(3)).toHaveAttribute('aria-pressed', 'true');
  expect(await focusOverlaps(page, { scope: '.import' })).toEqual([]);
  await sources.nth(3).focus();

  // Down to the user name field: typed with the TV's keyboard, OK sends it
  await remote(page, 'Down');
  await expect(page.getByRole('textbox', { name: 'AniList user name' })).toBeFocused();
  await page.keyboard.type('not a name!');
  await remote(page, 'OK');
  await expect(page.locator('.import-error')).toHaveText('Type your AniList user name (letters, digits, _ or -).');
  expect(await focused(page)).not.toBe('BODY');
  await remote(page, 'Back'); // leaves the field: the arrows go on from it
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Import my list/);

  // MyAnimeList: its export file (the phone / computer part, like the Letterboxd test)
  await remote(page, 'Up Up');
  await pressUntil(page, 'Left', 'BUTTON MyAnimeListAnime list export (.xml.gz)');
  await remote(page, 'OK');
  await expect(sources.nth(2)).toHaveAttribute('aria-pressed', 'true');
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Choose files/);
  await page.locator('.import-panel input[type="file"]').setInputFiles({
    name: 'animelist_1_-_1.xml', mimeType: 'text/xml', buffer: Buffer.from(MAL),
  });
  await expect(page.locator('.import-result')).toBeVisible({ timeout: 30_000 });
  expect(await focused(page)).toMatch(/^BUTTON Go to your home page/);
  await expect(page.locator('.import-stat--liked dd')).toHaveText('1');
  await expect(page.locator('.import-stat--notFound dd')).toHaveText('1');
});

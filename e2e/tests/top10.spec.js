// Top 10 rows and browsing by streaming service (ROADMAP 9.4), with the TV remote only: arrows /
// OK / Back. e2e_prepare.py seeds TMDB's charts (Inception first today, Night Shift this week) and
// the US services (the browser's region): every title on Netflix, Heat / Parasite / Breaking Bad
// on Prime Video.
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

test.use({ viewport: { width: 1280, height: 720 } }); // the tightest TV screen

/** Down until the focus is in `selector` (at most `max` presses). */
async function downTo(page, selector, max = 12) {
  for (let i = 0; i < max; i += 1) {
    if (await page.evaluate((s) => !!document.activeElement?.closest(s), selector)) return;
    await remote(page, 'Down');
  }
  throw new Error(`the remote never reached ${selector} (focus: ${await focused(page)})`);
}

test('home: Top 10 rows, numbered, OK opens the title, Back comes back to it', async ({ page }) => {
  const home = page.waitForResponse((r) => r.url().includes('/api/reco/home/'));
  await signInAs(page, 'Alex');
  const top = page.locator('.row--top10').first();
  await expect(top).toBeVisible();
  await expect(top.locator('.row__title')).toHaveText('Top 10 movies today');
  await expect(page.locator('.row--top10 .row__title').nth(1)).toHaveText('Top 10 shows this week');
  await expect(top.locator('.row-top10__rank').first()).toHaveText('1');
  // the services in the visitor's country (the browser's en-US): a row for the one with enough
  // titles (on this tiny catalog the page's one-title-once rule empties it, so read the answer)
  const res = await home;
  expect(new URL(res.url()).searchParams.get('region')).toBe('US');
  const rows = (await res.json()).rows.map((r) => [r.row_type, r.title]);
  expect(rows).toContainEqual(['service:netflix', 'On Netflix']);
  expect(rows.map((r) => r[0])).not.toContain('service:prime'); // 3 titles: too few for a row

  await downTo(page, '.row--top10');
  expect(await focused(page)).toBe('DIV No. 1: Inception');
  await remote(page, 'Right');
  expect(await focused(page)).toBe('DIV No. 2: Parasite');

  // the focus ring never covers the big numbers' neighbours or another card
  expect(await focusOverlaps(page, { scope: '.row--top10' })).toEqual([]);
  await top.locator('.movie-card').nth(1).focus(); // focusOverlaps moved the focus: back where it was

  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/movies\/\d+$/);
  await expect(page.locator('#detail-title')).toHaveText('Parasite');
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/$/);
  await expect.poll(() => focused(page)).toBe('DIV No. 2: Parasite');

  // on to the shows' chart and back up: never lost
  await downTo(page, 'section[aria-label="Top 10 shows this week"]');
  await remote(page, 'Up Up Down Right Left');
  expect(await focused(page)).not.toBe('BODY');
});

test('browse: filter by streaming service with the remote, then Back', async ({ page }) => {
  await signInAs(page, 'Alex', '/movies');
  await expect(page.locator('.poster-card').first()).toBeVisible();
  const all = await page.locator('.poster-card').count();

  await page.getByRole('button', { name: 'Filters' }).focus();
  await remote(page, 'OK');
  const sheet = page.locator('.ui-modal');
  await expect(sheet.getByText('Streaming service')).toBeVisible();
  // the sheet opens on the selected chip: the service's "Any"; Right goes through the services
  expect(await focused(page)).toBe('BUTTON Any');
  await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Netflix');
  await remote(page, 'Right OK');
  expect(await focused(page)).toBe('BUTTON Prime Video');
  await expect(sheet.locator('.ui-chip.is-selected', { hasText: 'Prime Video' })).toHaveCount(1);
  expect(await focusOverlaps(page, { scope: '.ui-modal' })).toEqual([]);
  await sheet.getByRole('button', { name: 'Prime Video' }).focus(); // back where the remote was

  // down to the sheet's buttons (Reset, Show results), then right
  for (let i = 0; i < 12 && !/Reset|Show results/.test(await focused(page)); i += 1) await remote(page, 'Down');
  if (!/Show results/.test(await focused(page))) await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Show results');
  await remote(page, 'OK');
  await expect(sheet).toHaveCount(0);

  await expect(page).toHaveURL(/service=prime/);
  await expect(page.locator('.browse__pill', { hasText: 'On Prime Video' })).toBeVisible();
  await expect(page.locator('.poster-card')).toHaveCount(2);
  await expect(page.locator('.poster-card', { hasText: 'Heat' })).toHaveCount(1);
  await expect(page.locator('.poster-card', { hasText: 'Parasite' })).toHaveCount(1);
  expect(await focused(page)).not.toBe('BODY');

  // Back from a title keeps the filter
  await downTo(page, '.poster-card');
  await remote(page, 'OK');
  await expect(page.locator('#detail-title')).toBeVisible();
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/movies\?service=prime$/);
  await expect(page.locator('.poster-card')).toHaveCount(2);
  expect(all).toBeGreaterThan(2);
});

test('browse: "Recently added" sort, newest in the catalog first', async ({ page }) => {
  await signInAs(page, 'Alex', '/movies?sort=added');
  await expect(page.locator('.browse__sort select')).toHaveValue('added');
  await expect(page.locator('.browse__sort select option:checked')).toHaveText('Recently added');
  // e2e_prepare adds The Godfather Part II last, Parasite just before it
  await expect(page.locator('.poster-card').first()).toContainText('The Godfather Part II');
  await expect(page.locator('.poster-card').nth(1)).toContainText('Parasite');
});

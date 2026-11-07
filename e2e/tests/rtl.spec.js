// Right-to-left languages (Arabic, Urdu): profile "Layla" is in Arabic. The page is mirrored
// (dir="rtl", the logo and the first link on the right), the rows start at the right edge and the
// remote follows what is on screen: Left goes further into a row, Right comes back. Nothing
// spills sideways and the focus look still keeps clear of its neighbours.
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

test.use({ viewport: { width: 1920, height: 1080 } });

const box = (locator) => locator.evaluate((el) => {
  const r = el.getBoundingClientRect();
  return { left: Math.round(r.left), right: Math.round(r.right) };
});

test('an Arabic profile gets the app right to left', async ({ page }) => {
  await signInAs(page, 'Layla');
  const html = page.locator('html');
  await expect(html).toHaveAttribute('lang', 'ar');
  await expect(html).toHaveAttribute('dir', 'rtl');
  await expect(page).toHaveTitle(/شاهد الأفلام/);

  // the navbar reads from the right: Home, then Movies to its left
  const nav = page.getByRole('navigation');
  const home = await box(nav.getByText('الرئيسية', { exact: true }).first());
  const movies = await box(nav.getByText('أفلام', { exact: true }).first());
  expect(home.left).toBeGreaterThan(movies.left);

  // a row starts at the right edge
  const row = page.locator('.row').filter({ has: page.locator('.slick-slide[data-index="3"]') }).first();
  await row.scrollIntoViewIfNeeded();
  const first = row.locator('.slick-slide[data-index="0"] .movie-card');
  const second = row.locator('.slick-slide[data-index="1"] .movie-card');
  const a = await box(first);
  const b = await box(second);
  expect(a.left).toBeGreaterThan(b.left);
  expect(a.right).toBeGreaterThan(1920 / 2);

  // nothing sideways
  const widths = await page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]);
  expect(widths[0]).toBeLessThanOrEqual(widths[1]);
});

test('the remote moves through a mirrored row: Left goes further, Right comes back', async ({ page }) => {
  await signInAs(page, 'Layla');
  const row = page.locator('.row').filter({ has: page.locator('.slick-slide[data-index="8"]') }).first();
  await row.scrollIntoViewIfNeeded();
  const card = (i) => row.locator(`.slick-slide[data-index="${i}"] .movie-card`);
  const name = async (i) => `DIV ${await card(i).getAttribute('aria-label')}`.trim().slice(0, 64);

  await page.keyboard.press('Shift'); // keyboard mode, like a remote
  await card(0).focus();
  await remote(page, 'Left');
  expect(await focused(page)).toBe((await name(1)).slice(0, 64));

  // far into the row: the slider follows, the focused card stays fully on screen
  await remote(page, 'Left Left Left Left Left Left');
  await page.waitForTimeout(500);
  expect(await focused(page)).toBe((await name(7)).slice(0, 64));
  const seventh = await box(card(7));
  expect(seventh.left).toBeGreaterThanOrEqual(0);
  expect(seventh.right).toBeLessThanOrEqual(1920);

  await remote(page, 'Right');
  expect(await focused(page)).toBe((await name(6)).slice(0, 64));
  for (let i = 0; i < 6; i += 1) await remote(page, 'Right');
  await page.waitForTimeout(500);
  expect(await focused(page)).toBe((await name(0)).slice(0, 64));
  const back = await box(card(0));
  expect(back.right).toBeLessThanOrEqual(1920);
  expect(back.right).toBeGreaterThan(1920 / 2);
});

test('the focus look keeps clear of its neighbours right to left too', async ({ page }) => {
  test.setTimeout(180_000);
  await signInAs(page, 'Layla');
  const found = {};
  for (const path of ['/', '/movies', '/pick', '/list', '/account']) {
    if (path !== '/') await page.goto(path);
    await page.waitForLoadState('networkidle');
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(300);
    found[path] = await focusOverlaps(page);
  }
  for (const [path, list] of Object.entries(found)) for (const o of list) console.log(`OVERLAP ${path} | ${o}`);
  expect(found).toEqual(Object.fromEntries(Object.keys(found).map((k) => [k, []])));
});

// The focus look never covers or touches a neighbour: on every page, menu, sheet and dialog, each
// control is focused like the TV remote does and its box + ring must keep 2px clear of the
// controls around it.
// (fixtures.focusOverlaps: how it's measured). At a TV size and at a laptop size.
const { test, expect, signInAs, focusOverlaps } = require('../fixtures');

const API = 'http://localhost:8101/api';

/** Every screen of the page, top to bottom (the check only looks at what's on screen). */
async function checkPage(page, { scope, screens = 6 } = {}) {
  const found = new Set();
  await page.evaluate(() => window.scrollTo(0, 0));
  for (let i = 0; i < screens; i += 1) {
    await page.waitForTimeout(300);
    for (const o of await focusOverlaps(page, { scope })) found.add(o);
    const moved = await page.evaluate(() => {
      const before = window.scrollY;
      window.scrollBy(0, Math.round(window.innerHeight * 0.8));
      return window.scrollY !== before;
    });
    if (!moved) break;
  }
  return [...found];
}

function report(pages) {
  for (const [path, list] of Object.entries(pages)) for (const o of list) console.log(`OVERLAP ${path} | ${o}`);
}

async function titleUrl(page, name) {
  await page.goto('/search?q=' + encodeURIComponent(name));
  const card = page.locator('.poster-card', { hasText: name }).first();
  await card.click();
  await expect(page.locator('#detail-title')).toHaveText(name);
  return new URL(page.url()).pathname;
}

for (const viewport of [{ width: 1280, height: 720 }, { width: 1920, height: 1080 }]) {
  test.describe(`${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });
    test.describe.configure({ timeout: 300_000 }); // every control of every screen, one by one

    test('browsing pages', async ({ page }) => {
      await signInAs(page, 'Alex');
      const pages = {};
      await expect(page.locator('.row').first()).toBeVisible();
      pages['/'] = await checkPage(page);
      for (const path of ['/movies', '/tv', '/list', '/calendar', '/collection/230', '/search', '/search?q=the']) {
        await page.goto(path);
        await page.waitForLoadState('networkidle');
        pages[path] = await checkPage(page);
      }
      report(pages);
      expect(pages).toEqual(Object.fromEntries(Object.keys(pages).map((k) => [k, []])));
    });

    test('title pages and the player', async ({ page }) => {
      const { session, profile } = await signInAs(page, 'Alex', '/');
      const pages = {};
      // The Godfather: its collection row; Breaking Bad last: its player (episodes) is checked
      for (const name of ['The Godfather', 'Inception', 'Breaking Bad']) {
        const path = await titleUrl(page, name);
        await page.waitForLoadState('networkidle');
        pages[path] = await checkPage(page);
      }
      await page.getByRole('button', { name: /Watch|Resume/ }).first().click();
      await expect(page).toHaveURL(/\/watch\//);
      await page.waitForLoadState('networkidle');
      pages['/watch'] = await checkPage(page);
      // opening the player saved history (Continue watching, a watch entry): clear it, the other
      // tests expect Alex's home as it was (Play, not Resume; no "Next in your collections")
      const res = await page.request.delete(`${API}/history/`, {
        params: { profileId: String(profile.id) },
        headers: { Authorization: `Bearer ${session.access}` },
      });
      expect(res.ok()).toBeTruthy();
      report(pages);
      expect(pages).toEqual(Object.fromEntries(Object.keys(pages).map((k) => [k, []])));
    });

    test('signed out: sign in, sign up', async ({ page }) => {
      const pages = {};
      for (const path of ['/login', '/register']) {
        await page.goto(path);
        await page.waitForLoadState('networkidle');
        pages[path] = await checkPage(page);
      }
      report(pages);
      expect(pages).toEqual(Object.fromEntries(Object.keys(pages).map((k) => [k, []])));
    });

    test('menus, sheets and dialogs', async ({ page }) => {
      await signInAs(page, 'Alex', '/movies');
      const pages = {};
      await expect(page.locator('.poster-card').first()).toBeVisible();
      await page.getByRole('button', { name: 'Filters' }).click();
      await expect(page.locator('.ui-modal')).toBeVisible();
      pages['filters'] = await checkPage(page, { scope: '.ui-modal', screens: 1 });
      await page.keyboard.press('Escape');
      await expect(page.locator('.ui-modal')).toHaveCount(0);

      await page.locator('.poster-card').first().click({ button: 'right' }); // the title options sheet
      await expect(page.locator('.title-options')).toBeVisible();
      pages['title options'] = await checkPage(page, { scope: '.title-options', screens: 1 });
      await page.keyboard.press('Escape');

      await page.locator('.profile-icon').click();
      await expect(page.locator('.profile-dropdown')).toBeVisible();
      pages['profile menu'] = await checkPage(page, { scope: '.profile-dropdown', screens: 1 });
      await page.keyboard.press('Escape');

      await page.locator('.notif__button').click();
      await expect(page.locator('.notif__panel')).toBeVisible();
      pages['notifications'] = await checkPage(page, { scope: '.notif__panel', screens: 1 });
      await page.keyboard.press('Escape');

      await page.goto('/profiles?manage');
      await page.locator('.profile-tile').first().click();
      await page.locator('.profile-form__pic--create').click(); // the avatar builder
      await expect(page.locator('.avatar-builder')).toBeVisible();
      const tabs = page.locator('.avatar-builder__tabs button');
      for (let i = 0; i < await tabs.count(); i += 1) {
        await tabs.nth(i).click();
        const label = (await tabs.nth(i).textContent()).trim();
        pages[`avatar: ${label}`] = await checkPage(page, { scope: '.ui-modal', screens: 1 });
      }
      report(pages);
      expect(pages).toEqual(Object.fromEntries(Object.keys(pages).map((k) => [k, []])));
    });

    test('profiles, account, picker, import', async ({ page }) => {
      const { session } = await signInAs(page, 'Alex', '/profiles');
      const pages = {};
      await expect(page.locator('.profile-tile').first()).toBeVisible();
      pages['/profiles'] = await checkPage(page);
      await page.goto('/profiles?manage');
      await expect(page.locator('.profile-tile').first()).toBeVisible();
      pages['/profiles?manage'] = await checkPage(page);
      await page.locator('.profile-tile').first().click(); // the profile editor dialog
      await expect(page.locator('.ui-modal')).toBeVisible();
      pages['profile editor'] = await checkPage(page, { scope: '.ui-modal', screens: 1 });
      for (const path of ['/taste', '/import', '/history', '/stats', `/account/${session.user.id}`]) {
        await page.goto(path);
        await page.waitForLoadState('networkidle');
        pages[path] = await checkPage(page);
      }
      report(pages);
      expect(pages).toEqual(Object.fromEntries(Object.keys(pages).map((k) => [k, []])));
    });
  });
}

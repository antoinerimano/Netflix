// The landing page with a TV remote only: arrows / OK, the focus always visible and never lost.
const path = require('path');
const { pathToFileURL } = require('url');
const { test, expect } = require('@playwright/test');

const PAGE = pathToFileURL(path.join(__dirname, '..', '..', 'landing', 'index.html')).href;
const SITE = 'https://tauruss.top';
const SHOTS = process.env.LANDING_SHOTS; // a folder: save screenshots there (design review)

async function focused(page) {
  return page.evaluate(() => {
    const a = document.activeElement;
    return !a || a === document.body ? 'BODY' : `${a.tagName} ${a.textContent.trim().replace(/\s+/g, ' ')}`;
  });
}
async function remote(page, keys) {
  const map = { Up: 'ArrowUp', Down: 'ArrowDown', Left: 'ArrowLeft', Right: 'ArrowRight', OK: 'Enter' };
  for (const k of keys.split(' ')) {
    await page.keyboard.press(map[k]);
    await page.waitForTimeout(300);
  }
}

test.beforeEach(async ({ page }) => {
  // never leave for the real site: a "Visit site" press is caught here
  await page.route(`${SITE}/**`, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: '<h1>App</h1>' }));
  await page.goto(PAGE);
});

test('the remote starts on "Visit site", OK opens the app', async ({ page }) => {
  expect(await focused(page)).toBe('A Visit site');
  if (SHOTS) {
    await page.waitForTimeout(1500);
    await page.screenshot({ path: path.join(SHOTS, 'hero-720.png') });
  }
  await remote(page, 'OK');
  await expect(page).toHaveURL(`${SITE}/`);
});

test('arrows reach every link and come back, never lost', async ({ page }) => {
  await remote(page, 'Right');
  expect(await focused(page)).toBe('A Create an account');
  await remote(page, 'Left Up');
  expect(await focused(page)).toBe('A Sign in');

  await remote(page, 'Down Down');
  expect(await focused(page)).toBe('A Visit site');
  // the closing "Visit site", far below: scrolled into view and shown
  await remote(page, 'Down');
  const last = page.locator('.final .cta');
  await expect(last).toBeFocused();
  await expect(last).toBeInViewport();
  await expect(last).toHaveCSS('opacity', '1');
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, 'final-720.png') });

  await remote(page, 'Down Down Up Up');
  expect(await focused(page)).not.toBe('BODY');
  await remote(page, 'OK');
  await expect(page).toHaveURL(new RegExp(`^${SITE}/`));
});

test('"Create an account" and "Sign in" open those app pages', async ({ page }) => {
  await remote(page, 'Right OK');
  await expect(page).toHaveURL(`${SITE}/register`);
  await page.goto(PAGE);
  await remote(page, 'Up OK');
  await expect(page).toHaveURL(`${SITE}/login`);
});

test('design screenshots', async ({ page }) => {
  test.skip(!SHOTS, 'LANDING_SHOTS not set');
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto(PAGE);
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(SHOTS, 'hero-1080.png') });
  await page.mouse.wheel(0, 1000);
  await page.waitForTimeout(1800);
  await page.screenshot({ path: path.join(SHOTS, 'features-1080.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(PAGE);
  await page.waitForTimeout(2000);
  await page.screenshot({ path: path.join(SHOTS, 'phone.png'), fullPage: true });
});

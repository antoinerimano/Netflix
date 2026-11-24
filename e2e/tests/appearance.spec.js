// "Appearance" (/appearance) with the TV remote only: from the account page, Customize opens it;
// a font pair, an accent color and a background are picked with arrows + OK, the whole site
// changes at once (the design tokens on <html>), the choice is saved on the profile (it comes
// back after a reload) and "Back to default" undoes it all. Profile "Sam" ends on the default look.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

const token = (page, name) =>
  page.evaluate((n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim(), name);

/** Presses `key` until the focus matches (the remote never gets lost on the way). */
async function moveTo(page, key, wanted, max = 12) {
  for (let i = 0; i < max && !wanted.test(await focused(page)); i += 1) {
    await remote(page, key);
    expect(await focused(page)).not.toBe('BODY');
  }
  expect(await focused(page)).toMatch(wanted);
}

/** In a row of choices: Right until the end, then Left (the focus may land anywhere in the row). */
async function moveInRow(page, wanted) {
  for (const key of ['Right', 'Left']) {
    for (let i = 0; i < 10 && !wanted.test(await focused(page)); i += 1) {
      const before = await focused(page);
      await remote(page, key);
      expect(await focused(page)).not.toBe('BODY');
      if ((await focused(page)) === before) break; // end of the row
    }
  }
  expect(await focused(page)).toMatch(wanted);
}

test('pick fonts, accent and background, then back to default: all with the remote', async ({ page }) => {
  const { session, profile } = await signInAs(page, 'Sam', '/');
  const auth = { headers: { Authorization: `Bearer ${session.access}` } };
  const saved = async () =>
    (await (await page.request.get(`${API}/users/${session.user.id}/profiles/${profile.id}/`, auth)).json()).appearance;

  // the account page leads there
  await page.goto(`/account/${session.user.id}`);
  await expect(page.getByRole('heading', { name: 'Appearance' })).toBeVisible();
  await moveTo(page, 'Down', /^A Customize/);
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/appearance$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Appearance' })).toBeVisible();
  await expect(page.getByRole('radio', { name: /^Original/ })).toHaveAttribute('aria-checked', 'true');

  // fonts: the first row of choices, Right to "Cinema", OK
  await moveTo(page, 'Down', /^BUTTON Original/);
  await moveInRow(page, /^BUTTON Cinema/);
  await remote(page, 'OK');
  await expect(page.getByRole('radio', { name: /^Cinema/ })).toHaveAttribute('aria-checked', 'true');
  expect(await token(page, '--font-display')).toContain('Oswald');
  expect(await focused(page)).toMatch(/^BUTTON Cinema/); // the focus stays on the choice

  // accent color: further down, "Blue"
  await moveTo(page, 'Down', /^BUTTON (Red|Orange|Gold|Green|Teal|Blue|Purple|Pink)$/);
  await moveInRow(page, /^BUTTON Blue$/);
  await remote(page, 'OK');
  await expect(page.getByRole('radio', { name: 'Blue', exact: true })).toHaveAttribute('aria-checked', 'true');
  expect(await token(page, '--color-brand')).toBe('#2563eb');

  // background: "Midnight blue"
  await moveTo(page, 'Down', /^BUTTON (Graphite|Pure black|Midnight blue|Espresso|Forest)$/);
  await moveInRow(page, /^BUTTON Midnight blue$/);
  await remote(page, 'OK');
  expect(await token(page, '--color-bg')).toBe('#0b1020');
  await expect(page.getByRole('status')).toHaveText('Saved');
  await expect.poll(saved).toEqual({ font: 'cinema', accent: 'blue', background: 'midnight' });

  // saved on the profile: still there after a reload, and on the other pages
  await page.reload();
  await expect(page.getByRole('radio', { name: 'Blue', exact: true })).toHaveAttribute('aria-checked', 'true');
  expect(await token(page, '--color-brand')).toBe('#2563eb');
  await page.goto('/');
  expect(await token(page, '--color-bg')).toBe('#0b1020');

  // back to default: the button keeps the focus, everything returns to the original look
  await page.goto('/appearance');
  await expect(page.getByRole('radio', { name: /^Cinema/ })).toHaveAttribute('aria-checked', 'true');
  await moveTo(page, 'Down', /^BUTTON Back to default/, 20);
  await remote(page, 'OK');
  await expect(page.getByRole('radio', { name: /^Original/ })).toHaveAttribute('aria-checked', 'true');
  expect(await focused(page)).toMatch(/^BUTTON Back to default/);
  expect(await token(page, '--color-brand')).toBe('#e50914');
  await expect(page.getByRole('status')).toHaveText('Saved');
  await expect.poll(saved).toEqual({});
});

test('an expired session takes the profile look with it: the next sign-in starts from the default', async ({ page }) => {
  const { session, profile } = await signInAs(page, 'Sam', '/');
  const auth = { headers: { Authorization: `Bearer ${session.access}` } };
  await page.request.patch(`${API}/users/${session.user.id}/profiles/${profile.id}/`, { ...auth, data: { appearance: { accent: 'blue' } } });
  try {
    await page.goto('/appearance');
    await expect(page.getByRole('radio', { name: 'Blue', exact: true })).toHaveAttribute('aria-checked', 'true');
    expect(await token(page, '--color-brand')).toBe('#2563eb');

    // the session is no longer valid (refresh refused): the app signs out by itself
    await page.evaluate(() => {
      localStorage.setItem('access', 'expired');
      localStorage.setItem('refresh', 'expired');
    });
    await page.goto('/');
    await expect(page).toHaveURL(/\/login$/);
    expect(await token(page, '--color-brand')).toBe('#e50914');
    expect(await page.evaluate(() => [localStorage.getItem('activeProfile'), localStorage.getItem('activeProfileId')])).toEqual([null, null]);
  } finally {
    await page.request.patch(`${API}/users/${session.user.id}/profiles/${profile.id}/`, { ...auth, data: { appearance: {} } });
  }
});

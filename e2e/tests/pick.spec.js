// "What to watch?" with the TV remote: "Surprise me" on the home banner opens one title (focus on
// Watch), "Another one" keeps the focus on itself; the time / mood choices, "Nothing fits" when
// nothing does, "Show me" with the focus on the first result, OK opens it.
// The e2e catalog has no movie under 90 minutes; about 2 hours + funny = Amélie (128 min).
const { test, expect, signInAs, focused, remote } = require('../fixtures');

test.use({ viewport: { width: 1280, height: 720 } });

async function moveUntil(page, key, pattern, max = 8) {
  for (let i = 0; i < max && !pattern.test(await focused(page)); i += 1) await remote(page, key);
  expect(await focused(page)).toMatch(pattern);
}

test('surprise me, then choose the time and the mood', async ({ page }) => {
  await signInAs(page, 'Alex');
  await expect(page.locator('.row').first()).toBeVisible();
  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Play/);
  await moveUntil(page, 'Right', /^BUTTON Surprise me/, 3);
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/pick\?surprise=1$/);

  const title = page.locator('.pick-surprise__title');
  await expect(title).toBeVisible();
  await expect.poll(() => focused(page)).toBe('BUTTON Watch');
  const first = await title.textContent();
  await moveUntil(page, 'Right', /^BUTTON Another one/, 3);
  await remote(page, 'OK');
  await expect(title).not.toHaveText(first);
  expect(await focused(page)).toBe('BUTTON Another one'); // again and again from the same button

  // under 90 minutes: nothing in this catalog
  await moveUntil(page, 'Up', /^BUTTON No limit/);
  await moveUntil(page, 'Left', /^BUTTON Under 90 min/, 4);
  await remote(page, 'OK');
  await moveUntil(page, 'Down', /^BUTTON Show me/, 3);
  await remote(page, 'OK');
  await expect(page.getByRole('heading', { name: 'Nothing fits' })).toBeVisible();

  // about 2 hours, funny: Amélie
  await moveUntil(page, 'Up', /^BUTTON Under 90 min/, 4);
  await remote(page, 'Right OK');
  await expect(page.getByRole('button', { name: 'About 2 hours' })).toHaveAttribute('aria-pressed', 'true');
  await remote(page, 'Down');
  await moveUntil(page, 'Right', /^BUTTON Funny/, 3);
  await remote(page, 'OK');
  await moveUntil(page, 'Down', /^BUTTON Show me/, 3);
  await remote(page, 'OK');
  const card = page.locator('.pick-card').first();
  await expect(card).toContainText('Amélie');
  await expect(card).toContainText('2 hr 8 min');
  await expect(card).toBeFocused(); // the remote follows what came out
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/movies\/\d+$/);
});

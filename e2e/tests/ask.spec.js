// "Ask Taurus" with the TV remote (roadmap 8.10): from "What to watch?", OK on "Ask Taurus"; Down
// to the starters, OK on "A series to binge"; the answer comes (the scripted fake, AI_FAKE: never
// the API), the focus lands on the first title, nothing on the page overlaps when focused, the
// follow-ups replace the starters; OK opens the show.
const { test, expect, signInAs, focused, remote, focusOverlaps } = require('../fixtures');

test.use({ viewport: { width: 1280, height: 720 } });

async function moveUntil(page, key, pattern, max = 8) {
  for (let i = 0; i < max && !pattern.test(await focused(page)); i += 1) await remote(page, key);
  expect(await focused(page)).toMatch(pattern);
}

test('ask for a series with the remote, open one', async ({ page }) => {
  await signInAs(page, 'Alex', '/pick');
  await expect(page.getByRole('heading', { name: 'What to watch?' })).toBeVisible();
  await moveUntil(page, 'Down', /^BUTTON (Show me|Surprise me|Ask Taurus)/);
  await moveUntil(page, 'Right', /^BUTTON Ask Taurus/, 4);
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/ask$/);
  await expect(page.getByRole('heading', { name: 'Ask Taurus' })).toBeVisible();

  await moveUntil(page, 'Down', /^BUTTON Something funny tonight/, 4);
  await moveUntil(page, 'Right', /^BUTTON A series to binge/, 4);
  await remote(page, 'OK');

  await expect(page.getByText('Here are a few ideas for tonight.')).toBeVisible();
  const first = page.locator('.ask-turn .pick-card').first();
  await expect(first).toBeVisible();
  await expect.poll(() => focused(page)).toMatch(/^BUTTON (Breaking Bad|Night Shift)/); // the remote follows the answer
  await expect(page.getByRole('button', { name: 'Something funny tonight' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'A series instead' })).toBeVisible();
  expect(await focusOverlaps(page)).toEqual([]);

  await first.focus();
  await remote(page, 'OK');
  await expect(page).toHaveURL(/\/tv\/\d+$/);
});

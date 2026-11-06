// "Upcoming" (/calendar) with the TV remote only: an empty calendar offers shows coming back,
// OK follows one and its episodes join the days above, Up reaches them, OK on an episode still
// to come opens the show, Back returns to the card. Show "Night Shift" airs in 3 and 10 days
// (backend e2e_prepare); profile "Sam" tracks nothing at first.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

test('follow a show coming back, then its episodes are in the calendar', async ({ page }) => {
  const { session, profile } = await signInAs(page, 'Sam', '/calendar');
  await expect(page.getByRole('heading', { name: 'Your calendar is empty' })).toBeVisible();
  await expect(page.getByRole('navigation').getByText('Upcoming')).toBeVisible();

  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Follow: Night Shift, S1 · E2, In 3 days/);
  await remote(page, 'OK');
  const card = page.getByRole('button', { name: /^Follow: Night Shift/ });
  await expect(card).toHaveAttribute('aria-pressed', 'true');
  await expect(card).toBeFocused(); // the remote stays on it
  await expect(page.getByRole('heading', { name: 'Your calendar is empty' })).toHaveCount(0);
  await expect(page.locator('.cal-day:not(.cal-suggest)', { hasText: 'In 3 days' })).toContainText('Shift 2');

  await remote(page, 'Up');
  expect(await focused(page)).toMatch(/^BUTTON Night Shift, season 1, episode 3/); // in 10 days
  await remote(page, 'Up');
  expect(await focused(page)).toMatch(/^BUTTON Night Shift, season 1, episode 2/); // in 3 days
  const episode = await focused(page);

  await remote(page, 'OK'); // not out yet: the show's page
  await expect(page).toHaveURL(/\/tv\/\d+$/);
  await expect(page.locator('#detail-title')).toHaveText('Night Shift');
  await remote(page, 'Back');
  await expect(page).toHaveURL(/\/calendar$/);
  await expect.poll(() => focused(page)).toBe(episode);

  // leave Sam as it was: unfollow
  const auth = { params: { profileId: String(profile.id) }, headers: { Authorization: `Bearer ${session.access}` } };
  const calendar = await (await page.request.get(`${API}/calendar/`, auth)).json();
  const res = await page.request.delete(`${API}/follows/${calendar.upcoming[0].show.id}/`, auth);
  expect(res.ok()).toBeTruthy();
});

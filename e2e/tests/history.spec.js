// "Watch history" (/history) with the TV remote: entries by day, Right + OK removes one (the focus
// moves to the next), the pause switch stops recording, Clear history asks first and empties it.
// Profile "Kids" watches Toy Story and Spirited Away (what the watch page sends when it opens);
// the test ends with an empty history.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const API = 'http://localhost:8101/api';

test.use({ viewport: { width: 1280, height: 720 } });

async function titleId(page, name) {
  const res = await page.request.get(`${API}/titles/search/`, { params: { q: name } });
  const data = await res.json();
  return (data.results || data).find((t) => t.title === name).id;
}

test('remove an entry, pause, clear: all with the remote', async ({ page }) => {
  const { session, profile } = await signInAs(page, 'Kids', '/');
  const auth = { headers: { Authorization: `Bearer ${session.access}` } };
  const watch = async (name) =>
    page.request.post(`${API}/watch-progress/`, { ...auth, data: { profile_id: profile.id, title_id: await titleId(page, name) } });
  await watch('Spirited Away');
  await watch('Toy Story'); // newest: first

  await page.goto('/history');
  const rows = page.locator('.history-row');
  await expect(rows).toHaveCount(2);
  await expect(page.getByRole('heading', { name: 'Today' })).toBeVisible();

  await remote(page, 'Down');
  expect(await focused(page)).toMatch(/^BUTTON Pause watch history/);
  await remote(page, 'Down Down');
  expect(await focused(page)).toMatch(/^BUTTON Toy Story/);
  await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Remove Toy Story from history');
  await remote(page, 'OK');
  await expect(rows).toHaveCount(1);
  await expect(page.getByText('Toy Story removed from history')).toBeVisible();
  await expect.poll(() => focused(page)).toBe('BUTTON Remove Spirited Away from history'); // the next one

  // pause: watching saves nothing (up to the switch, never past it to the navbar)
  for (let i = 0; i < 3 && !/^BUTTON Pause watch history/.test(await focused(page)); i += 1) await remote(page, 'Up');
  expect(await focused(page)).toMatch(/^BUTTON Pause watch history/);
  await remote(page, 'OK');
  await expect(page.getByRole('switch', { name: /Pause watch history/ })).toHaveAttribute('aria-checked', 'true');
  await watch('Toy Story');
  await page.reload();
  await expect(rows).toHaveCount(1);
  await expect(page.getByRole('switch', { name: /Pause watch history/ })).toHaveAttribute('aria-checked', 'true');
  await remote(page, 'Down OK'); // starts on the switch: turn it back on
  await expect(page.getByRole('switch', { name: /Pause watch history/ })).toHaveAttribute('aria-checked', 'false');

  // clear: asks first, Cancel is where the focus lands
  await remote(page, 'Down'); // the toolbar: Your year, Download, Clear history
  for (let i = 0; i < 3 && (await focused(page)) !== 'BUTTON Clear history'; i += 1) await remote(page, 'Right');
  expect(await focused(page)).toBe('BUTTON Clear history');
  await remote(page, 'OK');
  await expect(page.locator('.ui-modal')).toBeVisible();
  await expect.poll(() => focused(page)).toBe('BUTTON Cancel');
  await remote(page, 'Right OK');
  await expect(page.getByRole('heading', { name: 'Nothing watched yet' })).toBeVisible();
  await expect(rows).toHaveCount(0);
});

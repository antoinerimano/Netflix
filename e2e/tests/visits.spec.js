// Site visitors (admin dashboard): moving around the app with the remote reports each page,
// and never gets in the way of the focus. A normal browser name: headless ones are not counted.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

test.use({
  viewport: { width: 1280, height: 720 },
  userAgent: 'Mozilla/5.0 (SMART-TV; LINUX; Tizen 6.0) AppleWebKit/537.36 SamsungBrowser/4.0 TV Safari/537.36',
});

const visit = (page, kind, path) =>
  page.waitForResponse((r) => {
    if (!r.url().includes('/api/events/visit/')) return false;
    const body = r.request().postDataJSON() || {};
    return body.kind === kind && path.test(body.path) && r.status() === 204;
  });

test('remote: every page opened is one page view, from the same visitor', async ({ page }) => {
  const home = visit(page, 'view', /^\/$/);
  await signInAs(page, 'Alex');
  const first = (await home).request().postDataJSON();
  expect(first.visitor_id).toMatch(/^[0-9a-f-]{36}$/);

  await expect(page.locator('.row').first()).toBeVisible();
  const detail = visit(page, 'view', /^\/(movies|tv)\/\d+$/);
  await remote(page, 'Down Down OK'); // the banner's Play, the first card, open it
  const second = (await detail).request().postDataJSON();
  expect(second.visitor_id).toBe(first.visitor_id);
  expect(second.session_id).toBe(first.session_id); // the same visit
  expect(second.referrer).toBe(''); // only the first page says where the visitor came from
  await expect(page.locator('#detail-title')).toBeVisible();
  await remote(page, 'Down'); // the remote still moves around the title page
  expect(await focused(page)).not.toBe('BODY');
});

// Trailer previews on the home rows: the remote (focus) and the mouse (hover) start them, one at
// a time, and the banner's trailer pauses meanwhile. Every row title gets a clip here (the test
// data has none): a real little video, made by the browser itself, served as the CDN's.
const { test, expect, signInAs, focused, remote } = require('../fixtures');

const CLIP = 'https://cdn.e2e.test/previews/clip.webm';

/** 1.5 s of changing colours, recorded from a canvas: WebM, plays in Playwright's Chromium */
async function makeClip(page) {
  const b64 = await page.evaluate(async () => {
    const c = Object.assign(document.createElement('canvas'), { width: 320, height: 180 });
    const ctx = c.getContext('2d');
    const rec = new MediaRecorder(c.captureStream(30), { mimeType: 'video/webm;codecs=vp8' });
    const chunks = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    let f = 0;
    const draw = setInterval(() => {
      ctx.fillStyle = `hsl(${(f++ * 12) % 360} 70% 50%)`;
      ctx.fillRect(0, 0, 320, 180);
    }, 33);
    rec.start(250);
    await new Promise((r) => setTimeout(r, 1500));
    await new Promise((r) => { rec.onstop = r; rec.stop(); });
    clearInterval(draw);
    const bytes = new Uint8Array(await new Blob(chunks).arrayBuffer());
    let s = '';
    for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
    return btoa(s);
  });
  return Buffer.from(b64, 'base64');
}

async function withPreviews(page) {
  const clip = await makeClip(page);
  await page.route(CLIP, (route) => route.fulfill({ status: 200, contentType: 'video/webm', body: clip }));
  await page.route(/\/api\/reco\/home\//, async (route) => {
    const res = await route.fetch();
    const data = await res.json();
    const rows = Array.isArray(data) ? data : data.rows || [];
    for (const r of rows) for (const it of r.items || []) it.trailer_clip_url = CLIP;
    await route.fulfill({ response: res, json: data });
  });
}

const playing = (locator) =>
  locator.evaluate((v) => !v.paused && v.readyState >= 2).catch(() => false);

test.describe('remote', () => {
  test.use({ viewport: { width: 1280, height: 720 } });

  test('the focused card plays its preview, the next card takes over, the banner pauses', async ({ page }) => {
    await withPreviews(page);
    await signInAs(page, 'Alex');
    await expect(page.locator('.row').first()).toBeVisible();

    await remote(page, 'Down Down'); // the banner's Play, then the first card
    const first = await focused(page);
    expect(first).toMatch(/^DIV /);
    const preview = page.locator('.movie-card:focus .row-preview.is-showing');
    await expect(preview).toBeVisible({ timeout: 8000 });
    await expect.poll(() => playing(preview)).toBe(true);
    await expect(page.locator('.row-preview')).toHaveCount(1); // one at a time
    if (await page.locator('.hero__video').count()) {
      await expect.poll(() => page.locator('.hero__video').evaluate((v) => v.paused)).toBe(true);
    }

    await remote(page, 'Right');
    expect(await focused(page)).not.toBe(first);
    await expect(page.locator('.row-preview.is-showing')).toHaveCount(0); // the old one stopped at once
    await expect(preview).toBeVisible({ timeout: 8000 }); // the new card's
    await expect(page.locator('.row-preview')).toHaveCount(1);

    await remote(page, 'Up'); // back to the banner: no preview left
    await expect(page.locator('.row-preview')).toHaveCount(0);
    expect(await focused(page)).not.toBe('BODY');
  });
});

test('mouse: hover plays the preview, sound on is remembered, leaving stops it', async ({ page }) => {
  await withPreviews(page);
  await signInAs(page, 'Alex');
  const card = page.locator('.row').first().locator('.movie-card').first();
  await card.hover();
  const preview = card.locator('.row-preview.is-showing');
  await expect(preview).toBeVisible({ timeout: 8000 });
  await expect.poll(() => playing(preview)).toBe(true);

  await card.getByRole('button', { name: /unmute/i }).click();
  await expect(card.getByRole('button', { name: /^mute/i })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('previewMuted'))).toBe('0');

  await page.mouse.move(5, 5);
  await expect(page.locator('.row-preview')).toHaveCount(0);
});

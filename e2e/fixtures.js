// Shared test setup: the outside world is stubbed (players, images, fonts), sign-in helpers, and
// TV remote helpers (arrows / OK / Back are keyboard keys, like the app expects from a remote).
const base = require('@playwright/test');

const API = 'http://localhost:8101/api';
const USER = { email: 'e2e@example.test', password: 'E2e-pass-1234!' }; // backend e2e_prepare.py

// A stand-in for the embedded players. It answers CineSrc's postMessage API (play / pause / seek)
// and keeps the commands it got in window.commands, for the tests to read.
const FAKE_PLAYER = `<!doctype html><html><body style="margin:0;background:#111;color:#eee;font:20px sans-serif">
<p id="state">fake player</p>
<script>
  window.commands = [];
  addEventListener('message', (e) => {
    const d = e.data || {};
    if (d.type !== 'cinesrc:command') return;
    window.commands.push(d.command + (d.args && d.args.length ? ':' + d.args.join(',') : ''));
    document.getElementById('state').textContent = window.commands.join(' ');
    if (d.command === 'play' || d.command === 'pause') parent.postMessage({ type: 'cinesrc:' + d.command }, '*');
  });
  parent.postMessage({ type: 'cinesrc:ready' }, '*');
</script></body></html>`;

const test = base.test.extend({
  page: async ({ page }, use) => {
    await page.route(/^https:\/\/(player\.e2e\.test|cinesrc\.st)\//, (route) =>
      route.fulfill({ status: 200, contentType: 'text/html', body: FAKE_PLAYER })
    );
    // nothing else leaves the machine (images, fonts, analytics): fast, and the same every run
    await page.route(/^https?:\/\/(?!localhost|127\.0\.0\.1|player\.e2e\.test|cinesrc\.st)/, (route) => route.abort());
    await use(page);
  },
});

/** Signed in through the API (fast), with a profile chosen: the app opens on `path`. */
async function signInAs(page, profileName = 'Alex', path = '/') {
  const res = await page.request.post(`${API}/users/login/`, { data: USER });
  base.expect(res.ok()).toBeTruthy();
  const session = await res.json();
  const profiles = await (
    await page.request.get(`${API}/users/${session.user.id}/profiles/`, { headers: { Authorization: `Bearer ${session.access}` } })
  ).json();
  const list = Array.isArray(profiles) ? profiles : profiles.results;
  const profile = list.find((p) => p.name === profileName);
  await page.addInitScript(
    ({ s, p }) => {
      if (sessionStorage.getItem('e2e-signed-in')) return; // only once: the app may change them afterwards
      sessionStorage.setItem('e2e-signed-in', '1');
      localStorage.setItem('access', s.access);
      localStorage.setItem('refresh', s.refresh);
      localStorage.setItem('userId', s.user.id);
      localStorage.setItem('user', JSON.stringify(s.user));
      localStorage.setItem('activeProfileId', String(p.id));
      localStorage.setItem('activeProfile', JSON.stringify(p));
      localStorage.setItem('lang', p.language_preference || 'en');
    },
    { s: session, p: profile }
  );
  await page.goto(path);
  return { session, profile };
}

/** What has the focus, in words ("BUTTON Play"): the remote must never be lost (BODY). */
async function focused(page) {
  return page.evaluate(() => {
    const a = document.activeElement;
    if (!a || a === document.body) return 'BODY';
    return `${a.tagName} ${(a.getAttribute('aria-label') || a.textContent || '').trim().slice(0, 60)}`;
  });
}

/** Presses remote keys one by one: "Down Down Right OK Back" */
async function remote(page, keys) {
  const map = { Up: 'ArrowUp', Down: 'ArrowDown', Left: 'ArrowLeft', Right: 'ArrowRight', OK: 'Enter', Back: 'Escape' };
  for (const k of keys.split(/\s+/)) {
    await page.keyboard.press(map[k] || k);
    await page.waitForTimeout(250); // the app scrolls / slides smoothly
  }
}

module.exports = { test, expect: base.expect, signInAs, focused, remote, USER };

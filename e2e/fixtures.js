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

/**
 * Focuses every control on screen like the remote does, and lists the ones whose focus look
 * (enlarged box + ring) covers or touches a neighbouring control (less than 2px of page between them): ["BUTTON Play -> BUTTON More info (6x40)"].
 * The focus look: the element's box after its transform, grown by its rings (box-shadows with no
 * blur), and the same for whatever inside it moves or gets a ring (a poster card's artwork).
 * Shadows with a blur are soft depth, not edges: they may spill over.
 */
async function focusOverlaps(page, { scope = 'body' } = {}) {
  await page.keyboard.press('Shift'); // keyboard mode: programmatic focus shows :focus-visible
  return page.evaluate(async (scopeSel) => {
    // the final focus look at once (no 160 ms transition per control): fast and the same every run
    if (!document.getElementById('e2e-no-anim')) {
      const st = document.createElement('style');
      st.id = 'e2e-no-anim';
      st.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; }';
      document.head.appendChild(st);
    }
    const MIN_GAP = 2; // px of page between the focus look and any neighbour
    const FOCUSABLE = "a[href], button:not([disabled]), input:not([disabled]):not([type='hidden']), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
    const root = document.querySelector(scopeSel) || document.body;
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.opacity !== '0'
        && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
    };
    // everything clipped away by a parent (slider rows, scrolled lists) isn't on screen
    const clipped = (el) => {
      const r = el.getBoundingClientRect();
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (/(hidden|auto|scroll|clip)/.test(cs.overflowX + cs.overflowY)) {
          const b = p.getBoundingClientRect();
          if (r.right <= b.left + 1 || r.left >= b.right - 1 || r.bottom <= b.top + 1 || r.top >= b.bottom - 1) return true;
        }
      }
      return false;
    };
    const ring = (el) => {
      const bs = getComputedStyle(el).boxShadow;
      if (!bs || bs === 'none') return 0;
      let max = 0;
      for (const part of bs.split(/,(?![^(]*\))/)) {
        if (part.includes('inset')) continue;
        const [x = 0, y = 0, blur = 0, spread = 0] = part.replace(/rgba?\([^)]*\)/g, '').trim().split(/\s+/).map(parseFloat);
        if (blur === 0 && spread > 0) max = Math.max(max, spread + Math.max(Math.abs(x), Math.abs(y)));
      }
      return max;
    };
    const clips = (e) => /(hidden|clip)/.test(getComputedStyle(e).overflowX + getComputedStyle(e).overflowY);
    // a part inside the element, cut by the boxes that clip it on the way up (a zoomed image
    // inside a card that hides its overflow doesn't spill over)
    const visiblePart = (d, el, s) => {
      const r = d.getBoundingClientRect();
      let box = { l: r.left - s, t: r.top - s, r: r.right + s, b: r.bottom + s };
      for (let p = d.parentElement; p && el.contains(p); p = p.parentElement) {
        if (!clips(p)) continue;
        const c = p.getBoundingClientRect();
        box = { l: Math.max(box.l, c.left), t: Math.max(box.t, c.top), r: Math.min(box.r, c.right), b: Math.min(box.b, c.bottom) };
      }
      return box;
    };
    const lookOf = (el) => {
      const r0 = el.getBoundingClientRect();
      const s0 = ring(el);
      let box = { l: r0.left - s0, t: r0.top - s0, r: r0.right + s0, b: r0.bottom + s0 };
      const inner = clips(el) ? { l: r0.left, t: r0.top, r: r0.right, b: r0.bottom } : null;
      for (const d of el.querySelectorAll('*')) {
        const s = ring(d);
        if (s === 0 && getComputedStyle(d).transform === 'none') continue;
        let v = visiblePart(d, el, s);
        if (inner) v = { l: Math.max(v.l, inner.l), t: Math.max(v.t, inner.t), r: Math.min(v.r, inner.r), b: Math.min(v.b, inner.b) };
        if (v.r > v.l && v.b > v.t) box = { l: Math.min(box.l, v.l), t: Math.min(box.t, v.t), r: Math.max(box.r, v.r), b: Math.max(box.b, v.b) };
      }
      return box;
    };
    // a fixed / sticky bar (navbar, filter bar, bottom bar): the page scrolls under it by design
    const pinnedOf = (e) => {
      for (let p = e; p && p !== document.body; p = p.parentElement) {
        const pos = getComputedStyle(p).position;
        if (pos === 'fixed' || pos === 'sticky') return p;
      }
      return null;
    };
    const name = (el) => `${el.tagName} ${(el.getAttribute('aria-label') || el.textContent || el.className || '').trim().replace(/\s+/g, ' ').slice(0, 40)}`;

    const els = [...root.querySelectorAll(FOCUSABLE)].filter((el) => visible(el) && !clipped(el));
    const found = [];
    for (const el of els) {
      el.focus({ preventScroll: true });
      if (!el.matches(':focus-visible')) continue;
      await new Promise((r) => setTimeout(r, 30)); // a frame for the focus look
      const v = lookOf(el);
      const pinned = pinnedOf(el);
      // where the element sits without its focus look (a row may have slid to show it: the
      // neighbours are measured where they are now, not where they were)
      const now = el.getBoundingClientRect();
      const cx = (now.left + now.right) / 2;
      const cy = (now.top + now.bottom) / 2;
      const r0 = { left: cx - el.offsetWidth / 2, right: cx + el.offsetWidth / 2, top: cy - el.offsetHeight / 2, bottom: cy + el.offsetHeight / 2 };
      for (const n of els) {
        if (n === el || n.contains(el) || el.contains(n)) continue;
        if (pinnedOf(n) !== pinned) continue; // one of them scrolls under the other's bar
        const b = n.getBoundingClientRect();
        const ox = Math.min(v.r, b.right) - Math.max(v.l, b.left);
        const oy = Math.min(v.b, b.bottom) - Math.max(v.t, b.top);
        // already that close without the focus look (menu rows stacked flush, stacked on purpose):
        // only a look that grows past its box would make it worse
        const restOx = Math.min(r0.right, b.right) - Math.max(r0.left, b.left);
        const restOy = Math.min(r0.bottom, b.bottom) - Math.max(r0.top, b.top);
        const grows = v.l < r0.left - 1 || v.t < r0.top - 1 || v.r > r0.right + 1 || v.b > r0.bottom + 1;
        if (restOx > -MIN_GAP && restOy > -MIN_GAP && !(grows && restOx <= 0 && restOy <= 0 && ox > 1 && oy > 1)) continue;
        // touching counts too: a ring against the next box reads as overlapping on a TV
        if (ox > -MIN_GAP && oy > -MIN_GAP) found.push(`${name(el)} -> ${name(n)} (${Math.round(ox)}x${Math.round(oy)})`);
      }
    }
    document.activeElement?.blur();
    document.getElementById('e2e-no-anim')?.remove();
    return found;
  }, scope);
}

module.exports = { test, expect: base.expect, signInAs, focused, remote, focusOverlaps, USER };

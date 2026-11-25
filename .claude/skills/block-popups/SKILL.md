---
name: block-popups
description: Build ROADMAP item 9.1, the "Block pop-ups" switch that sandboxes the embedded player iframes on the watch page so third-party players can't open new tabs or redirect the page. Use when the user types /block-popups or asks to work on 9.1 / block pop-ups.
---

# Block pop-ups (ROADMAP 9.1)

Taurus runs no ads of its own and hosts no films. The pop-ups and redirects come from the
third-party players embedded in `frontend/src/components/WatchPage.jsx` (the `<iframe>` with
`iframeRef`). The goal is to stop those players from opening new tabs or navigating our page,
without breaking playback, progress tracking or full screen. Do not build our own player: that
item (9.10) was dropped.

## Before writing code

1. Read ROADMAP.txt item 9.1, items 2.1 (smart playback) and 4.9 (watch page) for context, and mark
   9.1 as `[~]`.
2. Read `WatchPage.jsx` (iframe, `onLoad`, `autoFailedRef`, source chips, the player-event
   `onMessage` handler), `frontend/src/components/watch/playerEvents.js`, the `Provider` model in
   `backend/users/models.py`, and `provider_scraper/provider_health.py`.
3. Write a short plan (files, data, what the remote does) and show it to the user before building.

## What to build

**Sandbox on the iframe.** When blocking is ON the iframe gets
`sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"`: no `allow-popups` and no
`allow-top-navigation*`. Keep the `allow=` attribute (autoplay, fullscreen, picture-in-picture,
encrypted-media) and `allowFullScreen`.
- A sandbox only applies when the frame navigates. Remount the iframe (change its `key`) when the
  switch changes.
- `allow-same-origin` is safe here because the frames are cross-origin. Never sandbox a frame on our
  own origin with `allow-scripts allow-same-origin`.
- Check that the postMessage progress events (videasy, cinesrc, vidcore) still arrive when the
  frame is sandboxed.

**Know which sources still play when sandboxed.** Some embeds detect the sandbox and refuse to play.
- Add a field on `Provider`, for example `sandbox_ok` (yes / no / unknown), with a migration. Show
  it in the Django admin and on the dashboard's provider card.
- Teach the provider scout's check (`provider_scraper/`) to load each source sandboxed as well and
  record the result. The scout runs on the mini PC (`~/provider-scout`). Change the code in the repo
  only. Don't connect to the mini PC or deploy there unless the user asks, and the mini PC must
  never connect to the laptop.
- On the watch page, a sandboxed source that fails by itself teaches the app the same thing (the
  same path as `autoFailedRef`).

**The switch.**
- A per-profile setting "Block pop-ups", ON by default, saved on the server like the other profile
  settings. It also appears as a switch in the watch page's source row.
- When it's ON: sources with `sandbox_ok = no` go last, with a "may open pop-ups" note. Sources
  that work sandboxed get a small "No pop-ups" chip.
- If no source plays sandboxed: offer "Allow pop-ups for this source" once (it doesn't change the
  setting).
- Text in all 13 locales (`frontend/src/i18n/locales`), then run `npm run i18n:check`. Arabic and
  Urdu must look right (logical CSS properties).

## TV remote first (required)

Every control works with arrows / OK / Back only: the switch is reachable from the source chips,
OK toggles it, focus stays on it after the iframe remounts, and Back still leaves the page. The
focus ring must not cover a neighbour (see `e2e/tests/focus-overlap.spec.js`).

## Tests

- Unit: `playerEvents.test.js` / a new test for the sandbox attribute and source ordering; backend
  tests for the new field and the API that exposes it.
- e2e, remote only: in `e2e/tests/watch.spec.js` (or a new `popups.spec.js`), use a fake embed page
  that calls `window.open` and `top.location = ...`. With the switch ON nothing opens and the page
  stays put; with it OFF the call goes through. Drive everything with the keyboard (arrows / Enter /
  Escape), never mouse clicks.
- Run only the related specs locally (`npx playwright test watch popups`), never the full suite.

## Finishing

- Stage files by path and check the staged names before committing: never `.env`, never the user's
  unrelated work-in-progress files, never old stashes.
- Commit locally on a branch (for example `block-popups`). Don't push or open a PR until the user
  says so.
- Write up 9.1 in ROADMAP.txt like the finished items (what was built, what was measured, the tests)
  and mark it `[x]`.
- Tell the user what to do after the deploy: the migration, updating the scout on the mini PC, and
  re-testing a few sources on the live site.

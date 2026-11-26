---
name: roadmap-item
description: Build one ROADMAP.txt item end to end (plan, code, remote-only e2e, related tests, local commit, roadmap write-up). Use when the user types /roadmap-item <number> (e.g. /roadmap-item 9.2) or asks an agent to work on a roadmap item.
---

# Build ROADMAP item $ARGUMENTS

## Before writing code

1. Read the item `$ARGUMENTS` in ROADMAP.txt, plus every earlier item it mentions, and mark it `[~]`.
   Read section 9's intro if the item is in section 9.
2. Read the code the item touches before planning. For the watch page that means
   `frontend/src/components/WatchPage.jsx` and `frontend/src/components/watch/`.
3. Write a short plan: files, data, API, and what the remote does on each new control.
   - Interactive session: show the plan to the user and wait for an OK.
   - Unattended run: put the plan in the report and go on.
   - If the item says to plan it on its own, or it is marked `[-]` (dropped), stop and say so.

## Hard rules (the user's)

- **Taurus hosts no films and shows no ads.** It only embeds other sites' players in an iframe.
  - Never build our own player, never extract or proxy streams.
  - Never sandbox the player iframe or block its pop-ups. That was tried (9.1): most players then
    refuse to play.
- **TV remote first.** Every new control works with arrows / OK / Back only.
  - Focus is never lost, hidden or covering a neighbour (`e2e/tests/focus-overlap.spec.js`).
  - Prove it with an e2e test that drives the page with the keyboard only (arrows / Enter /
    Escape), never mouse clicks.
- **Text in all 13 locales** (`frontend/src/i18n/locales`), then `npm run i18n:check`.
  - Right to left (ar, ur) must look right: use logical CSS properties.
- **AI.** Use AI only as a background job, or behind the 8.9 caps. Use TMDB data first.
- **Tests: run only the related ones**, never the whole e2e suite. For example
  `npx playwright test watch`, the frontend unit tests, and the backend tests of the touched apps.
- **Migrations.** For a model change, write the migration and run
  `python manage.py makemigrations --check --dry-run`.

## Finishing

- **Committing:**
  - Stage files by path and check the staged names before committing.
  - Never `.env`, `backend/.venv`, `node_modules`, build output, or the user's unrelated
    work-in-progress files. Never pop old stashes.
  - Commit locally only. Never push, never open a PR, never deploy, never add a git remote.
- **ROADMAP.txt:** write the item up like the finished ones (what was built, what was measured,
  the tests) and mark it `[x]`.
- **Say what the user must do after the deploy:** migrations, the scout on the mini PC, and what
  to check on the live site.

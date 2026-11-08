# Tauruss frontend

React 18 app, built with [Vite](https://vite.dev) (`vite.config.mjs`), tested with
[Vitest](https://vitest.dev).

## Commands

| Command | What it does |
| --- | --- |
| `npm start` | dev server on http://localhost:3000, reloads on save |
| `npm run build` | production build into `build/` (`BUILD_PATH` changes it), then `scripts/obfuscate.js` |
| `npm run preview` | serve the production build locally |
| `npm test` | unit tests once (`npm run test:watch`: re-run on save) |
| `npm run lint` | ESLint (`eslint.config.mjs`); a warning fails it, like in CI |
| `npm run i18n:check` | every language has every text, plural form and placeholder |

## Settings

`.env` (see `.env.example`), or the environment at build time:

| Variable | Meaning |
| --- | --- |
| `REACT_APP_API_BASE` | address of the Django API (`""` in production: same site, `/api`) |

In the code they are `import.meta.env.REACT_APP_*` (`process.env` doesn't exist with Vite).

## Layout

- `index.html`: the page shell (SEO tags for the home page, start-up splash). Django rewrites its
  tags for title / actor pages (`backend/users/seo.py`), so keep the tag shapes it looks for.
- `public/`: copied as is (icons, manifest, service worker, robots.txt).
- `src/`: files containing JSX are `.jsx`, plain modules `.js`.
- Built JS / CSS / images go to `build/static/` with a content hash in their names: nginx caches
  `/static/` for a year, `index.html` never.
- Rarely used pages (account, admin, watch, sign-up, email links) are separate files loaded on
  demand (`React.lazy` in `src/App.jsx`).

More on the tests: `docs/TESTING.md`.

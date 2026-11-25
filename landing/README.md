# Taurus landing page

A standalone static site for its own domain, separate from the app (`frontend/`): no build step,
no dependencies, nothing shared with the app at runtime.

```
index.html   the page
styles.css   the design (same palette / fonts as the app, copied on purpose)
main.js      TV-remote arrows, poster wall, typing prompt, scroll effects
emblem.svg   the logo / favicon (from frontend/src/design/brandMark.js)
```

**The app's address** is set once, in `index.html`:
`<meta name="site-url" content="https://tauruss.com" />`. Every "Visit site", "Sign in" and
"Create an account" button goes there (`/`, `/login`, `/register`). The links also carry that address
in their `href`, so they still work without JavaScript: change both when the domain changes.

**Hosting:** upload the four files to any static host (nginx, Netlify, Cloudflare Pages, S3...).

**Preview:** open `index.html` in a browser.

**Tests** (TV remote only, opened from disk, no server needed):

```
cd e2e && npx playwright test -c playwright.landing.config.js
```

// The landing page (../landing): a static site on its own domain, so its tests need no API or app
// server: the page is opened from disk.   cd e2e && npx playwright test -c playwright.landing.config.js
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './landing',
  timeout: 30_000,
  reporter: [['list']],
  use: { viewport: { width: 1280, height: 720 } }, // the tightest TV screen
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 720 } } }],
});

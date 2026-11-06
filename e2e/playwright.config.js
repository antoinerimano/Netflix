// End-to-end tests: the real app in Chromium (production build of the frontend + Django on a
// dedicated MySQL database, reset and filled by `manage.py e2e_prepare` at every start).
//   cd e2e && npm test            (needs MySQL running, like the backend dev setup)
//   npm run test:headed           (watch it)
// Ports 8101 / 3101: the usual dev servers (8000 / 3000) can keep running.
const { defineConfig, devices } = require('@playwright/test');

const API_PORT = 8101;
const WEB_PORT = 3101;
const isCI = !!process.env.CI;

module.exports = defineConfig({
  testDir: './tests',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // one shared database
  workers: 1,
  retries: isCI ? 1 : 0,
  forbidOnly: isCI,
  reporter: isCI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    viewport: { width: 1920, height: 1080 }, // a TV
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1920, height: 1080 } } }],
  webServer: [
    {
      // reset + seed the e2e database, then serve the API
      command: `python manage.py e2e_prepare && python manage.py runserver 127.0.0.1:${API_PORT} --noreload`,
      cwd: '../backend',
      url: `http://127.0.0.1:${API_PORT}/api/providers/`,
      timeout: 300_000,
      reuseExistingServer: !isCI,
      env: {
        DB_NAME: process.env.E2E_DB_NAME || 'taurus_e2e',
        DJANGO_DEBUG: '1',
        DJANGO_ALLOWED_HOSTS: 'localhost,127.0.0.1',
        CORS_ALLOWED_ORIGINS: `http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT}`,
        THROTTLE_AUTH_RATE: '1000/min', // every test signs in
        THROTTLE_PASSWORD_RESET_RATE: '1000/hour',
        EMAIL_BACKEND: 'django.core.mail.backends.locmem.EmailBackend',
        PYTHONIOENCODING: 'utf-8',
      },
    },
    {
      // production build (what users get), ads off: their pop-unders take over the tab
      command: `npm run build && node ../e2e/node_modules/serve/build/main.js -s build-e2e -l ${WEB_PORT} --no-clipboard`,
      cwd: '../frontend',
      url: `http://localhost:${WEB_PORT}`,
      timeout: 600_000,
      reuseExistingServer: !isCI,
      env: {
        REACT_APP_API_BASE: `http://localhost:${API_PORT}`,
        REACT_APP_DISABLE_ADS: 'true',
        BUILD_PATH: 'build-e2e', // vite.config.mjs
      },
    },
  ],
});

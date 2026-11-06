// Vite: dev server (npm start), production build (npm run build), tests (npm test, Vitest).
//
// Kept from the Create React App days so nothing else had to change:
//   - REACT_APP_* variables (.env, or the environment) reach the app as import.meta.env.REACT_APP_*
//   - BUILD_PATH picks the output folder (the e2e tests build into build-e2e)
//   - JSX lives in .js files
//   - built files go to static/js, static/css, static/media: nginx caches /static/ for a year
//     (names carry a content hash) and scripts/obfuscate.js reads static/js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  envPrefix: ['REACT_APP_', 'VITE_'],
  server: { port: 3000, open: false },
  preview: { port: 3000 },
  build: {
    outDir: process.env.BUILD_PATH || 'build',
    emptyOutDir: true,
    sourcemap: false, // the bundles are obfuscated: no maps that would undo it
    assetsDir: 'static',
    rolldownOptions: {
      output: {
        entryFileNames: 'static/js/[name]-[hash].js',
        chunkFileNames: 'static/js/[name]-[hash].js',
        assetFileNames: (asset) =>
          (asset.names || []).some((n) => n.endsWith('.css'))
            ? 'static/css/[name]-[hash][extname]'
            : 'static/media/[name]-[hash][extname]',
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.js'],
    css: false,
  },
});

/* Tauruss service worker: makes the site installable and shows a proper page when offline.
 *
 * Deliberately does NOT cache the app (index.html, JS bundles, API): everything still comes from
 * the network, so a deploy is visible right away (caching the app is how PWAs get stuck on an old
 * version). Only the offline page and its logo are kept, for when the network is gone.
 */
const OFFLINE_CACHE = "tauruss-offline-v1";
const OFFLINE_URL = "/offline.html";
const OFFLINE_ASSETS = [OFFLINE_URL, "/logo/favicon-192x192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(OFFLINE_CACHE).then((cache) => cache.addAll(OFFLINE_ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== OFFLINE_CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  // only page loads: if the network fails, show the offline page instead of the browser error
  if (event.request.mode !== "navigate") return;
  event.respondWith(
    fetch(event.request).catch(() => caches.match(OFFLINE_URL, { cacheName: OFFLINE_CACHE }))
  );
});

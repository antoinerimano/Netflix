// src/utils/watchRegion.js
// The visitor's country for the streaming services ("On Netflix" home rows, the browse pages'
// service filter, ROADMAP 9.4): the first browser language with a region ("fr-CA" -> "CA").
// "" when none says one: the server then takes the profile's language region (fr -> FR), else US
// (backend users/watch_services.py request_region).
const TAG = /^[a-z]{2,3}(?:-[a-z]{4})?-([a-z]{2})(?:-|$)/i;

export function watchRegion(languages = typeof navigator !== 'undefined' ? navigator.languages || [navigator.language] : []) {
  for (const tag of languages || []) {
    const m = TAG.exec(String(tag || '').replace(/_/g, '-'));
    if (m) return m[1].toUpperCase();
  }
  return '';
}

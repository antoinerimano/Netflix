// Which source the watch page tries first, and which next when one doesn't play (ROADMAP 2.1 / 9.2).
// Pure helpers, tested in sourceOrder.test.js.

/**
 * Every source of this title, in the order the page tries them:
 *   1. what worked before: the source that last played this title (any device of this profile), the
 *      one picked here last, the one that last played for this profile;
 *   2. the server's order (down last, then what plays most for everyone / in the scout's nightly test);
 *      for an anime (prefs.anime, ROADMAP 9.5), the sources the scout saw miss its anime episodes
 *      (animeMiss: wrong episode numbering, no anime catalog) come after the others;
 *   3. the sources whose last try on this title didn't play;
 *   4. the ones our health check couldn't reach.
 * providers: [{ key, down, animeMiss }] (buildProviderLinks);
 * prefs: { title, saved, profile, failed: [key], anime: bool }.
 */
export function orderSources(providers, prefs = {}) {
  const byKey = new Map((providers || []).map((p) => [p.key, p]));
  const failed = new Set(prefs.failed || []);
  const preferred = [prefs.title, prefs.saved, prefs.profile].filter((k) => k && byKey.has(k) && !failed.has(k));
  const keys = [...new Set([...preferred, ...byKey.keys()])];
  const group = (k) => {
    if (preferred.includes(k)) return 0; // worked before: even if the health check missed it
    if (failed.has(k)) return byKey.get(k).down ? 3 : 2;
    if (byKey.get(k).down) return 3;
    return prefs.anime && byKey.get(k).animeMiss ? 1.5 : 1;
  };
  // a stable sort: the order inside each group stays the server's
  return keys.map((k, i) => [group(k), i, k]).sort((a, b) => a[0] - b[0] || a[1] - b[1]).map(([, , k]) => k);
}

/** The next source to try after `current`: the first in `order` not tried yet on this page, or null. */
export function nextSource(order, current, tried) {
  return (order || []).find((k) => k !== current && !tried.has(k)) || null;
}

/** Any message from one of the players we know (CineSrc, VidCore, Videasy), even "ready" / "pause". */
export function isPlayerMessage(raw) {
  let type = raw && typeof raw === "object" ? raw.type : null;
  if (typeof raw === "string") {
    if (raw.startsWith("vidcore:")) return true;
    try {
      type = JSON.parse(raw)?.type;
    } catch {
      return false;
    }
  }
  return typeof type === "string" && (type === "PLAYER_EVENT" || /^(cinesrc|vidcore):/.test(type));
}

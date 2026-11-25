// "Block pop-ups" (ROADMAP 9.1): the watch page's pure helpers (no React). Tested in popups.test.js.
//
// Taurus runs no ads; the pop-ups / redirects come from the embedded players. With the switch on
// (the profile's block_popups, on by default) the player's iframe is sandboxed WITHOUT
// allow-popups and allow-top-navigation*: it can't open tabs or send the page elsewhere. Some
// embeds refuse to play sandboxed: the provider scout records it (Provider.sandbox_ok), and a
// sandboxed source that fails by itself on the watch page is remembered here (learned failures).

// no allow-popups, no allow-top-navigation(-by-user-activation / -to-custom-protocols)
export const SANDBOX = "allow-scripts allow-same-origin allow-forms allow-presentation";
// a frame on our own origin must never get allow-scripts + allow-same-origin together (it could
// remove its own sandbox): it loses allow-same-origin
const SANDBOX_SAME_ORIGIN = "allow-scripts allow-forms allow-presentation";

/**
 * The iframe's sandbox attribute for this player URL, or undefined (no sandbox).
 * block: "Block pop-ups" is on (and not lifted for this source).
 */
export function sandboxFor(url, block, pageOrigin = typeof window !== "undefined" ? window.location.origin : "") {
  if (!block || !url) return undefined;
  let origin;
  try {
    origin = new URL(url, pageOrigin || undefined).origin;
  } catch {
    return SANDBOX_SAME_ORIGIN; // can't tell where it goes: the safe one
  }
  return origin === pageOrigin ? SANDBOX_SAME_ORIGIN : SANDBOX;
}

/**
 * Sources in the order the watch page shows them. Block on: the ones that don't play sandboxed
 * (scout said "no", or failed sandboxed here: learned) go last, marked popupRisk; the ones the
 * scout saw play sandboxed get noPopups (the "No pop-ups" chip). Block off: as they came, no marks.
 * Stable: the server's order (success rates, priority) is kept inside each group.
 */
export function orderSources(providers, { block, learned } = {}) {
  const list = providers || [];
  if (!block) return list.map((p) => ({ ...p, popupRisk: false, noPopups: false }));
  const failed = learned || new Set();
  const marked = list.map((p) => {
    const risk = p.sandboxOk === "no" || failed.has(p.key);
    return { ...p, popupRisk: risk, noPopups: !risk && p.sandboxOk === "yes" };
  });
  return [...marked.filter((p) => !p.popupRisk), ...marked.filter((p) => p.popupRisk)];
}

/**
 * Block on, and the viewer has nothing that plays sandboxed left: offer "Allow pop-ups for this
 * source" (once per source, for this page only; the setting doesn't change).
 * current: the selected source (from orderSources); failed: sources that failed by themselves here.
 */
export function shouldOfferAllow({ block, current, sources, failed, allowed }) {
  if (!block || !current || allowed?.has(current.key)) return false;
  if (current.popupRisk) return true; // only risky ones were left (or the viewer chose one)
  const done = failed || new Set();
  // the current one failed by itself and no other source would play sandboxed
  return done.has(current.key) && !(sources || []).some((p) => !p.popupRisk && !p.down && !done.has(p.key));
}

// ---------- learned failures: a sandboxed source that failed by itself, per profile ----------
const LEARN_KEY = (profileId) => `sandboxFailed_${profileId || "anon"}`;
export const LEARN_TTL_MS = 14 * 24 * 3600 * 1000; // players change: tried sandboxed again after 2 weeks

export function readSandboxFailures(profileId, now = Date.now()) {
  try {
    const raw = JSON.parse(localStorage.getItem(LEARN_KEY(profileId)) || "{}");
    return new Set(Object.keys(raw).filter((k) => now - Number(raw[k]) < LEARN_TTL_MS));
  } catch {
    return new Set();
  }
}

export function rememberSandboxFailure(profileId, key, now = Date.now()) {
  if (!key) return;
  try {
    const raw = JSON.parse(localStorage.getItem(LEARN_KEY(profileId)) || "{}");
    const kept = Object.fromEntries(Object.entries(raw).filter(([, t]) => now - Number(t) < LEARN_TTL_MS));
    localStorage.setItem(LEARN_KEY(profileId), JSON.stringify({ ...kept, [key]: now }));
  } catch {
    /* storage full / blocked: only this page knows */
  }
}

// ---------- the setting: the active profile's block_popups ----------
export function readBlockPopups() {
  try {
    const p = JSON.parse(localStorage.getItem("activeProfile") || "null");
    return p?.block_popups !== false; // on by default (and for profiles saved before 9.1)
  } catch {
    return true;
  }
}

/** The copy the app keeps of the active profile (next start, profile switch) */
export function storeBlockPopups(on) {
  try {
    const p = JSON.parse(localStorage.getItem("activeProfile") || "null");
    if (p) localStorage.setItem("activeProfile", JSON.stringify({ ...p, block_popups: !!on }));
  } catch {
    /* ignore */
  }
}

// src/api/problemsApi.js
// "Playback problem?" on the watch page and the public status page (backend reco/problems.py,
// ROADMAP 9.8).
import api from "./http";

export const PROBLEMS = ["not_playing", "wrong_title", "no_sound", "out_of_sync", "no_subtitles"];

// what's wrong with a source on a title / episode (signed out too: no profile)
export async function reportProblem({ profileId, titleId, provider, problem, season, episode }) {
  const profile = profileId && profileId !== "anon" ? profileId : undefined;
  const res = await api.post("/playback/report/", {
    provider,
    problem,
    title_id: Number(titleId),
    ...(season ? { season, episode } : {}),
    ...(profile ? { profile_id: Number(profile) } : {}),
  });
  return res.data;
}

// { ok, generated_at, sources: [{ key, label, domain, state, checked_at, scout, plays_24h, played_share_24h, reports_24h }], counts }
export async function fetchStatus() {
  const res = await api.get("/status/", { timeout: 15000 });
  return res.data;
}

/**
 * Can this browser reach a source's site? A no-cors request: it resolves when the server answers
 * at all (any status, the answer can't be read), it fails on a DNS / connection / blocked error
 * (a network filter, an ad blocker, the site down). -> true / false, false after `timeoutMs`.
 */
export async function reachable(domain, { timeoutMs = 8000, fetchImpl = globalThis.fetch } = {}) {
  if (!domain || !fetchImpl) return false;
  const ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
  const timer = setTimeout(() => ctrl?.abort(), timeoutMs);
  try {
    await fetchImpl(`${domain.replace(/\/+$/, "")}/`, {
      mode: "no-cors",
      cache: "no-store",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      signal: ctrl?.signal,
    });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * The status page's answer to "is it down for me or everyone?" from the server's view of each
 * source (state) and this browser's test (reach: { key: true | false }):
 *   "everyone"  the source is down for everyone (our checks)
 *   "you"       it works for others but this browser can't reach it (network, blocker...)
 *   "ok"        reachable from here and working
 *   null        not tested from here yet
 */
export function whoIsAffected(source, reach) {
  if (source.state === "down") return "everyone";
  const r = reach?.[source.key];
  if (r === undefined) return null;
  return r ? "ok" : "you";
}

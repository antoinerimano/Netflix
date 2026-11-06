// The watch page's pure helpers (no React): saved source preferences, URLs, the players'
// postMessage events, numbers from the address. Tested in playerEvents.test.js.

// sources saved by older versions used the DB column names
export const LEGACY_SOURCE_KEYS = {
  video_url: "vidking",
  movie_link2: "videasy", episode_link2: "videasy",
  movie_link3: "vidsrc", episode_link3: "vidsrc",
  movie_link4: "vidfast", episode_link4: "vidfast",
  movie_link5: "vidplus", episode_link5: "vidplus",
  movie_link6: "111movies", episode_link6: "111movies",
};

export function storageKey(profileId, titleId) {
  return `watchprefs_${profileId || "anon"}_${titleId}`;
}

export function normalizeUrl(u) {
  const s = String(u || "").trim();
  if (!s) return "";
  if (!/^https?:\/\//i.test(s) && /^[\w-]+\.[\w.-]+/i.test(s)) return `https://${s}`;
  return s;
}

export function isDirectVideo(url) {
  return /\.(m3u8|mp4)(\?|#|$)/i.test(url || "");
}

// Smart playback timings
export const SOURCE_LOAD_TIMEOUT_MS = 15000; // page never loaded: switch to the next source by itself
export const SOURCE_SILENT_TIMEOUT_MS = 20000; // loaded, but a player that reports playback stayed silent: offer the next one
export const SOURCE_STAYED_MS = 120000; // stayed this long on a source: it works
export const SOURCE_QUICK_LEAVE_MS = 60000; // switched away sooner, without playback: it didn't work

// Normalize the players' postMessage events (formats from their docs) to
// { position?, duration?, playing?, ended?, flush?, season?, episode? } (seconds), or null.
// playing = proof the source actually plays (smart playback).
export function readPlayerEvent(raw) {
  let data = raw;
  if (typeof data === "string") {
    if (data.startsWith("vidcore:")) data = { type: data };
    else {
      try {
        data = JSON.parse(data);
      } catch {
        return null;
      }
    }
  }
  if (!data || typeof data !== "object" || typeof data.type !== "string") return null;
  const num = (v) => (v === null || v === undefined || v === "" ? NaN : Number(v));

  // Videasy: { type: "PLAYER_EVENT", data: { player_status, player_progress, player_duration, player_info } }
  if (data.type === "PLAYER_EVENT") {
    let d = data.data;
    if (typeof d === "string") {
      try {
        d = JSON.parse(d);
      } catch {
        return null;
      }
    }
    if (!d) return null;
    const status = String(d.player_status || "");
    return {
      position: num(d.player_progress),
      duration: num(d.player_duration),
      playing: status === "playing" || Number(d.player_progress) > 0,
      ended: status === "completed",
      flush: status === "paused" || status === "seeked",
      season: num(d.player_info?.season) || undefined,
      episode: num(d.player_info?.episode) || undefined,
    };
  }

  // CineSrc: { type: "cinesrc:timeupdate", currentTime, duration }, cinesrc:ended, cinesrc:nextepisode ...
  if (data.type.startsWith("cinesrc:")) {
    const kind = data.type.slice("cinesrc:".length);
    if (kind === "timeupdate" || kind === "seeked") {
      const position = num(data.currentTime);
      return { position, duration: num(data.duration), playing: position > 0, flush: kind === "seeked" };
    }
    if (kind === "play") return { playing: true };
    if (kind === "pause") return { flush: true };
    if (kind === "ended") return { ended: true };
    if (kind === "nextepisode") return { season: num(data.season), episode: num(data.episode) };
    return null;
  }

  // VidCore: only play / pause / ended, no position
  if (data.type === "vidcore:play") return { playing: true };
  if (data.type === "vidcore:ended") return { ended: true };
  return null;
}

export function readPositiveInt(search, key, fallback) {
  const v = new URLSearchParams(search).get(key);
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

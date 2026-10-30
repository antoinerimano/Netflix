// src/api/recoApi.js
import api from "./http";
import { getRecoSessionId } from "./analyticsApi";

export async function fetchHomeRecoRows(profileId) {
  const res = await api.get("/reco/home/", { params: { profileId } });
  return res.data;
}

// ---------- continue watching ----------
// Called by the watch page: remembers the last movie / episode opened for this profile.
// position / duration (seconds) and finished come from the player's events when it sends them.
export async function saveWatchProgress({
  profileId, titleId, season = null, episode = null, position = null, duration = null, finished = false,
}) {
  if (!profileId || !titleId) return;
  await api.post("/watch-progress/", {
    profile_id: Number(profileId),
    title_id: Number(titleId),
    season,
    episode,
    position,
    duration,
    finished,
  });
}

// Removes a title from the "Continue watching" row.
export async function hideWatchProgress({ profileId, titleId }) {
  if (!profileId || !titleId) return;
  await api.delete("/watch-progress/", { params: { profileId, titleId } });
}

// ---------- like / dislike / not interested ----------
export async function fetchRating({ profileId, titleId }) {
  if (!profileId || !titleId) return null;
  const res = await api.get(`/ratings/${titleId}/`, { params: { profileId } });
  return res.data?.rating ?? null; // "like" | "dislike" | null
}

// rating: "like" | "dislike" | null (null clears it)
export async function setRating({ profileId, titleId, rating }) {
  if (!profileId || !titleId) return;
  await api.put(`/ratings/${titleId}/`, { rating, session_id: getRecoSessionId() }, { params: { profileId } });
}

// Never recommend this title again to this profile.
export async function markNotInterested({ profileId, titleId, surface = "" }) {
  if (!profileId || !titleId) return;
  await api.post("/events/action/", {
    profile_id: Number(profileId),
    title_id: Number(titleId),
    action: "not_interested",
    session_id: getRecoSessionId(),
    provider: surface ? `surface:${surface}` : "",
  });
}

// ---------- smart playback ----------
// Did this source play? worked = playback reported / viewer stayed; false = left it quickly or it never loaded.
export async function reportPlayback({ profileId, titleId, provider, worked }) {
  if (!profileId || !titleId || !provider) return;
  await api.post("/playback/", { profile_id: Number(profileId), title_id: Number(titleId), provider, worked });
}

// { title, profile }: provider key that last worked for this title / for this profile (or null)
export async function fetchPreferredSource({ profileId, titleId }) {
  if (!profileId) return { title: null, profile: null };
  const res = await api.get("/playback/", { params: { profileId, titleId } });
  return res.data || { title: null, profile: null };
}

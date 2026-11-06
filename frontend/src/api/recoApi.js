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

// ---------- new episode alerts ----------
export async function fetchFollow({ profileId, titleId }) {
  if (!profileId || !titleId) return false;
  const res = await api.get(`/follows/${titleId}/`, { params: { profileId } });
  return !!res.data?.following;
}

export async function setFollow({ profileId, titleId, following }) {
  if (!profileId || !titleId) return;
  const url = `/follows/${titleId}/`;
  if (following) await api.put(url, null, { params: { profileId } });
  else await api.delete(url, { params: { profileId } });
}

// { unread, items: [{ id, title_id, show, image, season, episode, air_date, read }] }
export async function fetchNotifications(profileId) {
  if (!profileId) return { unread: 0, items: [] };
  const res = await api.get("/notifications/", { params: { profileId } });
  return res.data || { unread: 0, items: [] };
}

export async function markNotificationsRead(profileId) {
  if (!profileId) return;
  await api.post("/notifications/read/", null, { params: { profileId } });
}

// ---------- taste onboarding (backend reco/taste.py) ----------
// { titles: [{id, type, title, poster, release_year}], min_picks }: well-known titles to pick from
export async function fetchTasteTitles(profileId) {
  const res = await api.get("/taste/", { params: { profileId } });
  return res.data;
}

// The picks become likes and the home page is rebuilt from them (a few seconds).
export async function saveTaste(profileId, titleIds) {
  const res = await api.post("/taste/", { title_ids: titleIds, session_id: getRecoSessionId() }, { params: { profileId } });
  return res.data;
}

// ---------- upcoming episodes (backend reco/calendar.py) ----------
// { today, tracked, recent: [episode], upcoming: [episode], suggestions: [show] }
export async function fetchCalendar(profileId) {
  const res = await api.get("/calendar/", { params: { profileId } });
  return res.data;
}

// ---------- your year (backend reco/stats.py) ----------
// year: null = the latest year with history
export async function fetchStats(profileId, year = null) {
  const res = await api.get("/stats/", { params: { profileId, ...(year ? { year } : {}) } });
  return res.data;
}

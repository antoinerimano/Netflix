// src/api/recoApi.js
import api from "./http";

export async function fetchHomeRecoRows(profileId) {
  const res = await api.get("/reco/home/", { params: { profileId } });
  return res.data;
}

// ---------- continue watching ----------
// Called by the watch page: remembers the last movie / episode opened for this profile.
export async function saveWatchProgress({ profileId, titleId, season = null, episode = null }) {
  if (!profileId || !titleId) return;
  await api.post("/watch-progress/", {
    profile_id: Number(profileId),
    title_id: Number(titleId),
    season,
    episode,
  });
}

// Removes a title from the "Continue watching" row.
export async function hideWatchProgress({ profileId, titleId }) {
  if (!profileId || !titleId) return;
  await api.delete("/watch-progress/", { params: { profileId, titleId } });
}

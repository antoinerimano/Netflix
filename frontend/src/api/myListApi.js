// src/api/myListApi.js
// "My List", saved on the server per profile (same list on every device).
import http from "./http";

const LEGACY_KEY = (profileId) => `userList_${profileId}`; // where the browser used to keep it

// profileId -> Promise<items>, so the list page and detail pages share one request
const cache = new Map();

// One-time move of the list this browser kept before (localStorage) to the server.
async function importLegacyList(profileId) {
  const raw = localStorage.getItem(LEGACY_KEY(profileId));
  if (raw == null) return;
  let ids = [];
  try {
    ids = (JSON.parse(raw) || []).map((item) => item?.id).filter(Boolean);
  } catch {
    ids = [];
  }
  if (ids.length) {
    await http.post("/my-list/import/", { profile_id: Number(profileId), title_ids: ids });
  }
  localStorage.removeItem(LEGACY_KEY(profileId)); // only once the server has it
}

/** [{ id, type, title, poster, landscape_image, description, release_date, first_air_date, ... }], newest first */
export function fetchMyList(profileId) {
  if (!profileId) return Promise.resolve([]);
  if (!cache.has(profileId)) {
    const request = importLegacyList(profileId)
      .then(() => http.get("/my-list/", { params: { profileId } }))
      .then((res) => (Array.isArray(res.data) ? res.data : []))
      .catch((err) => {
        cache.delete(profileId); // retry next time
        throw err;
      });
    cache.set(profileId, request);
  }
  return cache.get(profileId);
}

export async function setInMyList(profileId, titleId, inList) {
  if (!profileId || !titleId) return;
  cache.delete(profileId);
  const url = `/my-list/${encodeURIComponent(titleId)}/`;
  if (inList) {
    await http.put(url, null, { params: { profileId } });
  } else {
    await http.delete(url, { params: { profileId } });
  }
}

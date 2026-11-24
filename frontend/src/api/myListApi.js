// src/api/myListApi.js
// "My List", saved on the server per profile (same list on every device).
import http from "./http";
import { currentLanguage } from "../i18n";

const LEGACY_KEY = (profileId) => `userList_${profileId}`; // where the browser used to keep it

// profile + language -> { request, at }: the list page and detail pages opened one after the other
// share one request. Kept a short while only: it was kept until the page reloaded, so the titles
// stayed in the old language and a change made on another device never showed.
const cache = new Map();
const CACHE_MS = 30 * 1000;
const cacheKey = (profileId) => `${profileId}|${currentLanguage()}`;
const forgetProfile = (profileId) => {
  for (const k of cache.keys()) if (k.startsWith(`${profileId}|`)) cache.delete(k);
};

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
  const key = cacheKey(profileId);
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_MS) return hit.request;
  const request = importLegacyList(profileId)
    .then(() => http.get("/my-list/", { params: { profileId } }))
    .then((res) => (Array.isArray(res.data) ? res.data : []))
    .catch((err) => {
      if (cache.get(key)?.request === request) cache.delete(key); // retry next time
      throw err;
    });
  cache.set(key, { request, at: Date.now() });
  return request;
}

export async function setInMyList(profileId, titleId, inList) {
  if (!profileId || !titleId) return;
  forgetProfile(profileId);
  const url = `/my-list/${encodeURIComponent(titleId)}/`;
  try {
    if (inList) {
      await http.put(url, null, { params: { profileId } });
    } else {
      await http.delete(url, { params: { profileId } });
    }
  } finally {
    // a list asked for while this change was on its way may predate it
    forgetProfile(profileId);
  }
}

// src/api/listsApi.js - lists a profile makes, and shared lists (backend reco/lists.py)
import api from "./http";

/** -> { lists: [{ id, name, description, count, is_public, share_id, covers, contains? }], max } */
export async function fetchLists(profileId, titleId = null) {
  const res = await api.get("/lists/", { params: { profileId, ...(titleId ? { titleId } : {}) } });
  return res.data;
}

export async function createList(profileId, { name, description = "", titleId = null }) {
  const res = await api.post("/lists/", { name, description, ...(titleId ? { title_id: titleId } : {}) }, { params: { profileId } });
  return res.data;
}

/** -> summary + { items: [{ title, added_at }] } */
export async function fetchList(profileId, id) {
  const res = await api.get(`/lists/${id}/`, { params: { profileId } });
  return res.data;
}

/** fields: { name?, description?, is_public? } */
export async function updateList(profileId, id, fields) {
  const res = await api.patch(`/lists/${id}/`, fields, { params: { profileId } });
  return res.data;
}

export async function deleteList(profileId, id) {
  await api.delete(`/lists/${id}/`, { params: { profileId } });
}

export async function setInList(profileId, id, titleId, inList) {
  const url = `/lists/${id}/items/${titleId}/`;
  if (inList) await api.put(url, null, { params: { profileId } });
  else await api.delete(url, { params: { profileId } });
}

/** A shared list, for anyone: { name, description, owner, count, items, updated_at } */
export async function fetchPublicList(shareId) {
  const res = await api.get(`/public-lists/${shareId}/`);
  return res.data;
}

/** A private copy of a shared list in the viewer's lists -> its summary */
export async function copyPublicList(profileId, shareId) {
  const res = await api.post(`/public-lists/${shareId}/copy/`, {}, { params: { profileId } });
  return res.data;
}

/** The address of a shared list, as people see and type it */
export function shareUrl(shareId) {
  return `${window.location.origin}/l/${shareId}`;
}

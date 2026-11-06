// src/api/historyApi.js - a profile's watch history (backend reco/history.py)
import api from "./http";

/** -> { paused, items: [{ id, watched_at, season, episode, episode_info, title }], next: page | null } */
export async function fetchHistory(profileId, page = 1) {
  const res = await api.get("/history/", { params: { profileId, page } });
  return res.data;
}

/** -> { ok, title_forgotten }: the title's last entry also clears what watching it left behind */
export async function removeHistoryItem(profileId, id) {
  const res = await api.delete(`/history/${id}/`, { params: { profileId } });
  return res.data;
}

export async function clearHistory(profileId) {
  const res = await api.delete("/history/", { params: { profileId } });
  return res.data;
}

export async function setHistoryPaused(profileId, paused) {
  const res = await api.post("/history/pause/", { paused }, { params: { profileId } });
  return !!res.data?.paused;
}

/** Saves the history as a CSV file (the browser's download). */
export async function downloadHistory(profileId) {
  const res = await api.get("/history/export/", { params: { profileId }, responseType: "blob" });
  const match = /filename="([^"]+)"/.exec(res.headers?.["content-disposition"] || "");
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = match ? match[1] : "watch-history.csv";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

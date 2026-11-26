// src/api/importApi.js - history import from Letterboxd / IMDb / MyAnimeList export files, or a
// public AniList list (backend reco/imports.py)
import api from "./http";

/** Letterboxd .zip / .csv, IMDb .csv -> { liked, disliked, watched, listed, matched, not_found, not_found_examples, ... } */
export async function importFiles(profileId, files) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await api.post("/import/files/", form, { params: { profileId } });
  return res.data;
}

/** A public AniList anime list by user name (or profile link) -> the same summary as importFiles */
export async function importAniList(profileId, username) {
  const res = await api.post("/import/anilist/", { username }, { params: { profileId } });
  return res.data;
}

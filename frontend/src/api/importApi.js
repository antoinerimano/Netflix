// src/api/importApi.js - history import from Letterboxd / IMDb export files (backend reco/imports.py)
import api from "./http";

/** Letterboxd .zip / .csv, IMDb .csv -> { liked, disliked, watched, listed, matched, not_found, not_found_examples, ... } */
export async function importFiles(profileId, files) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  const res = await api.post("/import/files/", form, { params: { profileId } });
  return res.data;
}

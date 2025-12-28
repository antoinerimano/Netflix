// src/api/recoApi.js
import api from "./http";

export async function fetchHomeRecoRows(profileId) {
  const res = await api.get("/reco/home/", { params: { profileId } });
  return res.data;
}

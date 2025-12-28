// src/api/analyticsApi.js
import axios from "axios";

const API_BASE = process.env.REACT_APP_API_BASE;

// src/api/analyticsConsts.js

export const SURFACES = {
  HOME: "home",
  HERO: "hero",
  SEARCH: "search",
  MOVIES: "movies",
  TVSHOWS: "tvshows",
  MY_LIST: "my_list",
  DETAIL: "detail",
};

export const PROVIDERS = {
  HOME_YOU_MIGHT_LIKE: "home_you_might_like",
  HOME_TRENDING_CA: "home_trending_ca",
  HOME_NEW_THIS_WEEK: "home_new_this_week",
  HOME_TOP_BY_GENRE: "home_top_by_genre",

  HERO_MORE_INFO: "hero_more_info",
  HERO_PLAY: "hero_play",

  SEARCH_RESULT: "search_result",

  MOVIES_GRID: "movies_grid",
  TV_GRID: "tv_grid",

  LIST_GRID: "my_list_grid",

  DETAIL_ADD_TO_LIST: "detail_add_to_list",
  DETAIL_REMOVE_FROM_LIST: "detail_remove_from_list",

  OUTBOUND: "outbound",
};


const API = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 20000,
});

// --- JWT header auto (comme ton titlesApi.js) ---
API.interceptors.request.use((config) => {
  const token = localStorage.getItem("access"); // adapte si ton token a un autre nom
  if (token) config.headers.Authorization = `Bearer ${token}`;
  config.headers["Content-Type"] = "application/json";
  return config;
});

// --- session id ---
const SESSION_KEY = "reco_session_id";
export function getRecoSessionId() {
  let sid = localStorage.getItem(SESSION_KEY);
  if (!sid) {
    sid = `${Date.now()}_${Math.random().toString(16).slice(2)}`;
    localStorage.setItem(SESSION_KEY, sid);
  }
  return sid;
}

function getActiveProfileId() {
  const v = localStorage.getItem("activeProfileId");
  if (!v) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * MUST MATCH BACKEND:
 * POST /api/events/impressions/
 * body = { items: [ {profile_id, session_id, title_id, row_type, position, country, device}, ... ] }
 */
export async function logImpressions({ items, surface, row_type, device = "", country = "" }) {
  if (!Array.isArray(items) || items.length === 0) return;

  const profile_id = getActiveProfileId();
  if (!profile_id) return; // sinon backend 400

  const session_id = getRecoSessionId();

  const payloadItems = items.map((it) => ({
    profile_id,
    session_id,
    title_id: Number(it.title_id ?? it.id),
    row_type: String(it.row_type ?? row_type ?? surface ?? ""),
    position: Number.isFinite(Number(it.position)) ? Number(it.position) : 0,
    device,
    country,
  }));

  return API.post("/events/impressions/", { items: payloadItems });
}

/**
 * MUST MATCH BACKEND:
 * POST /api/events/action/
 * body = { profile_id, title_id, action, session_id, provider? }
 */
async function _postAction({ title_id, action, session_id, provider = "" }) {
  const profile_id = getActiveProfileId();
  if (!profile_id) return; // sinon backend 400/401 depending

  return API.post("/events/action/", {
    profile_id,
    title_id: Number(title_id),
    action: String(action),
    session_id,
    provider: provider || "",
  });
}

// ✅ KEEP SAME NAME
export function logTitleClick({ title_id, surface, position, row_title }) {
  const provider = [
    row_title ? `row:${row_title}` : "",
    typeof position === "number" ? `pos:${position}` : "",
    surface ? `surface:${surface}` : "",
  ]
    .filter(Boolean)
    .join("|");

  return _postAction({
    title_id,
    action: "click",
    session_id: getRecoSessionId(),
    provider,
  });
}

export function logOutboundClickBeacon({ title_id, surface, provider, url }) {
  const profile_id = getActiveProfileId();
  if (!profile_id) return false;

  const token = localStorage.getItem("access"); // same token
  const payload = {
    profile_id,
    title_id: Number(title_id),
    action: "outbound",
    session_id: getRecoSessionId(),
    provider: [
      provider ? `provider:${provider}` : "",
      surface ? `surface:${surface}` : "",
      url ? `url:${url}` : "",
    ]
      .filter(Boolean)
      .join("|"),
  };

  // Use fetch keepalive because we need Authorization header
  try {
    fetch(`${API_BASE}/api/events/action/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      keepalive: true,
    });
    return true;
  } catch {
    return false;
  }
}


// ✅ KEEP SAME NAME IF YOU ALREADY USE IT
// With JWT, we must use fetch keepalive (sendBeacon can't send Authorization header)
export function logActionBeacon({ title_id, action, surface = "", provider = "" }) {
  const profile_id = getActiveProfileId();
  if (!profile_id) return false;

  const token = localStorage.getItem("access");
  const payload = {
    profile_id,
    title_id: Number(title_id),
    action: String(action),
    session_id: getRecoSessionId(),
    provider: [
      provider ? String(provider) : "",
      surface ? `surface:${surface}` : "",
    ]
      .filter(Boolean)
      .join("|"),
  };

  try {
    fetch(`${API_BASE}/api/events/action/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(payload),
      keepalive: true,
    });
    return true;
  } catch {
    return false;
  }
}


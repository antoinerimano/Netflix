// src/api/http.js
import axios from "axios";
import { currentLanguage } from "../i18n";

const API_BASE = process.env.REACT_APP_API_BASE;

// ✅ Base: {API_BASE}/api
const http = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 200000,
  withCredentials: false,
});

http.interceptors.request.use((config) => {
  const url = config.url || "";

  // the server answers in the app's language: messages, emails, titles and synopses
  config.headers["Accept-Language"] = currentLanguage();

  const isPublic =
    url.includes("/users/login/") ||
    url.includes("/users/register/") ||
    url.includes("/token/") ||
    url.includes("/password-reset");

  if (isPublic) {
    delete config.headers.Authorization;
    return config;
  }

  const token = localStorage.getItem("access");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  // active profile: the backend applies its age limit (Kids profile) to every title it returns
  const profileId = localStorage.getItem("activeProfileId");
  if (profileId) {
    config.headers["X-Profile-Id"] = profileId;
  }

  return config;
});


function isJwtInvalidOrExpired(error) {
  const status = error?.response?.status;
  const data = error?.response?.data;
  if (status !== 401) return false;

  if (data?.code === "token_not_valid") return true;

  const detail = (data?.detail || "").toLowerCase();
  return detail.includes("token") && (detail.includes("invalid") || detail.includes("expired"));
}

// one refresh at a time, shared by every request that hit a 401 meanwhile
let refreshPromise = null;

function refreshAccessToken() {
  if (!refreshPromise) {
    const refresh = localStorage.getItem("refresh");
    refreshPromise = (refresh
      ? axios.post(`${API_BASE}/api/token/refresh/`, { refresh })
      : Promise.reject(new Error("no refresh token"))
    )
      .then(({ data }) => {
        localStorage.setItem("access", data.access);
        // ROTATE_REFRESH_TOKENS is on: the old refresh token is now blacklisted
        if (data.refresh) localStorage.setItem("refresh", data.refresh);
        return data.access;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

http.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error?.config;
    if (isJwtInvalidOrExpired(error) && original && !original._retried) {
      original._retried = true;
      try {
        const access = await refreshAccessToken();
        original.headers.Authorization = `Bearer ${access}`;
        return http(original);
      } catch {
        // refresh token expired or revoked: fall through to logout
      }
    }

    if (isJwtInvalidOrExpired(error)) {
      localStorage.removeItem("access");
      localStorage.removeItem("refresh");
      localStorage.removeItem("activeProfileId");

      // ✅ aussi nettoyer ces items (tu les set dans Login.js)
      localStorage.removeItem("userId");
      localStorage.removeItem("user");
      localStorage.removeItem("isStaff");

      if (window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
      return;
    }
    return Promise.reject(error);
  }
);

export default http;

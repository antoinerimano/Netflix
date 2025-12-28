// src/api/http.js
import axios from "axios";

const API_BASE = process.env.REACT_APP_API_BASE;

// ✅ Base: {API_BASE}/api
const http = axios.create({
  baseURL: `${API_BASE}/api`,
  timeout: 200000,
  withCredentials: false,
});

http.interceptors.request.use((config) => {
  const token = localStorage.getItem("access");
  if (token) config.headers.Authorization = `Bearer ${token}`;
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

http.interceptors.response.use(
  (res) => res,
  (error) => {
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

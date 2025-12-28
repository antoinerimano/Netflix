// ProtectedRoute.js
import React from "react";
import { Navigate, useLocation } from "react-router-dom";

function isJwtExpired(token) {
  try {
    const parts = String(token).split(".");
    if (parts.length !== 3) return false; // pas un JWT => on ne peut pas vérifier
    const payload = JSON.parse(atob(parts[1].replace(/-/g, "+").replace(/_/g, "/")));
    const exp = Number(payload?.exp);
    if (!Number.isFinite(exp)) return false;
    const now = Math.floor(Date.now() / 1000);
    return exp <= now;
  } catch {
    return false;
  }
}

export default function ProtectedRoute({ children }) {
  const location = useLocation();

  const token =
    localStorage.getItem("access_token") ||
    localStorage.getItem("token") ||
      localStorage.getItem("access");  

  const pid = localStorage.getItem("activeProfileId") || "";

  // ✅ règles
  const hasToken = Boolean(token);
  const hasProfile = Boolean(pid); // enlève ça si tu veux juste token
  const expired = hasToken ? isJwtExpired(token) : true;

  if (!hasToken || expired || !hasProfile) {

    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
}

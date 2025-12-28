import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { fetchUserData } from "./api/userApi"; // ⬅️ use your API wrapper

function getToken()      { return localStorage.getItem("access") || null; }
function getUserId()     { return localStorage.getItem("userId") || null; }
function cachedIsStaff() {
  // Fast path: either the simple flag or a cached user object
  if (localStorage.getItem("isStaff") === "1") return true;
  try {
    const u = JSON.parse(localStorage.getItem("user") || "null");
    return !!u?.is_staff;
  } catch {
    return false;
  }
}

export default function ProtectedStaffRoute({ children, fallback = null }) {
  const [status, setStatus] = useState("checking"); // "checking" | "allowed" | "blocked"
  const loc = useLocation();

  useEffect(() => {
    (async () => {
      const token  = getToken();
      const userId = getUserId();

      // Must be logged-in
      if (!token || !userId) return setStatus("blocked");

      // Instant allow if we already know they're staff
      if (cachedIsStaff()) return setStatus("allowed");

      // Otherwise, confirm with backend using your userApi
      try {
        const user = await fetchUserData(userId);  // ← calls /api/users/:id/ (with auth header)
        if (user?.is_staff) {
          // cache for next time
          try {
            localStorage.setItem("isStaff", "1");
            localStorage.setItem("user", JSON.stringify(user));
          } catch {}
          return setStatus("allowed");
        }
      } catch (e) {
        // ignore, fall through to blocked
      }
      setStatus("blocked");
    })();
  }, []);

  if (status === "checking") {
    return fallback ?? <div style={{ padding: 24 }}>Checking permissions…</div>;
  }
  if (status === "blocked") {
    // Send them to login and remember where they were going
    return <Navigate to="/login" replace state={{ from: loc }} />;
  }
  return children;
}

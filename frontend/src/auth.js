// Reads your JWT and (optionally) a cached user object.
// Adjust the /api/users/me/ endpoint if yours differs.

export function getAccessToken() {
  return localStorage.getItem("access") || null;
}

export function getCachedUser() {
  try {
    const raw = localStorage.getItem("user");
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export async function fetchMeFromAPI() {
  const token = getAccessToken();
  if (!token) return null;

  const res = await fetch("/api/users/me/", {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) return null;
  return await res.json(); // should include { is_staff: boolean }
}

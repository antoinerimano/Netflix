// src/utils/session.js
// Signing out, by the button or because the session expired (api/http.js): everything this
// browser kept about the account goes, the profile's look too (the sign-in page has the app's
// own look, and the next account must not start with the previous profile's colors).
import { DEFAULT_APPEARANCE, setAppearance } from '../design/theme';

const SESSION_KEYS = ['access', 'refresh', 'userId', 'user', 'isStaff', 'activeProfileId', 'activeProfile'];

export function clearSession() {
  SESSION_KEYS.forEach((k) => {
    try {
      localStorage.removeItem(k);
    } catch {
      /* private mode */
    }
  });
  setAppearance(DEFAULT_APPEARANCE);
}

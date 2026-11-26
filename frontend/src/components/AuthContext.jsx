import React, { createContext, useState, useEffect } from 'react';
import { fetchUserProfile, fetchUserProfiles } from '../api/userApi';
import { setActiveProfile } from '../utils/activeProfile';
import { setAppearance } from '../design/theme';
import { clearSession } from '../utils/session';

export const AuthContext = createContext();

export const AuthProvider = ({ children }) => {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [activeProfileId, setActiveProfileId] = useState(
    localStorage.getItem('activeProfileId') || null
  );

  useEffect(() => {
    const token = localStorage.getItem('access');
    setIsAuthenticated(!!token);

    // bootstrap active profile on app load if logged in
    (async () => {
      if (!token) return;

      const existing = localStorage.getItem('activeProfileId');
      if (existing) {
        setActiveProfileId(existing);
        // its look may have changed on another device (Appearance page): take the saved one
        const uid = localStorage.getItem('userId');
        const lookBefore = localStorage.getItem('appearance');
        if (uid) {
          fetchUserProfile(uid, existing)
            .then((p) => {
              if (localStorage.getItem('activeProfileId') !== existing || !p) return;
              // picked on this device while the request was on its way (Appearance page): that
              // choice is newer than the answer, keep it (the page saves it on the profile)
              if (localStorage.getItem('appearance') !== lookBefore) {
                let mine = null;
                try {
                  mine = JSON.parse(localStorage.getItem('activeProfile') || 'null')?.appearance;
                } catch {
                  /* unreadable copy: the server's */
                }
                localStorage.setItem('activeProfile', JSON.stringify(mine ? { ...p, appearance: mine } : p));
                return;
              }
              localStorage.setItem('activeProfile', JSON.stringify(p));
              setAppearance(p.appearance);
            })
            .catch(() => {});
        }
        return;
      }

      const userId = localStorage.getItem('userId');
      if (!userId) return;

      try {
        const resProfiles = await fetchUserProfiles(userId);
        const profiles = Array.isArray(resProfiles) ? resProfiles : (resProfiles?.profiles || []);

        if (profiles.length) {
          setActiveProfile(profiles[0]); // also switches to the profile's language
          setActiveProfileId(String(profiles[0].id));
        }
      } catch (e) {
        // laisse activeProfileId à null si erreur
      }
    })();
  }, []);

  const logout = () => {
    clearSession(); // the profile's look too: the sign-in page has the app's own look
    setActiveProfileId(null);
    setIsAuthenticated(false);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, setIsAuthenticated, activeProfileId, setActiveProfileId, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

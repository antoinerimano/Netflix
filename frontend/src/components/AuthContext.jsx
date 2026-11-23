import React, { createContext, useState, useEffect } from 'react';
import { fetchUserProfile, fetchUserProfiles } from '../api/userApi';
import { setActiveProfile } from '../utils/activeProfile';
import { DEFAULT_APPEARANCE, setAppearance } from '../design/theme';

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
        if (uid) {
          fetchUserProfile(uid, existing)
            .then((p) => {
              if (localStorage.getItem('activeProfileId') !== existing || !p) return;
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
    localStorage.removeItem('access');
    localStorage.removeItem('refresh');
    localStorage.removeItem('userId');
    localStorage.removeItem('user');
    localStorage.removeItem('isStaff');
    localStorage.removeItem('activeProfileId');
    localStorage.removeItem('activeProfile');
    setAppearance(DEFAULT_APPEARANCE); // the sign-in page: the app's own look
    setActiveProfileId(null);
    setIsAuthenticated(false);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, setIsAuthenticated, activeProfileId, setActiveProfileId, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

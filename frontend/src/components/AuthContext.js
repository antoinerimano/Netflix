import React, { createContext, useState, useEffect } from 'react';
import { fetchUserProfiles } from '../api/userApi';
import { setActiveProfile } from '../utils/activeProfile';

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
    setActiveProfileId(null);
    setIsAuthenticated(false);
  };

  return (
    <AuthContext.Provider value={{ isAuthenticated, setIsAuthenticated, activeProfileId, setActiveProfileId, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

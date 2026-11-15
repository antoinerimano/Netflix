// src/api/visitsApi.js
// Site visitors for the admin dashboard (backend reco/visits.py): which page the app shows, and
// a ping every minute while its tab is visible ("on the site now").
// Private: a random id kept in this browser (no cookie, nothing about the person), and nothing
// at all when the browser asks not to be tracked (Global Privacy Control / Do Not Track).
import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import http from './http';
import { getRecoSessionId } from './analyticsApi';

const VISITOR_KEY = 'visitorId';
export const PING_MS = 60 * 1000;
let firstPage = true;

export function trackingAllowed(nav = typeof navigator !== 'undefined' ? navigator : {}) {
  if (nav.globalPrivacyControl === true) return false;
  return !['1', 'yes'].includes(String(nav.doNotTrack ?? (typeof window !== 'undefined' ? window.doNotTrack : '')));
}

const uuid = () => {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  // older TV browsers: a v4 UUID by hand
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
};

export function getVisitorId() {
  try {
    let id = localStorage.getItem(VISITOR_KEY);
    if (!id) {
      id = uuid();
      localStorage.setItem(VISITOR_KEY, id);
    }
    return id;
  } catch {
    return uuid(); // storage blocked: counted as a new visitor each time
  }
}

export function sendVisit(kind, path, referrer = '') {
  if (!trackingAllowed()) return Promise.resolve();
  return http
    .post('/events/visit/', {
      visitor_id: getVisitorId(),
      session_id: getRecoSessionId(),
      kind,
      path,
      referrer,
    })
    .catch(() => {}); // never in the way of the app
}

/** App.jsx: a page view at every page change, a ping every minute while the tab is visible */
export function useVisitTracking() {
  const { pathname } = useLocation();

  useEffect(() => {
    // the site that sent the visitor: only on the first page (afterwards it's the app itself)
    const referrer = firstPage ? document.referrer : '';
    firstPage = false;
    sendVisit('view', pathname, referrer);
  }, [pathname]);

  useEffect(() => {
    const ping = () => {
      if (document.visibilityState === 'visible') sendVisit('ping', window.location.pathname);
    };
    const timer = setInterval(ping, PING_MS);
    document.addEventListener('visibilitychange', ping);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', ping);
    };
  }, []);
}

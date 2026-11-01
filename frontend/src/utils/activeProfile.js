// src/utils/activeProfile.js
// The profile in use (localStorage: the API sends it as X-Profile-Id). Changing it tells the app
// ("activeProfileChanged"): App remounts the pages for the new profile, no full reload.
// Each profile has its language (language_preference): the app switches to it with the profile.
import { setLanguage } from '../i18n';

export function getActiveProfileId() {
  return localStorage.getItem('activeProfileId') || '';
}

export function setActiveProfile(profile) {
  if (profile?.id == null) return;
  localStorage.setItem('activeProfileId', String(profile.id));
  localStorage.setItem('activeProfile', JSON.stringify(profile));
  if (profile.language_preference) setLanguage(profile.language_preference);
  window.dispatchEvent(new Event('activeProfileChanged'));
}

export function clearActiveProfile() {
  localStorage.removeItem('activeProfileId');
  localStorage.removeItem('activeProfile');
  window.dispatchEvent(new Event('activeProfileChanged'));
}

export const MAX_PROFILES = 4;

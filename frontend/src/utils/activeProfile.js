// src/utils/activeProfile.js
// The profile in use (localStorage: the API sends it as X-Profile-Id). Changing it tells the app
// ("activeProfileChanged"): App remounts the pages for the new profile, no full reload.
// Each profile has its language (language_preference): the app switches to it with the profile.
// And its look (appearance: fonts, accent, background - design/theme.js).
import { setLanguage } from '../i18n';
import { DEFAULT_APPEARANCE, setAppearance } from '../design/theme';

export function getActiveProfileId() {
  return localStorage.getItem('activeProfileId') || '';
}

export function setActiveProfile(profile) {
  if (profile?.id == null) return;
  localStorage.setItem('activeProfileId', String(profile.id));
  localStorage.setItem('activeProfile', JSON.stringify(profile));
  if (profile.language_preference) setLanguage(profile.language_preference);
  setAppearance(profile.appearance);
  window.dispatchEvent(new Event('activeProfileChanged'));
}

export function clearActiveProfile() {
  localStorage.removeItem('activeProfileId');
  localStorage.removeItem('activeProfile');
  setAppearance(DEFAULT_APPEARANCE);
  window.dispatchEvent(new Event('activeProfileChanged'));
}

export const MAX_PROFILES = 4;

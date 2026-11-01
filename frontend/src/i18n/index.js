// src/i18n/index.js
// Translations (i18next + react-i18next).
//
// - One JSON file per language in src/i18n/locales/<lang>/<namespace>.json. English is bundled
//   (instant first paint + fallback for any missing key); every other language is its own
//   code-split chunk, downloaded only when that language is used.
// - Language choice, first match wins: ?lng= in the address, the language saved on this device
//   (the active profile's language, or the picker on signed-out pages), then the browser's
//   languages (navigator.languages), then English. "fr-CA" -> "fr", "zh-TW" -> "zh".
// - Plurals use the CLDR rules of each language (Intl.PluralRules): keys end in _one / _other
//   (and _zero / _few / _many where a language needs them). Numbers, dates and lists go through
//   Intl in the current language (i18n/format.js, or {{value, number}} in a string).
// - <html lang> / dir follow the language; the API gets it as Accept-Language (api/http.js) so
//   messages, emails and catalog texts (titles, synopses) come back in the same language.
//
// Adding a language: add its code to SUPPORTED_LANGUAGES, copy locales/en into locales/<code>,
// translate, then `npm run i18n:check` (same keys and placeholders in every language).
import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import LanguageDetector from 'i18next-browser-languagedetector';
import resourcesToBackend from 'i18next-resources-to-backend';
import enCommon from './locales/en/common.json';

/** code -> name in that language (shown as is in every picker, the usual convention) */
export const SUPPORTED_LANGUAGES = {
  en: 'English',
  fr: 'Français',
  es: 'Español',
  de: 'Deutsch',
  it: 'Italiano',
  ja: '日本語',
  zh: '中文',
};
export const LANGUAGE_CODES = Object.keys(SUPPORTED_LANGUAGES);
export const DEFAULT_LANGUAGE = 'en';
export const NAMESPACES = ['common', 'auth', 'profiles', 'catalog', 'watch', 'account', 'admin', 'legal'];
const STORAGE_KEY = 'lang';

// older profiles were saved with non-standard codes
const ALIASES = { jp: 'ja', cn: 'zh', 'zh-cn': 'zh', 'zh-tw': 'zh', 'zh-hk': 'zh' };

/** "fr-CA" -> "fr", "jp" -> "ja", unknown -> null */
export function normalizeLanguage(code) {
  if (!code) return null;
  const lower = String(code).trim().toLowerCase().replace('_', '-');
  const aliased = ALIASES[lower] || lower;
  const base = aliased.split('-')[0];
  if (SUPPORTED_LANGUAGES[aliased]) return aliased;
  if (SUPPORTED_LANGUAGES[base]) return base;
  return ALIASES[base] || null;
}

i18n
  .use(
    resourcesToBackend((lng, ns) =>
      // webpack makes one chunk per file; English common is already bundled (partialBundledLanguages)
      import(/* webpackChunkName: "i18n-[request]" */ `./locales/${lng}/${ns}.json`)
    )
  )
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: { en: { common: enCommon } },
    partialBundledLanguages: true,
    supportedLngs: LANGUAGE_CODES,
    nonExplicitSupportedLngs: true,
    load: 'languageOnly',
    fallbackLng: DEFAULT_LANGUAGE,
    ns: NAMESPACES,
    defaultNS: 'common',
    fallbackNS: 'common',
    returnNull: false,
    interpolation: { escapeValue: false }, // React escapes already
    detection: {
      order: ['querystring', 'localStorage', 'navigator'],
      lookupQuerystring: 'lng',
      lookupLocalStorage: STORAGE_KEY,
      caches: ['localStorage'],
      convertDetectedLanguage: (lng) => normalizeLanguage(lng) || lng,
    },
    react: { useSuspense: true },
  });

function applyToDocument(lng) {
  if (typeof document === 'undefined') return;
  const html = document.documentElement;
  html.lang = lng;
  html.dir = i18n.dir(lng);
}

i18n.on('languageChanged', applyToDocument);
if (i18n.resolvedLanguage) applyToDocument(i18n.resolvedLanguage);

/** The language in use, always one of LANGUAGE_CODES */
export function currentLanguage() {
  return normalizeLanguage(i18n.resolvedLanguage || i18n.language) || DEFAULT_LANGUAGE;
}

/** Switch the whole app (and remember it on this device). Unsupported codes are ignored. */
export function setLanguage(code) {
  const lng = normalizeLanguage(code);
  if (!lng || lng === currentLanguage()) return Promise.resolve();
  return i18n.changeLanguage(lng);
}

export default i18n;

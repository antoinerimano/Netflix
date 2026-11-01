// src/i18n/format.js
// Numbers, dates, durations and language names in the current language (Intl). Formatters are
// cached per language: building an Intl object is slow, using one is cheap.
import { useTranslation } from 'react-i18next';
import i18n, { currentLanguage } from './index';

const cache = new Map();
function cached(kind, lng, options, make) {
  const key = `${kind}|${lng}|${JSON.stringify(options || {})}`;
  if (!cache.has(key)) cache.set(key, make());
  return cache.get(key);
}

/** "2024-03-05" / Date / ms -> Date (a bare yyyy-mm-dd is a calendar day, not UTC midnight) */
function toDate(value) {
  if (value instanceof Date) return value;
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    const [y, m, d] = value.split('-').map(Number);
    return new Date(y, m - 1, d);
  }
  return new Date(value);
}

export function formatNumber(value, options, lng = currentLanguage()) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '';
  return cached('n', lng, options, () => new Intl.NumberFormat(lng, options)).format(n);
}

/** 1234 -> "1.2K" / "1234" -> "1234" (short counts) */
export function formatCompact(value, lng = currentLanguage()) {
  return formatNumber(value, { notation: 'compact', maximumFractionDigits: 1 }, lng);
}

export function formatDate(value, options = { dateStyle: 'medium' }, lng = currentLanguage()) {
  if (value == null || value === '') return '';
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return '';
  return cached('d', lng, options, () => new Intl.DateTimeFormat(lng, options)).format(date);
}

/** "in 3 days" / "yesterday" / "2 hours ago" */
export function formatRelative(value, lng = currentLanguage()) {
  const date = toDate(value);
  if (Number.isNaN(date.getTime())) return '';
  const rtf = cached('r', lng, null, () => new Intl.RelativeTimeFormat(lng, { numeric: 'auto' }));
  const seconds = Math.round((date.getTime() - Date.now()) / 1000);
  const units = [
    ['year', 31536000],
    ['month', 2592000],
    ['week', 604800],
    ['day', 86400],
    ['hour', 3600],
    ['minute', 60],
  ];
  for (const [unit, size] of units) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit);
  }
  return rtf.format(seconds, 'second');
}

/** 0 -> "Today", 1 -> "Yesterday", 3 -> "3 days ago" (capitalized, to start a line) */
export function formatRelativeDay(daysAgo, lng = currentLanguage()) {
  const rtf = cached('r', lng, null, () => new Intl.RelativeTimeFormat(lng, { numeric: 'auto' }));
  const text = rtf.format(-daysAgo, 'day');
  return text.charAt(0).toLocaleUpperCase(lng) + text.slice(1);
}

/** 135 -> "2 h 15 min" in the current language */
export function formatRuntime(minutes, lng = currentLanguage()) {
  const m = Math.round(Number(minutes));
  if (!Number.isFinite(m) || m <= 0) return '';
  const h = Math.floor(m / 60);
  const rest = m % 60;
  const unit = (u, n) =>
    cached('u', lng, u, () => new Intl.NumberFormat(lng, { style: 'unit', unit: u, unitDisplay: 'short' })).format(n);
  if (!h) return unit('minute', rest);
  return rest ? `${unit('hour', h)} ${unit('minute', rest)}` : unit('hour', h);
}

/** ["Drama", "Crime"] -> "Drama and Crime" / "Drama et Crime" */
export function formatList(items, type = 'conjunction', lng = currentLanguage()) {
  const list = (items || []).filter(Boolean).map(String);
  if (!list.length) return '';
  try {
    return cached('l', lng, type, () => new Intl.ListFormat(lng, { style: 'long', type })).format(list);
  } catch {
    return list.join(', ');
  }
}

/** "ja" -> "Japanese" (English) / "japonais" (French) */
export function languageName(code, lng = currentLanguage()) {
  if (!code) return '';
  try {
    return cached('ln', lng, null, () => new Intl.DisplayNames([lng], { type: 'language' })).of(code) || code.toUpperCase();
  } catch {
    return String(code).toUpperCase();
  }
}

/** "FR" -> "France" / "Frankreich" */
export function regionName(code, lng = currentLanguage()) {
  if (!code) return '';
  try {
    return cached('rn', lng, null, () => new Intl.DisplayNames([lng], { type: 'region' })).of(code) || code;
  } catch {
    return code;
  }
}

/**
 * The same helpers bound to the language of the component (re-renders when it changes):
 * const { formatDate, languageName } = useFormat();
 */
export function useFormat() {
  const { i18n: instance } = useTranslation();
  const lng = instance.resolvedLanguage || currentLanguage();
  return {
    lng,
    formatNumber: (v, o) => formatNumber(v, o, lng),
    formatCompact: (v) => formatCompact(v, lng),
    formatDate: (v, o) => formatDate(v, o, lng),
    formatRelative: (v) => formatRelative(v, lng),
    formatRuntime: (v) => formatRuntime(v, lng),
    formatList: (v, t) => formatList(v, t, lng),
    languageName: (c) => languageName(c, lng),
    regionName: (c) => regionName(c, lng),
  };
}

export { i18n };

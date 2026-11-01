// src/i18n/catalogText.js
// Texts the server describes as data and the app words in its language (the server's English
// sentence stays as a fallback, shown only in English):
//   rowTitle(row)        home rows: { row_type: "genre:comedy", params: { genre: "comedy" }, title }
//   whyText(item)        card reason: { why_key: { key: "similarTo", title, liked }, why }
//   matchText(result)    search reason: { match_key: { key: "with", name }, match }
import i18n from './index';
import { formatCompact, formatDate, formatNumber, languageName, regionName } from './format';
import { genreName } from '../components/detail/DetailHero';

const t = (key, opts) => i18n.t(key, opts);
const isEnglish = () => (i18n.resolvedLanguage || 'en') === 'en';
const rating = (n) => formatNumber(n, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export function rowTitle(row) {
  const kind = String(row?.row_type || '').split(':')[0];
  const p = row?.params || {};
  const fallback = row?.title || t('catalog:home.recommended');
  const values = {
    ...p,
    language: p.language ? languageName(p.language) : '',
    genre: p.genre ? genreName(p.genre) : '',
    country: p.country ? regionName(p.country) : '',
  };
  // a row that needs a value the server didn't send keeps its own title
  const needs = { in_lang: 'language', lang_trending: 'language', because: 'title', genre: 'genre', studio: 'name', network: 'name', actor: 'name', country: 'country', kw: 'keyword' };
  if (!kind || (needs[kind] && !values[needs[kind]])) return fallback;
  return t(`catalog:home.rows.${kind}`, { ...values, defaultValue: fallback });
}

export function whyText(item) {
  const w = item?.why_key;
  if (!w?.key) return isEnglish() ? item?.why || '' : ''; // older snapshot: English only
  switch (w.key) {
    case 'similarTo':
      return t(w.liked ? 'catalog:home.why.similarToLiked' : 'catalog:home.why.similarTo', { title: w.title || '' });
    case 'ratedBy':
      return t('catalog:home.why.ratedBy', { rating: rating(w.rating), votes: formatCompact(w.votes) });
    case 'hiddenGem':
      return t('catalog:home.why.hiddenGem', { rating: rating(w.rating) });
    case 'newRelease':
      return t('catalog:home.why.newRelease', { date: formatDate(`${w.date}-01`, { month: 'short', year: 'numeric' }) });
    default:
      return t(`catalog:home.why.${w.key}`, { defaultValue: isEnglish() ? item?.why || '' : '' });
  }
}

function filtersText(k) {
  const parts = (k.genres || []).map((g) => genreName(g));
  if (k.yearFrom) {
    const from = Number(k.yearFrom);
    const to = Number(k.yearTo || k.yearFrom);
    if (to === from + 9 && from % 10 === 0) parts.push(t('catalog:browse.years.decade', { decade: from }));
    else if (to === from) parts.push(String(from));
    else parts.push(t('catalog:browse.years.range', { from, to }));
  }
  if (k.kind) parts.push(t(`common:kind.${k.kind === 'tv' ? 'tv' : 'movie'}`));
  return parts.join(' · ');
}

export function matchText(result) {
  const k = result?.match_key;
  if (!k?.key) return isEnglish() ? result?.match || '' : '';
  if (k.key === 'filters') return filtersText(k);
  return t(`catalog:search.match.${k.key}`, { ...k, defaultValue: isEnglish() ? result?.match || '' : '' });
}

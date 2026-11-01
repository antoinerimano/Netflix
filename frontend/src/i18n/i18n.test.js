// Translations: language codes, loading a language, Intl formatting, server texts worded here.
import i18n, { normalizeLanguage, setLanguage, LANGUAGE_CODES } from './index';
import { formatRuntime, formatRelativeDay, formatNumber, languageName } from './format';
import { rowTitle, whyText, matchText } from './catalogText';

afterEach(async () => {
  await i18n.changeLanguage('en');
});

describe('normalizeLanguage', () => {
  test.each([
    ['fr-CA', 'fr'],
    ['jp', 'ja'],
    ['zh-TW', 'zh'],
    ['ZH_cn', 'zh'],
    ['de', 'de'],
    ['ko-KR', null],
    ['pt-BR', 'pt'],
    ['', null],
  ])('%s -> %s', (input, expected) => {
    expect(normalizeLanguage(input)).toBe(expected);
  });

  test('every supported code normalizes to itself', () => {
    LANGUAGE_CODES.forEach((code) => expect(normalizeLanguage(code)).toBe(code));
  });
});

test('switching language loads its texts and updates <html lang>', async () => {
  await setLanguage('fr');
  await i18n.loadNamespaces(['auth', 'catalog']);
  expect(i18n.t('auth:signIn.title')).toBe('Bon retour parmi nous');
  expect(document.documentElement.lang).toBe('fr');
  // plurals follow the language's rules
  expect(i18n.t('catalog:detail.seasonCount', { count: 1 })).toBe('1 saison');
  expect(i18n.t('catalog:detail.seasonCount', { count: 3 })).toBe('3 saisons');
});

test('every supported language has its own texts', async () => {
  // a language listed in SUPPORTED_LANGUAGES without its locales/<lang> files would show English
  const english = 'Welcome back';
  for (const lng of LANGUAGE_CODES) {
    await i18n.changeLanguage(lng);
    await i18n.loadNamespaces('auth');
    const title = i18n.getFixedT(lng, 'auth')('signIn.title');
    if (lng === 'en') expect(title).toBe(english);
    else expect([lng, title]).not.toEqual([lng, english]);
  }
});

test('unsupported languages are ignored', async () => {
  await setLanguage('xx');
  expect(i18n.resolvedLanguage).toBe('en');
});

test('formatting follows the language', () => {
  expect(formatRuntime(135, 'en')).toMatch(/2\s*hr?\s*15\s*min/);
  expect(formatNumber(7.3, { minimumFractionDigits: 1 }, 'fr')).toBe('7,3');
  expect(languageName('ja', 'fr').toLowerCase()).toBe('japonais');
  expect(formatRelativeDay(1, 'en')).toBe('Yesterday');
});

describe('texts the server sends as data', () => {
  test('row titles', async () => {
    expect(rowTitle({ row_type: 'genre:comedy', params: { genre: 'comedy' }, title: 'More Comedy' })).toBe('More Comedy');
    expect(rowTitle({ row_type: 'because:12', params: { title_id: 12, title: 'Heat' } })).toBe('Because you watched Heat');
    await i18n.changeLanguage('fr');
    await i18n.loadNamespaces('catalog');
    expect(rowTitle({ row_type: 'genre:comedy', params: { genre: 'comedy' }, title: 'More Comedy' })).toBe('Comédie : encore plus');
    expect(rowTitle({ row_type: 'trending', params: {}, title: 'Trending' })).toBe('Tendances');
  });

  test('card reasons fall back to the English sentence only in English', async () => {
    const old = { why: 'Similar to Heat' }; // snapshot built before why_key existed
    expect(whyText(old)).toBe('Similar to Heat');
    expect(whyText({ why_key: { key: 'similarTo', title: 'Heat', liked: true } })).toBe('Similar to Heat, which you liked');
    await i18n.changeLanguage('fr');
    await i18n.loadNamespaces('catalog');
    expect(whyText(old)).toBe('');
    expect(whyText({ why_key: { key: 'popularNow' } })).toBe('Populaire en ce moment');
  });

  test('search reasons', () => {
    expect(matchText({ match_key: { key: 'with', name: 'Bryan Cranston' } })).toBe('With Bryan Cranston');
    expect(matchText({ match_key: { key: 'filters', genres: ['Crime'], yearFrom: 1990, yearTo: 1999, kind: 'tv' } })).toBe('Crime · 1990s · Series');
    expect(matchText({})).toBe('');
  });
});

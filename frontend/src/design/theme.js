// src/design/theme.js
// A profile's look (Appearance page): a font pair, an accent color and a background, chosen from
// the presets below. Saved on the profile ("appearance": {font, accent, background}, ids only),
// so it follows the profile on every device, and in localStorage so the first paint already has
// it. Applying = setting the design tokens (tokens.css) on <html>; missing ids = the default look.

const GOOGLE = 'https://fonts.googleapis.com/css2?';
const SYSTEM = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';

/** Font pairs: titles (display) + text. `css` is the Google Fonts query (null: nothing to download). */
export const FONTS = [
  { id: 'default', display: 'Space Grotesk', text: 'IBM Plex Sans', css: null }, // index.html loads it
  { id: 'cinema', display: 'Oswald', text: 'Barlow', css: 'family=Barlow:wght@400;500;600;700&family=Oswald:wght@500;600;700', tracking: '0.01em' },
  { id: 'classic', display: 'DM Serif Display', text: 'Karla', css: 'family=DM+Serif+Display&family=Karla:wght@400;500;600;700', tracking: '0' },
  { id: 'bold', display: 'Unbounded', text: 'Rubik', css: 'family=Rubik:wght@400;500;600;700&family=Unbounded:wght@500;600;700' },
  { id: 'editorial', display: 'Fraunces', text: 'Instrument Sans', css: 'family=Fraunces:wght@500;600;700&family=Instrument+Sans:wght@400;500;600;700' },
  { id: 'friendly', display: 'Nunito', text: 'Nunito', css: 'family=Nunito:wght@400;500;600;700;800' },
  { id: 'readable', display: 'Atkinson Hyperlegible', text: 'Atkinson Hyperlegible', css: 'family=Atkinson+Hyperlegible:wght@400;700', tracking: '0' },
  { id: 'system', display: null, text: null, css: null }, // the device's own font: nothing to download
];

/** Accent colors: buttons, highlights, glows. onBrand: the text drawn on it. */
export const ACCENTS = [
  { id: 'red', brand: '#e50914', hover: '#f6121d', pressed: '#c10710', rgb: '229, 9, 20' },
  { id: 'orange', brand: '#ea580c', hover: '#f26b1d', pressed: '#c2410c', rgb: '234, 88, 12' },
  { id: 'amber', brand: '#f5b50a', hover: '#ffc62e', pressed: '#d99c00', rgb: '245, 181, 10', onBrand: '#14110a' },
  { id: 'green', brand: '#16a34a', hover: '#1cb955', pressed: '#128a3e', rgb: '22, 163, 74' },
  { id: 'teal', brand: '#0d9488', hover: '#10a99b', pressed: '#0b7d73', rgb: '13, 148, 136' },
  { id: 'blue', brand: '#2563eb', hover: '#3b76f6', pressed: '#1d4fd0', rgb: '37, 99, 235' },
  { id: 'violet', brand: '#7c3aed', hover: '#8b4ff5', pressed: '#6929d4', rgb: '124, 58, 237' },
  { id: 'pink', brand: '#db2777', hover: '#e8408a', pressed: '#be1d65', rgb: '219, 39, 119' },
];

/** Dark backgrounds: page, deep (hero / player), and the 3 raised surfaces. */
export const BACKGROUNDS = [
  { id: 'graphite', bg: '#0f0f12', bgRgb: '15, 15, 18', deep: '#08080a', deepRgb: '8, 8, 10', s1: '#18181c', s2: '#222228', s3: '#2e2e36' },
  { id: 'black', bg: '#000000', bgRgb: '0, 0, 0', deep: '#000000', deepRgb: '0, 0, 0', s1: '#111113', s2: '#1b1b1f', s3: '#26262b' },
  { id: 'midnight', bg: '#0b1020', bgRgb: '11, 16, 32', deep: '#060912', deepRgb: '6, 9, 18', s1: '#131a2e', s2: '#1c243c', s3: '#27304b' },
  { id: 'espresso', bg: '#14100e', bgRgb: '20, 16, 14', deep: '#0b0807', deepRgb: '11, 8, 7', s1: '#1e1916', s2: '#29221e', s3: '#352c27' },
  { id: 'forest', bg: '#0b120f', bgRgb: '11, 18, 15', deep: '#060a08', deepRgb: '6, 10, 8', s1: '#131c18', s2: '#1c2722', s3: '#26332d' },
];

export const DEFAULT_APPEARANCE = { font: 'default', accent: 'red', background: 'graphite' };

const STORAGE_KEY = 'appearance';
const byId = (list, id) => list.find((x) => x.id === id) || list[0];

/** Only known ids, every key filled (an unknown id from an older / newer app: the default). */
export function normalizeAppearance(a) {
  const src = a && typeof a === 'object' ? a : {};
  return {
    font: byId(FONTS, src.font).id,
    accent: byId(ACCENTS, src.accent).id,
    background: byId(BACKGROUNDS, src.background).id,
  };
}

/** Downloads a font pair's files once (also used to draw the choices on the Appearance page). */
export function loadFont(fontId) {
  const font = byId(FONTS, fontId);
  if (!font.css || typeof document === 'undefined') return;
  const id = `font-${font.id}`;
  if (document.getElementById(id)) return;
  const link = document.createElement('link');
  link.id = id;
  link.rel = 'stylesheet';
  link.href = `${GOOGLE}${font.css}&display=swap`;
  document.head.appendChild(link);
}

/** CSS font stacks of a pair: [display, text] */
export function fontStacks(fontId) {
  const font = byId(FONTS, fontId);
  if (!font.text) return [SYSTEM, SYSTEM];
  return [`"${font.display}", "${font.text}", ${SYSTEM}`, `"${font.text}", ${SYSTEM}`];
}

/** Sets the tokens on <html>. The default of each part removes its variables (tokens.css wins). */
export function applyAppearance(appearance) {
  if (typeof document === 'undefined') return;
  const a = normalizeAppearance(appearance);
  const style = document.documentElement.style;
  const set = (vars, on) => Object.entries(vars).forEach(([k, v]) => (on ? style.setProperty(k, v) : style.removeProperty(k)));

  const font = byId(FONTS, a.font);
  loadFont(font.id);
  const [display, text] = fontStacks(font.id);
  set({ '--font-display': display, '--font-sans': text }, font.id !== 'default');
  set({ '--tracking-tight': font.tracking || '-0.02em' }, font.tracking != null);

  const c = byId(ACCENTS, a.accent);
  set(
    {
      '--color-brand': c.brand,
      '--color-brand-hover': c.hover,
      '--color-brand-pressed': c.pressed,
      '--color-brand-rgb': c.rgb,
      '--color-text-on-brand': c.onBrand || '#ffffff',
    },
    c.id !== 'red'
  );

  const b = byId(BACKGROUNDS, a.background);
  set(
    {
      '--color-bg': b.bg,
      '--color-bg-rgb': b.bgRgb,
      '--color-bg-deep': b.deep,
      '--color-bg-deep-rgb': b.deepRgb,
      '--color-surface-1': b.s1,
      '--color-surface-2': b.s2,
      '--color-surface-3': b.s3,
    },
    b.id !== 'graphite'
  );
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', b.id === 'graphite' ? '#000000' : b.deep);
}

/** The look of the profile in use, as last saved on this device. */
export function storedAppearance() {
  try {
    return normalizeAppearance(JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'));
  } catch {
    return { ...DEFAULT_APPEARANCE };
  }
}

/** Applies and remembers it for the next start (the profile's copy is saved by the caller). */
export function setAppearance(appearance) {
  const a = normalizeAppearance(appearance);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(a));
  } catch {
    /* private mode: applied for this visit only */
  }
  applyAppearance(a);
  return a;
}

/** What is saved on the profile: only the parts that differ from the default. */
export function toProfileValue(appearance) {
  const a = normalizeAppearance(appearance);
  return Object.fromEntries(Object.entries(a).filter(([k, v]) => DEFAULT_APPEARANCE[k] !== v));
}

// src/design/avatarArt.js
// Avatars people build themselves (profile form -> "Create"): a character drawn in SVG from
// parts. Stored as a short code in Profile.avatar_url (255 chars max), e.g.
// "avatar:2:3-1-0-2-4-1-5-3-0-...", so it needs no upload / storage and stays sharp at every size.
// Codes from version 1 (hats were hair styles, the mustache an extra) are converted on read.
import React from 'react';

export const AVATAR_PREFIX = 'avatar:2:';

/* ---------- palettes ---------- */
export const BACKGROUNDS = [
  ['#ff5f6d', '#ffc371'],
  ['#e50914', '#7a0b12'],
  ['#4facfe', '#00f2fe'],
  ['#43e97b', '#38f9d7'],
  ['#a18cd1', '#fbc2eb'],
  ['#667eea', '#764ba2'],
  ['#f7971e', '#ffd200'],
  ['#0f2027', '#2c5364'],
  ['#ff9a9e', '#fecfef'],
  ['#11998e', '#38ef7d'],
  ['#fc466b', '#3f5efb'],
  ['#232526', '#414345'],
  ['#ffecd2', '#fcb69f'],
  ['#30cfd0', '#330867'],
  ['#d4fc79', '#96e6a1'],
  ['#f857a6', '#ff5858'],
];
export const SKINS = ['#ffe6d5', '#ffdcc4', '#f3c79e', '#e0ac69', '#c68642', '#8d5524', '#5c3a21', '#8fd3ff', '#9be37a', '#c9a7ff'];
const HUMAN_SKINS = 7;
export const HAIR_COLORS = ['#1d1d22', '#4a2c17', '#8b5a2b', '#d9a441', '#e85d3a', '#eeeeee', '#9a9aa6', '#ff5fa2', '#5b7cff', '#2bb673'];
export const CLOTH_COLORS = ['#1d1d22', '#ffffff', '#e50914', '#2b59c3', '#2bb673', '#f5a524', '#8b5cf6', '#ec4899', '#14b8a6', '#9a9aa6'];
const INK = '#1d1d22';

/* parts, in the order of the code (never reorder: saved codes depend on it) */
export const PARTS = [
  { key: 'bg', label: 'Background', count: BACKGROUNDS.length },
  { key: 'pt', label: 'Pattern', count: 7, names: ['None', 'Dots', 'Stripes', 'Waves', 'Stars', 'Grid', 'Confetti'] },
  { key: 'fc', label: 'Face shape', count: 4, names: ['Round', 'Square', 'Oval', 'Wide'] },
  { key: 'sk', label: 'Skin', count: SKINS.length },
  { key: 'ey', label: 'Eyes', count: 10, names: ['Dots', 'Shiny', 'Happy', 'Wink', 'Sleepy', 'Stars', 'Shades', 'Big', 'Lashes', 'Hearts'] },
  { key: 'eb', label: 'Eyebrows', count: 7, names: ['None', 'Soft', 'Thick', 'Raised', 'Angry', 'Worried', 'Unibrow'] },
  { key: 'mo', label: 'Mouth', count: 8, names: ['Smile', 'Grin', 'Surprised', 'Neutral', 'Tongue', 'Smirk', 'Laugh', 'Lipstick'] },
  {
    key: 'hr',
    label: 'Hair',
    count: 12,
    names: ['None', 'Short', 'Spiky', 'Curly', 'Long', 'Bun', 'Mohawk', 'Afro', 'Side part', 'Buzz', 'Ponytail', 'Pigtails'],
  },
  { key: 'hc', label: 'Hair color', count: HAIR_COLORS.length },
  {
    key: 'hw',
    label: 'Hat',
    count: 10,
    names: ['None', 'Cap', 'Beanie', 'Crown', 'Headphones', 'Bandana', 'Top hat', 'Flowers', 'Halo', 'Cat ears'],
  },
  { key: 'hwc', label: 'Hat color', count: CLOTH_COLORS.length },
  { key: 'bd', label: 'Beard', count: 6, names: ['None', 'Stubble', 'Full', 'Goatee', 'Mustache', 'Handlebar'] },
  { key: 'ex', label: 'Extras', count: 7, names: ['None', 'Blush', 'Freckles', 'Round glasses', 'Square glasses', 'Earrings', 'Beauty mark'] },
  { key: 'sh', label: 'Top color', count: CLOTH_COLORS.length },
  { key: 'ts', label: 'Top', count: 4, names: ['T-shirt', 'Hoodie', 'Collar', 'Turtleneck'] },
];
export const partByKey = Object.fromEntries(PARTS.map((p) => [p.key, p]));

/* ---------- code <-> spec ---------- */
export function isBuiltAvatar(src) {
  return typeof src === 'string' && /^avatar:\d+:/.test(src);
}

const EMPTY = Object.fromEntries(PARTS.map((p) => [p.key, 0]));

function fromV1(nums) {
  // v1: bg, pt, fc, sk, ey, mo, hr (7-9 were cap / beanie / crown), hc, ex (4 mustache), sh
  const [bg, pt, fc, sk, ey, mo, hr, hc, ex, sh] = nums.map((n) => (Number.isInteger(n) ? n : 0));
  const spec = { ...EMPTY, bg, pt, fc, sk: Math.min(sk + 1, SKINS.length - 1), ey, mo, hc, sh };
  if (hr >= 7) spec.hw = { 7: 1, 8: 2, 9: 3 }[hr];
  else spec.hr = hr;
  if (ex === 4) spec.bd = 4;
  else spec.ex = { 0: 0, 1: 1, 2: 2, 3: 3, 5: 5 }[ex] || 0;
  return spec;
}

export function parseAvatar(src) {
  const m = /^avatar:(\d+):(.*)$/.exec(String(src || ''));
  if (!m) return { ...EMPTY };
  const nums = m[2].split('-').map((n) => parseInt(n, 10));
  const raw = m[1] === '1' ? fromV1(nums) : Object.fromEntries(PARTS.map((p, i) => [p.key, nums[i]]));
  const spec = {};
  PARTS.forEach((p) => {
    const n = raw[p.key];
    spec[p.key] = Number.isInteger(n) && n >= 0 && n < p.count ? n : 0;
  });
  return spec;
}

export function encodeAvatar(spec) {
  return AVATAR_PREFIX + PARTS.map((p) => spec[p.key] || 0).join('-');
}

export function randomAvatar() {
  const r = (n) => Math.floor(Math.random() * n);
  const spec = {};
  PARTS.forEach((p) => {
    spec[p.key] = r(p.count);
  });
  // random but rarely ugly: mostly human skins, hats / beards / extras / patterns now and then
  if (Math.random() < 0.85) spec.sk = r(HUMAN_SKINS);
  if (Math.random() < 0.6) spec.hw = 0;
  if (Math.random() < 0.7) spec.bd = 0;
  if (Math.random() < 0.5) spec.ex = 0;
  if (Math.random() < 0.5) spec.pt = 0;
  if (Math.random() < 0.3) spec.eb = 1;
  return spec;
}

/* ---------- drawing helpers ---------- */
const star = (cx, cy, r) => {
  const pts = [];
  for (let i = 0; i < 10; i += 1) {
    const a = (Math.PI / 5) * i - Math.PI / 2;
    const rad = i % 2 ? r * 0.45 : r;
    pts.push(`${(cx + rad * Math.cos(a)).toFixed(2)},${(cy + rad * Math.sin(a)).toFixed(2)}`);
  }
  return pts.join(' ');
};
const heart = (cx, cy, s) =>
  `M${cx} ${cy + s * 0.9} C${cx - s * 1.6} ${cy - s * 0.2} ${cx - s * 0.7} ${cy - s * 1.3} ${cx} ${cy - s * 0.35} ` +
  `C${cx + s * 0.7} ${cy - s * 1.3} ${cx + s * 1.6} ${cy - s * 0.2} ${cx} ${cy + s * 0.9} Z`;
const both = (fn) => (
  <>
    {fn(40, 'l')}
    {fn(60, 'r')}
  </>
);

/* ---------- parts ---------- */
function Face({ shape, skin }) {
  switch (shape) {
    case 1:
      return <rect x="24" y="28" width="52" height="56" rx="20" fill={skin} />;
    case 2:
      return <ellipse cx="50" cy="55" rx="24" ry="30" fill={skin} />;
    case 3:
      return <ellipse cx="50" cy="58" rx="29" ry="25" fill={skin} />;
    default:
      return <ellipse cx="50" cy="56" rx="26" ry="28" fill={skin} />;
  }
}

function Eyes({ style }) {
  const arc = (x) => <path key={x} d={`M${x - 4.5} 56 q4.5 -5.5 9 0`} stroke={INK} strokeWidth="2.6" fill="none" strokeLinecap="round" />;
  switch (style) {
    case 1:
      return both((x) => (
        <g key={x}>
          <ellipse cx={x} cy="54" rx="3.2" ry="4.2" fill={INK} />
          <circle cx={x + 1.1} cy="52.6" r="1.1" fill="#fff" />
        </g>
      ));
    case 2:
      return both(arc);
    case 3:
      return (
        <>
          <circle cx="40" cy="54" r="3.2" fill={INK} />
          {arc(60)}
        </>
      );
    case 4:
      return both((x) => <path key={x} d={`M${x - 4.5} 55 q4.5 3 9 0`} stroke={INK} strokeWidth="2.4" fill="none" strokeLinecap="round" />);
    case 5:
      return both((x) => <polygon key={x} points={star(x, 54, 5)} fill="#f5c518" stroke={INK} strokeWidth="0.8" />);
    case 6:
      return (
        <>
          <rect x="30" y="48.5" width="17" height="11" rx="4.5" fill={INK} />
          <rect x="53" y="48.5" width="17" height="11" rx="4.5" fill={INK} />
          <path d="M47 52 h6" stroke={INK} strokeWidth="2.2" />
          <path d="M33 51.5 l4 0 M56 51.5 l4 0" stroke="#fff" strokeOpacity="0.45" strokeWidth="1.6" strokeLinecap="round" />
        </>
      );
    case 7:
      return both((x) => (
        <g key={x}>
          <ellipse cx={x} cy="54" rx="5.2" ry="6.2" fill="#fff" />
          <circle cx={x} cy="55" r="3.3" fill={INK} />
          <circle cx={x + 1.3} cy="53.4" r="1.2" fill="#fff" />
        </g>
      ));
    case 8:
      return both((x, side) => (
        <g key={x} stroke={INK} strokeWidth="2.2" fill="none" strokeLinecap="round">
          <path d={`M${x - 4.5} 54 q4.5 4 9 0`} />
          <path d={side === 'l' ? `M${x - 4.5} 54 l-2 -2 M${x - 2} 55.6 l-1 -2.4` : `M${x + 4.5} 54 l2 -2 M${x + 2} 55.6 l1 -2.4`} />
        </g>
      ));
    case 9:
      return both((x) => <path key={x} d={heart(x, 54, 4.2)} fill="#ff3b6b" />);
    default:
      return both((x) => <circle key={x} cx={x} cy="54" r="3.2" fill={INK} />);
  }
}

function Brows({ style, color }) {
  const p = { stroke: color, strokeWidth: 2.4, fill: 'none', strokeLinecap: 'round' };
  switch (style) {
    case 1:
      return both((x) => <path key={x} d={`M${x - 5} 47 q5 -3 10 0`} {...p} />);
    case 2:
      return both((x) => <path key={x} d={`M${x - 5.5} 47.5 q5.5 -3.5 11 0`} {...p} strokeWidth="4.2" />);
    case 3:
      return both((x) => <path key={x} d={`M${x - 5} 44.5 q5 -4 10 0`} {...p} />);
    case 4:
      return both((x, side) => <path key={x} d={side === 'l' ? `M${x - 5} 45 l10 3.4` : `M${x + 5} 45 l-10 3.4`} {...p} strokeWidth="2.8" />);
    case 5:
      return both((x, side) => <path key={x} d={side === 'l' ? `M${x - 5} 48 l10 -3.4` : `M${x + 5} 48 l-10 -3.4`} {...p} />);
    case 6:
      return <path d="M34 47 q8 -3.5 16 -0.5 q8 -3 16 0.5" {...p} strokeWidth="3" />;
    default:
      return null;
  }
}

function Mouth({ style }) {
  switch (style) {
    case 1:
      return (
        <>
          <path d="M40 65 q10 13 20 0 z" fill={INK} />
          <path d="M42 65.6 h16 v2.6 q-8 2 -16 0 z" fill="#fff" />
        </>
      );
    case 2:
      return <ellipse cx="50" cy="69" rx="4.2" ry="5" fill={INK} />;
    case 3:
      return <path d="M43 69 h14" stroke={INK} strokeWidth="2.6" strokeLinecap="round" />;
    case 4:
      return (
        <>
          <path d="M41 65 q9 11 18 0 z" fill={INK} />
          <path d="M46 69.4 q4 6 8 0 z" fill="#ff6b8a" />
        </>
      );
    case 5:
      return <path d="M43 69 q8 3 14 -4" stroke={INK} strokeWidth="2.6" fill="none" strokeLinecap="round" />;
    case 6:
      return (
        <>
          <path d="M38 64 q12 17 24 0 z" fill={INK} />
          <path d="M44 72 q6 4 12 0 q-6 -5 -12 0 z" fill="#ff6b8a" />
          <path d="M40 64.6 h20 v2.2 q-10 2 -20 0 z" fill="#fff" />
        </>
      );
    case 7:
      return (
        <>
          <path d="M41 66 q4.5 -3 9 -0.6 q4.5 -2.4 9 0.6 q-9 9 -18 0 z" fill="#d61f45" />
          <path d="M42 66.4 q8 2 16 0" stroke="#8a0f28" strokeWidth="0.9" fill="none" />
        </>
      );
    default:
      return <path d="M42 66 q8 8 16 0" stroke={INK} strokeWidth="2.6" fill="none" strokeLinecap="round" />;
  }
}

/** hair: [behind the face, in front of it] */
function hair(style, color) {
  const front = (d) => <path key="f" d={d} fill={color} />;
  const shortFringe = 'M25 50 C24 32 37 25 50 25 C63 25 76 32 75 50 C70 40 61 35 50 35 C39 35 30 40 25 50 Z';
  switch (style) {
    case 1:
      return [null, front('M24 52 C22 31 36 22 50 22 C66 22 79 31 76 52 C72 40 62 34 50 34 C38 34 28 40 24 52 Z')];
    case 2:
      return [null, front('M24 49 L27 27 L36 34 L41 19 L50 31 L58 17 L64 32 L73 24 L76 49 C70 39 60 34 50 34 C40 34 30 39 24 49 Z')];
    case 3:
      return [
        null,
        <g key="f" fill={color}>
          <circle cx="29" cy="40" r="8.5" />
          <circle cx="36" cy="30" r="9.5" />
          <circle cx="47" cy="25" r="10" />
          <circle cx="59" cy="26" r="10" />
          <circle cx="68" cy="32" r="9.5" />
          <circle cx="73" cy="42" r="8" />
          <path d="M27 46 C34 38 44 35 50 35 C58 35 66 38 74 46 L74 34 L27 34 Z" />
        </g>,
      ];
    case 4:
      return [
        <path key="b" d="M19 94 C14 60 20 23 50 21 C80 23 86 60 81 94 Z" fill={color} />,
        front('M25 50 C26 31 39 24 50 24 C62 24 74 31 75 50 C70 40 63 35 55 34 C50 40 38 44 25 50 Z'),
      ];
    case 5:
      return [
        null,
        <g key="f" fill={color}>
          <circle cx="50" cy="17" r="9" />
          <path d={shortFringe} />
        </g>,
      ];
    case 6:
      return [null, front('M43 36 C41 22 45 11 50 6 C55 11 59 22 57 36 C55 33 45 33 43 36 Z')];
    case 7:
      return [<circle key="b" cx="50" cy="40" r="31" fill={color} />, front('M24 52 C23 34 36 27 50 27 C64 27 77 34 76 52 C71 42 62 38 50 38 C38 38 29 42 24 52 Z')];
    case 8:
      return [
        null,
        <g key="f">
          <path d="M24 52 C22 30 38 21 54 22 C70 23 79 33 76 50 C70 37 58 33 46 35 C39 36 31 41 24 52 Z" fill={color} />
          <path d="M44 23.5 C42 28 40 32 37 37" stroke="#000" strokeOpacity="0.18" strokeWidth="1.4" fill="none" strokeLinecap="round" />
        </g>,
      ];
    case 9:
      return [null, <path key="f" d="M26 47 C27 31 38 27 50 27 C62 27 73 31 74 47 C68 38 60 35 50 35 C40 35 32 38 26 47 Z" fill={color} fillOpacity="0.85" />];
    case 10:
      return [
        <path key="b" d="M70 32 C90 34 92 62 82 76 C85 60 80 47 69 44 Z" fill={color} />,
        front(shortFringe),
      ];
    case 11:
      return [
        <g key="b" fill={color}>
          <circle cx="20" cy="50" r="8.5" />
          <circle cx="80" cy="50" r="8.5" />
          <path d="M18 58 C14 68 18 76 22 78 C20 70 22 64 24 60 Z" />
          <path d="M82 58 C86 68 82 76 78 78 C80 70 78 64 76 60 Z" />
        </g>,
        front(shortFringe),
      ];
    default:
      return [null, null];
  }
}

/** hats / headwear, drawn on top of the hair */
function Hat({ style, color }) {
  switch (style) {
    case 1:
      return (
        <g>
          <path d="M23 47 C23 29 35 21 50 21 C65 21 77 29 77 47 Z" fill={color} />
          <path d="M60 44 L89 45.5 Q92 49 88 50.5 L60 50 Z" fill={color} />
          <path d="M23 47 C23 29 35 21 50 21 C65 21 77 29 77 47 Z" fill="#000" fillOpacity="0.12" />
          <circle cx="50" cy="21" r="2.6" fill={color} />
        </g>
      );
    case 2:
      return (
        <g>
          <path d="M24 46 C24 26 36 17 50 17 C64 17 76 26 76 46 Z" fill={color} />
          <rect x="21" y="40" width="58" height="10" rx="5" fill={color} />
          <rect x="21" y="40" width="58" height="10" rx="5" fill="#fff" fillOpacity="0.18" />
          <circle cx="50" cy="13" r="5.5" fill={color} />
        </g>
      );
    case 3:
      return (
        <g>
          <path d="M29 36 L33 18 L42 29 L50 13 L58 29 L67 18 L71 36 Z" fill="#f5c518" stroke="#c99a00" strokeWidth="1" strokeLinejoin="round" />
          <circle cx="50" cy="27" r="2.6" fill="#e50914" />
          <circle cx="38" cy="30" r="1.8" fill="#4facfe" />
          <circle cx="62" cy="30" r="1.8" fill="#43e97b" />
        </g>
      );
    case 4:
      return (
        <g>
          <path d="M21 54 C21 20 79 20 79 54" stroke={color} strokeWidth="5" fill="none" strokeLinecap="round" />
          <rect x="15" y="47" width="11" height="18" rx="5" fill={color} />
          <rect x="74" y="47" width="11" height="18" rx="5" fill={color} />
          <rect x="15" y="47" width="11" height="18" rx="5" fill="#fff" fillOpacity="0.15" />
          <rect x="74" y="47" width="11" height="18" rx="5" fill="#fff" fillOpacity="0.15" />
        </g>
      );
    case 5:
      return (
        <g>
          <path d="M23 41 C34 34 66 34 77 41 L77 48 C66 42 34 42 23 48 Z" fill={color} />
          <path d="M77 42 L87 37 L85 47 Z M77 45 L88 50 L80 52 Z" fill={color} />
          <g fill="#fff" fillOpacity="0.5">
            <circle cx="36" cy="41.5" r="1" />
            <circle cx="50" cy="39.5" r="1" />
            <circle cx="64" cy="41.5" r="1" />
          </g>
        </g>
      );
    case 6:
      return (
        <g>
          <rect x="33" y="4" width="34" height="30" rx="3" fill={color} />
          <rect x="33" y="25" width="34" height="5" fill="#e50914" />
          <rect x="22" y="31" width="56" height="6" rx="3" fill={color} />
          <rect x="33" y="4" width="34" height="30" rx="3" fill="#000" fillOpacity="0.12" />
        </g>
      );
    case 7:
      return (
        <g>
          {[
            [27, 40, '#ff5fa2'],
            [33, 32, '#f5c518'],
            [42, 27, '#ffffff'],
            [50, 25, '#ff5f6d'],
            [58, 27, '#ffffff'],
            [67, 32, '#f5c518'],
            [73, 40, '#ff5fa2'],
          ].map(([x, y, c]) => (
            <g key={x}>
              <circle cx={x} cy={y} r="4.3" fill={c} />
              <circle cx={x} cy={y} r="1.6" fill="#f5a524" />
            </g>
          ))}
          <path d="M30 37 C38 30 62 30 70 37" stroke="#2bb673" strokeWidth="1.6" fill="none" />
        </g>
      );
    case 8:
      return <ellipse cx="50" cy="13" rx="17" ry="4.5" stroke="#f5c518" strokeWidth="3" fill="none" />;
    case 9:
      return (
        <g>
          <path d="M26 38 L29 13 L45 29 Z M74 38 L71 13 L55 29 Z" fill={color} />
          <path d="M30 31 L31.5 19 L39 27 Z M70 31 L68.5 19 L61 27 Z" fill="#ff9ab5" />
        </g>
      );
    default:
      return null;
  }
}

function Beard({ style, color }) {
  switch (style) {
    case 1:
      return <path d="M27 60 C28 76 38 84 50 84 C62 84 72 76 73 60 C69 70 61 74 50 74 C39 74 31 70 27 60 Z" fill={color} fillOpacity="0.28" />;
    case 2:
      return (
        <path
          d="M25 57 C25 78 37 88 50 88 C63 88 75 78 75 57 C71 66 64 70 58 70 C55 64 45 64 42 70 C36 70 29 66 25 57 Z"
          fill={color}
        />
      );
    case 3:
      return <path d="M43 73 C43 82 57 82 57 73 C54 76 46 76 43 73 Z" fill={color} />;
    case 4:
      return <path d="M39 64.5 q5.5 -5 11 0 q5.5 -5 11 0 q-5.5 4.5 -11 1.2 q-5.5 3.3 -11 -1.2 z" fill={color} />;
    case 5:
      return (
        <path
          d="M50 63 C46 61 40 61 37 64 C35 66 33 64 33.5 61.5 C32 64 33 68 37 67.5 C41 67 46 65 50 65.5 C54 65 59 67 63 67.5 C67 68 68 64 66.5 61.5 C67 64 65 66 63 64 C60 61 54 61 50 63 Z"
          fill={color}
        />
      );
    default:
      return null;
  }
}

function Extras({ style, eyes }) {
  switch (style) {
    case 1:
      return (
        <g fill="#ff6b8a" fillOpacity="0.45">
          <ellipse cx="34.5" cy="63" rx="5" ry="3" />
          <ellipse cx="65.5" cy="63" rx="5" ry="3" />
        </g>
      );
    case 2:
      return (
        <g fill="#8d5524" fillOpacity="0.55">
          {[
            [34, 61],
            [37, 63.5],
            [31.5, 63.8],
            [66, 61],
            [63, 63.5],
            [68.5, 63.8],
          ].map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="1" />
          ))}
        </g>
      );
    case 3:
      return eyes === 6 ? null : (
        <g stroke={INK} strokeWidth="1.8" fill="#fff" fillOpacity="0.12">
          <circle cx="40" cy="54" r="7.5" />
          <circle cx="60" cy="54" r="7.5" />
          <path d="M47.5 53.5 q2.5 -2 5 0" fill="none" />
        </g>
      );
    case 4:
      return eyes === 6 ? null : (
        <g stroke={INK} strokeWidth="2" fill="#fff" fillOpacity="0.12">
          <rect x="31" y="48" width="17" height="12" rx="2.5" />
          <rect x="52" y="48" width="17" height="12" rx="2.5" />
          <path d="M48 53 h4" fill="none" />
        </g>
      );
    case 5:
      return (
        <g fill="#f5c518" stroke="#c99a00" strokeWidth="0.6">
          <circle cx="23.5" cy="65.5" r="2.4" />
          <circle cx="76.5" cy="65.5" r="2.4" />
        </g>
      );
    case 6:
      return <circle cx="61" cy="66" r="1.2" fill="#3b2416" />;
    default:
      return null;
  }
}

function Top({ style, color, skin }) {
  const body = <path d="M14 100 C14 85 30 78 50 78 C70 78 86 85 86 100 Z" fill={color} />;
  switch (style) {
    case 1:
      return (
        <>
          <path d="M26 92 C24 74 36 70 50 70 C64 70 76 74 74 92 Z" fill={color} />
          <path d="M26 92 C24 74 36 70 50 70 C64 70 76 74 74 92 Z" fill="#000" fillOpacity="0.18" />
          {body}
          <rect x="43" y="74" width="14" height="9" rx="4" fill={skin} />
          <path d="M45 84 v8 M55 84 v8" stroke="#fff" strokeOpacity="0.7" strokeWidth="1.6" strokeLinecap="round" />
        </>
      );
    case 2:
      return (
        <>
          {body}
          <rect x="43" y="74" width="14" height="10" rx="4" fill={skin} />
          <path d="M40 79 L50 90 L45 80 Z M60 79 L50 90 L55 80 Z" fill="#fff" />
        </>
      );
    case 3:
      return (
        <>
          {body}
          <rect x="41" y="72" width="18" height="14" rx="6" fill={color} />
          <path d="M42 76 h16 M42 79.5 h16" stroke="#000" strokeOpacity="0.15" strokeWidth="1" />
        </>
      );
    default:
      return (
        <>
          {body}
          <rect x="43" y="74" width="14" height="10" rx="4" fill={skin} />
        </>
      );
  }
}

function Pattern({ id, style }) {
  if (!style) return null;
  const common = { patternUnits: 'userSpaceOnUse' };
  const tiles = {
    1: (
      <pattern id={id} width="10" height="10" {...common}>
        <circle cx="5" cy="5" r="1.4" fill="#fff" />
      </pattern>
    ),
    2: (
      <pattern id={id} width="10" height="10" patternTransform="rotate(35)" {...common}>
        <rect width="4" height="10" fill="#fff" />
      </pattern>
    ),
    3: (
      <pattern id={id} width="20" height="10" {...common}>
        <path d="M0 5 q5 -5 10 0 t10 0" stroke="#fff" strokeWidth="1.6" fill="none" />
      </pattern>
    ),
    4: (
      <pattern id={id} width="16" height="16" {...common}>
        <polygon points={star(8, 8, 3.2)} fill="#fff" />
      </pattern>
    ),
    5: (
      <pattern id={id} width="10" height="10" {...common}>
        <path d="M10 0 V10 M0 10 H10" stroke="#fff" strokeWidth="1" />
      </pattern>
    ),
    6: (
      <pattern id={id} width="24" height="24" {...common}>
        <rect x="3" y="4" width="3" height="6" rx="1" transform="rotate(25 4 7)" fill="#fff" />
        <rect x="15" y="15" width="3" height="6" rx="1" transform="rotate(-30 16 18)" fill="#fff" />
        <circle cx="18" cy="5" r="1.6" fill="#fff" />
        <circle cx="6" cy="19" r="1.4" fill="#fff" />
      </pattern>
    ),
  };
  return (
    <>
      <defs>{tiles[style]}</defs>
      <rect width="100" height="100" fill={`url(#${id})`} opacity="0.16" />
    </>
  );
}

/** The built avatar (fills its box). spec: parseAvatar(code) or the builder's state. */
export function AvatarArt({ spec, className, title }) {
  const uid = React.useId().replace(/:/g, '');
  const s = { ...EMPTY, ...spec };
  const [c1, c2] = BACKGROUNDS[s.bg] || BACKGROUNDS[0];
  const skin = SKINS[s.sk] || SKINS[0];
  const hairColor = HAIR_COLORS[s.hc] || HAIR_COLORS[0];
  const [hairBack, hairFront] = hair(s.hr, hairColor);
  return (
    <svg
      className={className}
      viewBox="0 0 100 100"
      width="100%"
      height="100%"
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
      focusable="false"
    >
      <defs>
        <linearGradient id={`g${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={c1} />
          <stop offset="1" stopColor={c2} />
        </linearGradient>
      </defs>
      <rect width="100" height="100" fill={`url(#g${uid})`} />
      <Pattern id={`p${uid}`} style={s.pt} />
      {hairBack}
      <Top style={s.ts} color={CLOTH_COLORS[s.sh] || CLOTH_COLORS[0]} skin={skin} />
      <ellipse cx="24" cy="58" rx="4.5" ry="6" fill={skin} />
      <ellipse cx="76" cy="58" rx="4.5" ry="6" fill={skin} />
      <Face shape={s.fc} skin={skin} />
      {/* a faint outline: a light beard (white / grey hair) still reads on light skin */}
      <g stroke="#000" strokeOpacity="0.18" strokeWidth="0.8">
        <Beard style={s.bd} color={hairColor} />
      </g>
      <Brows style={s.eb} color={s.hc === 5 ? '#9a9aa6' : hairColor} />
      <Eyes style={s.ey} />
      <Mouth style={s.mo} />
      <Extras style={s.ex} eyes={s.ey} />
      {hairFront}
      <Hat style={s.hw} color={CLOTH_COLORS[s.hwc] || CLOTH_COLORS[0]} />
    </svg>
  );
}

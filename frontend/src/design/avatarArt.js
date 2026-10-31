// src/design/avatarArt.js
// Avatars people build themselves (profile form -> "Create your own"): a character drawn in SVG
// from parts (background, pattern, face, skin, eyes, mouth, hair / hat, hair color, extras).
// Stored as a short code in Profile.avatar_url (255 chars max), e.g. "avatar:1:3-1-0-2-4-1-5-3-0",
// so it needs no upload / storage and stays sharp at every size.
import React from 'react';

export const AVATAR_PREFIX = 'avatar:1:';

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
];
export const SKINS = ['#ffdcc4', '#f3c79e', '#e0ac69', '#c68642', '#8d5524', '#5c3a21', '#8fd3ff', '#9be37a'];
export const HAIR_COLORS = ['#1d1d22', '#4a2c17', '#8b5a2b', '#d9a441', '#e85d3a', '#eeeeee', '#ff5fa2', '#5b7cff'];
export const SHIRTS = ['#1d1d22', '#ffffff', '#e50914', '#2b59c3', '#2bb673', '#f5a524', '#8b5cf6', '#ec4899'];
const INK = '#1d1d22';

export const PARTS = [
  { key: 'bg', label: 'Background', count: BACKGROUNDS.length, color: true },
  { key: 'pt', label: 'Pattern', count: 5 },
  { key: 'fc', label: 'Face', count: 4 },
  { key: 'sk', label: 'Skin', count: SKINS.length, color: true },
  { key: 'ey', label: 'Eyes', count: 8 },
  { key: 'mo', label: 'Mouth', count: 6 },
  { key: 'hr', label: 'Hair & hats', count: 10 },
  { key: 'hc', label: 'Hair color', count: HAIR_COLORS.length, color: true },
  { key: 'ex', label: 'Extras', count: 6 },
  { key: 'sh', label: 'Top', count: SHIRTS.length, color: true },
];

/* ---------- code <-> spec ---------- */
export function isBuiltAvatar(src) {
  return typeof src === 'string' && src.startsWith('avatar:');
}

export function parseAvatar(src) {
  const nums = String(src || '')
    .slice(AVATAR_PREFIX.length)
    .split('-')
    .map((n) => parseInt(n, 10));
  const spec = {};
  PARTS.forEach((p, i) => {
    const n = nums[i];
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
  // mostly human skin tones, extras / patterns now and then: random but rarely ugly
  if (Math.random() < 0.85) spec.sk = r(6);
  if (Math.random() < 0.5) spec.ex = 0;
  if (Math.random() < 0.5) spec.pt = 0;
  return spec;
}

/* ---------- parts ---------- */
const star = (cx, cy, r) => {
  const pts = [];
  for (let i = 0; i < 10; i += 1) {
    const a = (Math.PI / 5) * i - Math.PI / 2;
    const rad = i % 2 ? r * 0.45 : r;
    pts.push(`${(cx + rad * Math.cos(a)).toFixed(2)},${(cy + rad * Math.sin(a)).toFixed(2)}`);
  }
  return pts.join(' ');
};

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

function Ears({ skin }) {
  return (
    <>
      <ellipse cx="24" cy="58" rx="4.5" ry="6" fill={skin} />
      <ellipse cx="76" cy="58" rx="4.5" ry="6" fill={skin} />
    </>
  );
}

function Eyes({ style }) {
  const both = (fn) => (
    <>
      {fn(40)}
      {fn(60)}
    </>
  );
  const arc = (x) => <path d={`M${x - 4.5} 56 q4.5 -5.5 9 0`} stroke={INK} strokeWidth="2.6" fill="none" strokeLinecap="round" />;
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
          <path d="M33 51.5 l4 0" stroke="#ffffff" strokeOpacity="0.45" strokeWidth="1.6" strokeLinecap="round" />
          <path d="M56 51.5 l4 0" stroke="#ffffff" strokeOpacity="0.45" strokeWidth="1.6" strokeLinecap="round" />
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
    default:
      return both((x) => <circle key={x} cx={x} cy="54" r="3.2" fill={INK} />);
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
    default:
      return <path d="M42 66 q8 8 16 0" stroke={INK} strokeWidth="2.6" fill="none" strokeLinecap="round" />;
  }
}

/** hair / hats: [behind the face, in front of it] */
function hair(style, color) {
  switch (style) {
    case 1:
      return [null, <path key="f" d="M24 52 C22 31 36 22 50 22 C66 22 79 31 76 52 C72 40 62 34 50 34 C38 34 28 40 24 52 Z" fill={color} />];
    case 2:
      return [null, <path key="f" d="M24 49 L27 27 L36 34 L41 19 L50 31 L58 17 L64 32 L73 24 L76 49 C70 39 60 34 50 34 C40 34 30 39 24 49 Z" fill={color} />];
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
        <path key="f" d="M25 50 C26 31 39 24 50 24 C62 24 74 31 75 50 C70 40 63 35 55 34 C50 40 38 44 25 50 Z" fill={color} />,
      ];
    case 5:
      return [
        null,
        <g key="f" fill={color}>
          <circle cx="50" cy="17" r="9" />
          <path d="M25 50 C24 32 37 25 50 25 C63 25 76 32 75 50 C70 40 61 35 50 35 C39 35 30 40 25 50 Z" />
        </g>,
      ];
    case 6:
      return [null, <path key="f" d="M43 36 C41 22 45 11 50 6 C55 11 59 22 57 36 C55 33 45 33 43 36 Z" fill={color} />];
    case 7:
      return [
        null,
        <g key="f">
          <path d="M23 47 C23 29 35 21 50 21 C65 21 77 29 77 47 Z" fill={color} />
          <path d="M60 44 L89 45.5 Q92 49 88 50.5 L60 50 Z" fill={color} />
          <path d="M23 47 C23 29 35 21 50 21 C65 21 77 29 77 47 Z" fill="#000" fillOpacity="0.12" />
          <circle cx="50" cy="21" r="2.6" fill={color} />
        </g>,
      ];
    case 8:
      return [
        null,
        <g key="f">
          <path d="M24 46 C24 26 36 17 50 17 C64 17 76 26 76 46 Z" fill={color} />
          <rect x="21" y="40" width="58" height="10" rx="5" fill={color} />
          <rect x="21" y="40" width="58" height="10" rx="5" fill="#fff" fillOpacity="0.18" />
          <circle cx="50" cy="13" r="5.5" fill={color} />
        </g>,
      ];
    case 9:
      return [
        null,
        <g key="f">
          <path d="M29 36 L33 18 L42 29 L50 13 L58 29 L67 18 L71 36 Z" fill="#f5c518" stroke="#c99a00" strokeWidth="1" strokeLinejoin="round" />
          <circle cx="50" cy="27" r="2.6" fill="#e50914" />
          <circle cx="38" cy="30" r="1.8" fill="#4facfe" />
          <circle cx="62" cy="30" r="1.8" fill="#43e97b" />
        </g>,
      ];
    default:
      return [null, null];
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
      return <path d="M39 64.5 q5.5 -5 11 0 q5.5 -5 11 0 q-5.5 4.5 -11 1.2 q-5.5 3.3 -11 -1.2 z" fill="#4a2c17" />;
    case 5:
      return (
        <g fill="#f5c518" stroke="#c99a00" strokeWidth="0.6">
          <circle cx="23.5" cy="65.5" r="2.4" />
          <circle cx="76.5" cy="65.5" r="2.4" />
        </g>
      );
    default:
      return null;
  }
}

function Pattern({ id, style }) {
  if (!style) return null;
  const common = { patternUnits: 'userSpaceOnUse' };
  let tile;
  if (style === 1) {
    tile = (
      <pattern id={id} width="10" height="10" {...common}>
        <circle cx="5" cy="5" r="1.4" fill="#fff" />
      </pattern>
    );
  } else if (style === 2) {
    tile = (
      <pattern id={id} width="10" height="10" patternTransform="rotate(35)" {...common}>
        <rect width="4" height="10" fill="#fff" />
      </pattern>
    );
  } else if (style === 3) {
    tile = (
      <pattern id={id} width="20" height="10" {...common}>
        <path d="M0 5 q5 -5 10 0 t10 0" stroke="#fff" strokeWidth="1.6" fill="none" />
      </pattern>
    );
  } else {
    tile = (
      <pattern id={id} width="16" height="16" {...common}>
        <polygon points={star(8, 8, 3.2)} fill="#fff" />
      </pattern>
    );
  }
  return (
    <>
      <defs>{tile}</defs>
      <rect width="100" height="100" fill={`url(#${id})`} opacity="0.16" />
    </>
  );
}

/** The built avatar (fills its box). spec: parseAvatar(code) or a builder state. */
export function AvatarArt({ spec, className, title }) {
  const uid = React.useId().replace(/:/g, '');
  const s = { ...parseAvatar(''), ...spec };
  const [c1, c2] = BACKGROUNDS[s.bg] || BACKGROUNDS[0];
  const skin = SKINS[s.sk] || SKINS[0];
  const hairColor = HAIR_COLORS[s.hc] || HAIR_COLORS[0];
  const [hairBack, hairFront] = hair(s.hr, hairColor);
  return (
    <svg className={className} viewBox="0 0 100 100" width="100%" height="100%" role={title ? 'img' : undefined} aria-label={title} aria-hidden={title ? undefined : true} focusable="false">
      <defs>
        <linearGradient id={`g${uid}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor={c1} />
          <stop offset="1" stopColor={c2} />
        </linearGradient>
      </defs>
      <rect width="100" height="100" fill={`url(#g${uid})`} />
      <Pattern id={`p${uid}`} style={s.pt} />
      {hairBack}
      {/* shoulders + neck */}
      <path d="M14 100 C14 85 30 78 50 78 C70 78 86 85 86 100 Z" fill={SHIRTS[s.sh] || SHIRTS[0]} />
      <rect x="43" y="74" width="14" height="10" rx="4" fill={skin} />
      <Ears skin={skin} />
      <Face shape={s.fc} skin={skin} />
      <Eyes style={s.ey} />
      <Mouth style={s.mo} />
      <Extras style={s.ex} eyes={s.ey} />
      {hairFront}
    </svg>
  );
}

// src/design/BrandLoader.js
// Loading animation with the Taurus emblem: the horns, then the face, draw themselves in red,
// fill in, a light sweeps across, then it fades and starts again. A soft red glow breathes
// behind it. Reduced motion: a gentle pulse only.
// size: number (px) or CSS length; page: centered on the whole screen; label: for screen readers
// (and shown under the mark when showLabel).
import React from 'react';
import { useTranslation } from 'react-i18next';
import { EMBLEM_PATHS, EMBLEM_VIEWBOX } from './brandMark';

const CYCLE_MS = 2600; // --loader-cycle in components.css

export default function BrandLoader({ size = 72, label: labelProp, showLabel = false, page = false, className = '' }) {
  // useSuspense false: this is also the fallback shown while a language's texts download
  const { t, ready } = useTranslation('common', { useSuspense: false });
  const label = labelProp || (ready ? t('loading') : 'Loading');
  const uid = React.useId().replace(/:/g, '');
  const width = typeof size === 'number' ? `${size}px` : size;
  // every part starts on the page clock: the drawing, the fill and the light stay in step, and
  // several loaders on screen move together
  const [offset] = React.useState(() =>
    typeof performance !== 'undefined' ? `-${Math.round(performance.now() % CYCLE_MS)}ms` : '0ms'
  );
  const mark = (
    <span
      className={`ui-brand-loader ${className}`}
      role="status"
      aria-label={label}
      style={{ '--loader-size': width, '--loader-offset': offset }}
    >
      <svg viewBox={EMBLEM_VIEWBOX} className="ui-brand-loader__mark" aria-hidden="true" focusable="false">
        <defs>
          <clipPath id={`clip${uid}`}>
            {EMBLEM_PATHS.map((d) => (
              <path key={d.slice(0, 24)} d={d} />
            ))}
          </clipPath>
          <linearGradient id={`shine${uid}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="#fff" stopOpacity="0" />
            <stop offset="0.5" stopColor="#fff" stopOpacity="0.75" />
            <stop offset="1" stopColor="#fff" stopOpacity="0" />
          </linearGradient>
        </defs>
        {EMBLEM_PATHS.map((d, i) => (
          <path
            key={d.slice(0, 24)}
            d={d}
            pathLength="1"
            className={`ui-brand-loader__part ui-brand-loader__part--${i}`}
          />
        ))}
        <g clipPath={`url(#clip${uid})`}>
          <rect className="ui-brand-loader__shine" x="-160" y="-20" width="140" height="340" fill={`url(#shine${uid})`} />
        </g>
      </svg>
      {showLabel ? <span className="ui-brand-loader__label">{label}</span> : null}
    </span>
  );
  return page ? <div className="ui-brand-loader-page">{mark}</div> : mark;
}

// src/design/BrandLogo.js
// The Taurus logo in vector: the emblem (design/brandMark.js) in brand red + "TAURUS" in light,
// spaced capitals. Replaces public/logo/navbar-logo.svg (a dark-red picture, hard to read on the
// dark UI, blurry on TVs). variant: "full" | "mark" (emblem only). height: CSS length of the emblem.
import React from 'react';
import { EMBLEM_PATHS, EMBLEM_VIEWBOX } from './brandMark';

export default function BrandLogo({ variant = 'full', height, className = '', title = 'Taurus' }) {
  return (
    <span className={`ui-logo ui-logo--${variant} ${className}`} role="img" aria-label={title} style={height ? { '--logo-height': height } : undefined}>
      <svg className="ui-logo__mark" viewBox={EMBLEM_VIEWBOX} aria-hidden="true" focusable="false">
        {EMBLEM_PATHS.map((d) => (
          <path key={d.slice(0, 24)} d={d} />
        ))}
      </svg>
      {variant === 'full' ? (
        <span className="ui-logo__word" aria-hidden="true">
          TAURUS
        </span>
      ) : null}
    </span>
  );
}

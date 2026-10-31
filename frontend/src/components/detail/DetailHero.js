// src/components/detail/DetailHero.js
// Top of a movie / show page: full-bleed artwork fading into the page (the portrait poster on
// phones), type, title, meta line, genres, description (expandable), credits, actions.
// Shared by MovieDetail and TVShowDetail so both pages look like one product.
import React, { useState } from 'react';
import { Badge, Rating } from '../../design';
import { tmdbImage, tmdbSrcSet, IMG } from '../../utils/tmdbImage';
import './detail.css';

const LONG_DESCRIPTION = 260; // characters: longer ones are clamped with a "More" toggle

/** "Drama, Comedy" | ["Drama"] -> ["Drama", "Comedy"] */
export function splitGenres(genre) {
  if (Array.isArray(genre)) return genre.map((g) => (typeof g === 'string' ? g : g?.name)).filter(Boolean);
  return String(genre || '')
    .split(',')
    .map((g) => g.trim())
    .filter(Boolean);
}

export default function DetailHero({ title, kind, meta = [], credits = [], actions }) {
  const [imageLoaded, setImageLoaded] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const wide = title.landscape_image || title.landscape_url || '';
  const poster = title.poster || '';
  const art = wide || poster;
  const description = (title.description || '').trim();
  const isLong = description.length > LONG_DESCRIPTION;
  const genres = splitGenres(title.genre || title.genres).slice(0, 4);
  const rating = Number(title.rating ?? title.vote_average);

  return (
    <section className="detail-hero" aria-labelledby="detail-title">
      <div className="detail-hero__media" aria-hidden="true">
        {art ? (
          <picture>
            {wide && poster ? (
              <source
                media="(max-width: 600px) and (orientation: portrait)"
                srcSet={tmdbSrcSet(poster, [342, 500, 780]) || tmdbImage(poster, IMG.posterLarge)}
                sizes="100vw"
              />
            ) : null}
            <img
              className={`detail-hero__image${wide ? '' : ' detail-hero__image--poster'}${imageLoaded ? ' is-loaded' : ''}`}
              src={tmdbImage(art, wide ? IMG.backdropHero : IMG.posterLarge)}
              srcSet={wide ? tmdbSrcSet(wide, [780, 1280]) : undefined}
              sizes="100vw"
              alt=""
              fetchpriority="high"
              decoding="async"
              onLoad={() => setImageLoaded(true)}
            />
          </picture>
        ) : null}
        <div className="detail-hero__scrim" />
      </div>

      <div className="detail-hero__content">
        <div className="detail-hero__kicker">
          <Badge tone="brand">{kind === 'tv' ? 'Series' : 'Film'}</Badge>
        </div>

        <h1 id="detail-title" className="detail-hero__title">
          {title.title}
        </h1>

        <div className="detail-hero__meta">
          {Number.isFinite(rating) && rating > 0 ? <Rating value={rating} /> : null}
          {meta.filter(Boolean).map((m) => (
            <span key={m}>{m}</span>
          ))}
        </div>

        {genres.length ? (
          <ul className="detail-hero__genres" aria-label="Genres">
            {genres.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        ) : null}

        {actions ? <div className="ui-actions detail-hero__actions">{actions}</div> : null}

        {description ? (
          <div className="detail-hero__description">
            <p className={isLong && !expanded ? 'is-clamped' : undefined}>{description}</p>
            {isLong ? (
              <button type="button" className="detail-hero__more" aria-expanded={expanded} onClick={() => setExpanded((v) => !v)}>
                {expanded ? 'Less' : 'More'}
              </button>
            ) : null}
          </div>
        ) : null}

        {credits.filter((c) => c && c.value).length ? (
          <dl className="detail-hero__credits">
            {credits
              .filter((c) => c && c.value)
              .map((c) => (
                <div key={c.label}>
                  <dt>{c.label}</dt>
                  <dd>{c.value}</dd>
                </div>
              ))}
          </dl>
        ) : null}
      </div>
    </section>
  );
}

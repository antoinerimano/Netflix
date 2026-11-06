// src/components/detail/CastRow.js
// Cast as a horizontal row of portrait cards (scrolls on phones, wraps nowhere). Each card opens
// the actor's page. Class names movie-detail-cast-* are kept: tv/focus.css styles their focus.
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { SectionTitle } from '../../design';

const FALLBACK_ACTOR_IMG = '/actor-default.png';

const profileUrl = (path, size = 'w185') => {
  if (!path) return '';
  if (/^https?:\/\//.test(path)) return path;
  return `https://image.tmdb.org/t/p/${size}${String(path).startsWith('/') ? path : `/${path}`}`;
};

/** actors: [{ name, character, profile_path, tmdb_id }] or names */
export function castObjects(cast, { byPopularity = false } = {}) {
  if (!Array.isArray(cast)) return [];
  const list = cast
    .map((x) => (typeof x === 'string' ? { name: x } : x))
    .filter((x) => x && (x.name || x.english_name));
  // most known first (how many titles the actor is in)
  return byPopularity ? list.sort((a, b) => (b.appearances ?? 0) - (a.appearances ?? 0)) : list;
}

export default function CastRow({ cast, limit = 20 }) {
  const navigate = useNavigate();
  const { t } = useTranslation('catalog');
  if (!cast?.length) return null;

  return (
    <section className="detail-section">
      <SectionTitle>{t('detail.cast')}</SectionTitle>
      <ul className="detail-cast">
        {cast.slice(0, limit).map((a, idx) => {
          const name = a?.name || a?.english_name || '';
          const img = profileUrl(a?.profile_path || a?.profile || a?.photo || '');
          const canOpen = !!a?.tmdb_id;
          return (
            <li key={`${name}-${idx}`}>
              <div
                className="movie-detail-cast-card"
                role={canOpen ? 'button' : undefined}
                tabIndex={canOpen ? 0 : undefined}
                aria-label={canOpen ? `${name}${a?.character ? `, ${a.character}` : ''}` : undefined}
                onClick={() => canOpen && navigate(`/actor/${a.tmdb_id}`)}
              >
                <div className="movie-detail-cast-photo">
                  <img
                    loading="lazy"
                    src={img || FALLBACK_ACTOR_IMG}
                    alt=""
                    onError={(e) => {
                      e.currentTarget.onerror = null;
                      e.currentTarget.src = FALLBACK_ACTOR_IMG;
                    }}
                  />
                </div>
                <div className="movie-detail-cast-name">{name}</div>
                {a?.character ? <div className="movie-detail-cast-role">{a.character}</div> : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

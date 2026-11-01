// src/components/ActorDetails.js
// Actor page: photo, name, how many titles, then their movies and shows (poster grids with the
// character played), most popular first.
import React, { useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from './Navbar';
import Footer from './Footer';
import MovieCard from './MovieCard';
import { fetchActor } from '../api/titlesApi';
import { Button, EmptyState, SectionTitle, Skeleton, friendlyError } from '../design';
import './PosterCard.css';
import './ActorDetails.css';

const FALLBACK_ACTOR_IMG = '/actor-default.png';
const photoUrl = (path, size = 'h632') => {
  if (!path) return '';
  if (/^https?:\/\//.test(path)) return path;
  return `https://image.tmdb.org/t/p/${size}${String(path).startsWith('/') ? path : `/${path}`}`;
};
const isTv = (t) => String(t?.type || '').toLowerCase() === 'tv';
// title: shown; analyticsTitle: the same in every language
function TitleGrid({ title, analyticsTitle, items, surface }) {
  const { t } = useTranslation('catalog');
  if (!items.length) return null;
  return (
    <section className="actor__section">
      <SectionTitle>{title}</SectionTitle>
      <div className="poster-grid actor__grid">
        {items.map((item, idx) => (
          <MovieCard
            key={item.id}
            movie={item}
            note={item.character ? t('actor.as', { character: item.character }) : ''}
            priority={idx < 8}
            analytics={{ surface, position: idx, row_title: analyticsTitle }}
          />
        ))}
      </div>
    </section>
  );
}

export default function ActorDetail() {
  const { t, i18n } = useTranslation('catalog');
  const { tmdbId } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetchActor(tmdbId)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [tmdbId, i18n.resolvedLanguage]);

  const items = useMemo(() => data?.results || [], [data]);
  const movies = useMemo(() => items.filter((x) => !isTv(x)), [items]);
  const shows = useMemo(() => items.filter(isTv), [items]);
  const actor = data?.actor;
  const name = actor?.name || '';

  let content;
  if (loading) {
    content = (
      <>
        <header className="actor__head" aria-busy="true">
          <Skeleton variant="circle" className="actor__photo" />
          <div className="actor__intro">
            <Skeleton variant="text" width="5rem" />
            <Skeleton width="min(20rem, 70vw)" height="2.75rem" />
            <Skeleton variant="text" width="12rem" />
          </div>
        </header>
        <div className="poster-grid actor__grid">
          {Array.from({ length: 12 }, (_, i) => (
            <Skeleton key={i} style={{ aspectRatio: '2 / 3' }} />
          ))}
        </div>
      </>
    );
  } else if (error || !items.length) {
    content = (
      <EmptyState
        page
        tone={error ? 'error' : 'empty'}
        title={error ? t('actor.loadError') : t('actor.emptyTitle')}
        actions={<Button variant="ghost" onClick={() => navigate(-1)}>{t('actions.goBack')}</Button>}
      >
        {error ? friendlyError(error, 'actor') : name ? t('actor.emptyText', { name }) : t('actor.emptyTextUnknown')}
      </EmptyState>
    );
  } else {
    content = (
      <>
        <header className="actor__head">
          <img
            className="actor__photo"
            src={photoUrl(actor?.profile_path) || FALLBACK_ACTOR_IMG}
            alt=""
            onError={(e) => {
              e.currentTarget.onerror = null;
              e.currentTarget.src = FALLBACK_ACTOR_IMG;
            }}
          />
          <div className="actor__intro">
            <p className="actor__kicker">{t('actor.kicker')}</p>
            <h1 className="actor__name">{name || t('actor.unknown')}</h1>
            <p className="actor__stats">
              {[movies.length ? t('actor.movieCount', { count: movies.length }) : '', shows.length ? t('actor.showCount', { count: shows.length }) : '']
                .filter(Boolean)
                .join(' · ')}
            </p>
            {name ? (
              <div className="ui-actions actor__actions">
                {movies.length ? (
                  <Button variant="glass" size="sm" to={`/movies?actor=${encodeURIComponent(name)}`}>
                    {t('actor.browseMovies', { name: name.split(' ')[0] })}
                  </Button>
                ) : null}
                {shows.length ? (
                  <Button variant="glass" size="sm" to={`/tv?actor=${encodeURIComponent(name)}`}>
                    {t('actor.browseShows', { name: name.split(' ')[0] })}
                  </Button>
                ) : null}
              </div>
            ) : null}
          </div>
        </header>
        <TitleGrid title={t('common:nav.movies')} analyticsTitle="Movies" items={movies} surface="actor_movies" />
        <TitleGrid title={t('common:nav.tv')} analyticsTitle="TV Shows" items={shows} surface="actor_shows" />
      </>
    );
  }

  return (
    <div className="browse actor">
      <Navbar />
      <main className="actor__main">{content}</main>
      <Footer />
    </div>
  );
}

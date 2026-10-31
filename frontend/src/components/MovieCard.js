// src/components/MovieCard.js
// Poster card for grids (Movies, TV Shows, My List, actor pages): 2:3 poster, title and
// year · rating under it, options sheet (hold OK, right click, long press, "⋯").
// onRemove (My List): adds "Remove from My List" to the options.
import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { logTitleClick, logOutboundClickBeacon } from '../api/analyticsApi';
import { tmdbImage, tmdbSrcSet, IMG } from '../utils/tmdbImage';
import { MoreIcon, StarIcon } from '../design/icons';
import TitleOptions from './TitleOptions';
import useCardOptions from './useCardOptions';
import './PosterCard.css';

const yearOf = (t) =>
  t?.release_year || String(t?.release_date || t?.first_air_date || '').match(/\d{4}/)?.[0] || '';

// note: an extra line under the title (actor page: the character played)
const MovieCard = ({ movie, onRemove, onClick, analytics, priority = false, note = '' }) => {
  const navigate = useNavigate();
  const { open, setOpen, cardProps, guardClick } = useCardOptions();
  const [artFailed, setArtFailed] = useState(false);

  const isTv = String(movie?.type || movie?.media_type || '').toLowerCase() === 'tv' || !!movie?.first_air_date;
  const detailPath = `/${isTv ? 'tv' : 'movies'}/${movie.id}`;
  const year = yearOf(movie);
  const rating = Number(movie?.rating ?? movie?.vote_average);
  const art = movie.poster || '';

  const logClick = () => {
    if (!movie?.id) return;
    logTitleClick({
      title_id: movie.id,
      surface: analytics?.surface || 'unknown',
      position: analytics?.position,
      row_title: analytics?.row_title,
    });
  };

  const handleRootClick = () => {
    logClick();
    if (typeof onClick === 'function') onClick();
    else navigate(detailPath);
  };

  return (
    <>
      <div
        className="poster-card"
        tabIndex={0}
        role="button"
        aria-label={[movie.title, year, Number.isFinite(rating) && rating > 0 ? `rated ${rating.toFixed(1)}` : '']
          .filter(Boolean)
          .join(', ')}
        onClick={guardClick(handleRootClick)}
        {...cardProps}
      >
        <div className="poster-card__art">
          {/* shown when there is no poster / it fails (the image covers it otherwise) */}
          <span className="poster-card__fallback" aria-hidden="true">{movie.title}</span>
          {art && !artFailed ? (
            <img
              src={tmdbImage(art, IMG.poster)}
              srcSet={tmdbSrcSet(art, [185, 342, 500])}
              sizes="(max-width: 600px) 33vw, (max-width: 1200px) 20vw, 200px"
              alt=""
              loading={priority ? 'eager' : 'lazy'}
              decoding="async"
              onError={() => setArtFailed(true)}
            />
          ) : null}
          <button
            type="button"
            tabIndex={-1}
            className="poster-card__more"
            aria-label={`Options for ${movie.title}`}
            title="Options"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(true);
            }}
          >
            <MoreIcon />
          </button>
        </div>
        <div className="poster-card__caption" aria-hidden="true">
          <span className="poster-card__title">{movie.title}</span>
          <span className="poster-card__meta">
            {year}
            {Number.isFinite(rating) && rating > 0 ? (
              <span className="poster-card__rating">
                <StarIcon />
                {rating.toFixed(1)}
              </span>
            ) : null}
          </span>
          {note ? <span className="poster-card__note">{note}</span> : null}
        </div>
      </div>

      <TitleOptions
        open={open}
        title={{ ...movie, type: isTv ? 'tv' : 'movie' }}
        surface={analytics?.surface || 'grid'}
        onClose={() => setOpen(false)}
        onPlay={() => {
          const url = `/watch/${movie.id}`;
          logOutboundClickBeacon({ title_id: movie.id, surface: `${analytics?.surface || 'grid'}_options`, provider: 'watch_page', url });
          navigate(url);
        }}
        onInfo={() => {
          logClick();
          navigate(detailPath);
        }}
        onRemoveFromList={onRemove ? () => onRemove(movie.id) : undefined}
      />
    </>
  );
};

export default MovieCard;

import React, { useEffect, useState, useMemo } from 'react';
import { fetchMovieById } from '../api/titlesApi';
import { logOutboundClickBeacon, logActionBeacon } from '../api/analyticsApi';
import { fetchMyList, setInMyList } from '../api/myListApi';
import RatingButtons from './RatingButtons';
import { useParams, useNavigate } from "react-router-dom";


import './MovieDetail.css';
import Navbar from './Navbar';
import { Button, EmptyState, Spinner, friendlyError } from '../design';
import { PlayIcon, PlusIcon, CheckIcon } from '../design/icons';
import { tmdbImage, tmdbSrcSet, tmdbBackground, IMG } from '../utils/tmdbImage';

/* --- Helpers --- */
function formatMinutes(mins) {
  if (mins === null || mins === undefined) return '';
  const h = Math.floor(mins / 60);
  const m = Math.floor(mins % 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}
function getNames(list, key = 'name') {
  if (!list) return [];
  if (Array.isArray(list)) {
    return list.map((x) => (typeof x === 'string' ? x : x?.[key] || x?.english_name)).filter(Boolean);
  }
  if (typeof list === 'object') return Object.values(list).filter(Boolean).map(String);
  return [];
}

const FALLBACK_ACTOR_IMG = "/actor-default.png";

const tmdbProfileUrl = (profilePath, size = "w185") => {
  if (!profilePath) return "";
  const p = String(profilePath).startsWith("/") ? profilePath : `/${profilePath}`;
  return `https://image.tmdb.org/t/p/${size}${p}`;
};

const getCastObjects = (cast) => {
  if (!Array.isArray(cast)) return [];
  return cast
    .map((x) => (typeof x === "string" ? { name: x } : x))
    .filter((x) => x && (x.name || x.english_name))
    // Sort by global appearances (how many titles this actor is in) — most popular first
    .sort((a, b) => (b.appearances ?? 0) - (a.appearances ?? 0));
};


/* --- Trailer embed --- */
function TrailerEmbed({ url }) {
  if (!url) return null;
  const ytMatch =
    url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{6,})/) ||
    url.match(/[?&]v=([A-Za-z0-9_-]{6,})/);
  if (ytMatch?.[1]) {
    return (
      <div className="trailer-embed">
        <iframe
          src={`https://www.youtube.com/embed/${ytMatch[1]}?rel=0&modestbranding=1`}
          title="Trailer"
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          loading="lazy"
        />
      </div>
    );
  }
  if (/\.(mp4|m3u8)(\?|#|$)/i.test(url)) {
    return (
      <div className="trailer-embed">
        <video controls preload="none" src={url} />
      </div>
    );
  }
  return (
    <div className="trailer-embed">
      <iframe src={url} title="Trailer" loading="lazy" />
    </div>
  );
}

const MovieDetail = () => {
  const { movieId } = useParams();
  const [movie, setMovie] = useState(null);
  const [loading, setLoading] = useState(true);

  const castObjs = useMemo(() => getCastObjects(movie?.actors), [movie]);
  const navigate = useNavigate();



  const activeProfileId = localStorage.getItem('activeProfileId');
  const [isInList, setIsInList] = useState(false);

  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    setLoadError(null);
    fetchMovieById(parseInt(movieId, 10))
      .then((data) => {
        setMovie(data);
        setLoading(false);
      })
      .catch((err) => {
        console.error('Failed to fetch movie:', err);
        setLoadError(err);
        setLoading(false);
      });
  }, [movieId]);

  // My List (saved on the server, per profile)
  useEffect(() => {
    if (!movie?.id || !activeProfileId) return;
    let alive = true;
    fetchMyList(activeProfileId)
      .then((items) => alive && setIsInList(items.some((i) => i.id === movie.id)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [movie?.id, activeProfileId]);

  const handleToggleList = () => {
    if (!movie || !activeProfileId) return;

    const nextIsAdd = !isInList;

    logActionBeacon({
      title_id: movie.id,
      action: 'add_to_list',
      surface: 'movie_detail',
      provider: nextIsAdd ? 'add' : 'remove',
    });

    setIsInList(nextIsAdd); // instant feedback, undone if the server refuses
    setInMyList(activeProfileId, movie.id, nextIsAdd).catch(() => setIsInList(!nextIsAdd));
  };

  const countryList = useMemo(() => getNames(movie?.production_countries), [movie]);

  if (loading) {
    return (
      <div className="loading-container">
        <Spinner />
      </div>
    );
  }

  if (!movie) {
    return (
      <div className="homepage">
        <Navbar />
        <EmptyState
          page
          tone="error"
          title="Movie unavailable"
          actions={
            <>
              <Button variant="primary" to="/movies">Browse movies</Button>
              <Button variant="ghost" onClick={() => navigate(-1)}>Go back</Button>
            </>
          }
        >
          {friendlyError(loadError || { status: 404 }, 'this movie')}
        </EmptyState>
      </div>
    );
  }

  const runtime = formatMinutes(movie.runtime_minutes);

  return (
    <div className="homepage">
      <Navbar />
      <div className="movie-detail-container">
        <div className="movie-detail-background">
          <div
            className="movie-detail-backdrop"
            style={{ backgroundImage: tmdbBackground(movie.landscape_image || movie.poster, IMG.backdropHero) }}
          />
          <div className="movie-detail-overlay"></div>
        </div>

        <div className="movie-detail-content">
          <img
            className="movie-detail-poster"
            src={tmdbImage(movie.poster, IMG.posterLarge)}
            srcSet={tmdbSrcSet(movie.poster, [342, 500, 780])}
            sizes="(max-width: 768px) 60vw, 20vw"
            alt={movie.title}
          />
          <div className="movie-detail-info">
            <h1 className="movie-detail-title">
              {movie.title}{' '}
              {movie.release_date ? `(${new Date(movie.release_date).getFullYear()})` : ''}
            </h1>
            <p className="movie-detail-description">{movie.description}</p>
            <div className="movie-detail-meta">
              {runtime ? <span>⏱ {runtime}</span> : null}
              {movie.rating ? <span>⭐ {Number(movie.rating).toFixed(1)}</span> : null}
              {movie.original_language ? <span>Lang: {movie.original_language.toUpperCase()}</span> : null}
              {movie.genre ? <span>Genre: {movie.genre}</span> : null}
            </div>

            <p className="movie-detail-director">
              <strong>Director:</strong> {movie.director}
            </p>

            {countryList.length ? (
              <div className="movie-detail-locale">
                <strong>Countries:</strong> {countryList.join(', ')}
              </div>
            ) : null}

                        {castObjs.length ? (
              <div className="movie-detail-cast">
                <h3 className="section-title">Cast</h3>

                <div className="movie-detail-cast-grid">
                  {castObjs.slice(0, 8).map((a, idx) => {
                    const name = a?.name || a?.english_name || "";
                    const img = tmdbProfileUrl(a?.profile_path || a?.profile || a?.photo || "");
                    return (
                      <div
                        className="movie-detail-cast-card"
                        key={`${name}-${idx}`}
                        role="button"
                        tabIndex={0}
                        onClick={() => {
                          if (!a?.tmdb_id) return;
                          navigate(`/actor/${a.tmdb_id}`);
                        }}
                      >
                        <div className="movie-detail-cast-photo">
                          <img
                            loading="lazy"
                            src={img || FALLBACK_ACTOR_IMG}
                            alt={name}
                            onError={(e) => { e.currentTarget.src = FALLBACK_ACTOR_IMG; }}
                          />
                        </div>
                        <div className="movie-detail-cast-name">{name}</div>
                        {a?.character ? <div className="movie-detail-cast-role">{a.character}</div> : null}
                      </div>

                    );
                  })}
                </div>
              </div>
            ) : null}

            {movie.trailer_url ? (
              <div className="movie-detail-trailer">
                <h3 className="section-title">Trailer</h3>
                <TrailerEmbed url={movie.trailer_url} />
              </div>
            ) : null}

            {/* actions: one primary (Watch), the rest as round icon buttons */}
            <div className="ui-actions movie-detail-actions">
              <Button
                variant="primary"
                size="lg"
                icon={<PlayIcon />}
                onClick={() => {
                  const watchUrl = `/watch/${movie.id}`;

                  logOutboundClickBeacon({
                    title_id: movie.id,
                    surface: 'movie_detail',
                    provider: 'watch_page',
                    url: watchUrl,
                  });

                  window.location.href = watchUrl;
                }}
              >
                Watch
              </Button>
              <Button
                variant="glass"
                icon={isInList ? <CheckIcon /> : <PlusIcon />}
                pressed={isInList}
                label={isInList ? 'In My List' : 'Add to My List'}
                onClick={handleToggleList}
              />
              <RatingButtons titleId={movie.id} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MovieDetail;
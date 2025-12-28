import React, { useEffect, useState, useMemo } from 'react';
import { fetchMovieById } from '../api/titlesApi';
import { logOutboundClickBeacon, logActionBeacon } from '../api/analyticsApi';
import { useParams, useNavigate } from "react-router-dom";


import './MovieDetail.css';
import Navbar from './Navbar';

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
  // garde seulement les objets avec name (ou string -> convert)
  return cast
    .map((x) => (typeof x === "string" ? { name: x } : x))
    .filter((x) => x && (x.name || x.english_name));
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
  const [list, setList] = useState(() => {
    const storedList = localStorage.getItem(`userList_${activeProfileId}`);
    return storedList ? JSON.parse(storedList) : [];
  });
  const [isInList, setIsInList] = useState(false);

  useEffect(() => {
    fetchMovieById(parseInt(movieId, 10))
      .then((data) => {
        setMovie(data);
        setLoading(false);
        setIsInList(list.some((item) => item.id === data.id));
      })
      .catch((err) => {
        console.error('Failed to fetch movie:', err);
        setLoading(false);
      });
  }, [movieId, list]);

  const handleToggleList = () => {
    if (!movie) return;

    const nextIsAdd = !isInList;

    logActionBeacon({
      title_id: movie.id,
      action: 'add_to_list',
      surface: 'movie_detail',
      provider: nextIsAdd ? 'add' : 'remove',
    });

    const pid = localStorage.getItem('activeProfileId');
    if (!pid) return;

    const raw = localStorage.getItem(`userList_${pid}`);
    const current = raw ? JSON.parse(raw) : [];

    const exists = current.some((i) => i?.id === movie.id);
    const updated = exists ? current.filter((i) => i?.id !== movie.id) : [...current, movie];

    localStorage.setItem(`userList_${pid}`, JSON.stringify(updated));
    setList(updated);
    setIsInList(!exists);

    window.dispatchEvent(new Event('activeProfileChanged'));
  };

  const countryList = useMemo(() => getNames(movie?.production_countries), [movie]);

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner"></div>
      </div>
    );
  }

  if (!movie) return <div>Movie not found</div>;

  const runtime = formatMinutes(movie.runtime_minutes);

  return (
    <div className="homepage">
      <Navbar />
      <div className="movie-detail-container">
        <div className="movie-detail-background">
          <div
            className="movie-detail-backdrop"
            style={{ backgroundImage: `url(${movie.landscape_image || movie.poster})` }}
          />
          <div className="movie-detail-overlay"></div>
        </div>

        <div className="movie-detail-content">
          <img className="movie-detail-poster" src={movie.poster} alt={movie.title} />
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
                    console.log("ACTOR CLICK DATA:", a);
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
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && a?.tmdb_id) window.location.assign(`/actor/${a.tmdb_id}`);
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

            {/* ✅ garde classes + ajoute beacon */}
            <div className="provider-row">
              <button
                className="movie-detail-play-button btn-provider-like-play"
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
                <svg viewBox="0 0 24 24" stroke="#ffffff" className="play-icon" fill="none">
                  <path
                    d="M16.6 9.3C18.1 10.2 18.8 10.6 19.1 11.2c.2.5.2 1.1 0 1.6-.2.5-.9 1-2.5 1.9L9.9 18.9c-1.6 1-2.4 1.5-3.1 1.5-.6 0-1.1-.3-1.5-.8C5 19.1 5 18.1 5 16.2V7.8C5 5.9 5 4.9 5.3 4.4c.4-.5.9-.8 1.5-.8.7 0 1.5.5 3.1 1.4l6.7 4.3z"
                    strokeWidth="2"
                    strokeLinejoin="round"
                  />
                </svg>
                <span>Watch</span>
              </button>
            </div>

            <button className="movie-detail-add-button" onClick={handleToggleList}>
              {isInList ? 'Remove from My List' : 'Add to My List'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default MovieDetail;

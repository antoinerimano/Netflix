// Hero.jsx
import React, { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import './Hero.css';
import { logOutboundClickBeacon, logTitleClick } from '../api/analyticsApi';

const HOVER_IN_DELAY_MS = 120;
const STALL_HIDE_MS = 900;

// ✅ TMDB image base (secure)
const TMDB_IMG_BASE = 'https://image.tmdb.org/t/p/';
// Choisis ta taille : "w1280" (recommandé) ou "original" (plus lourd)
const TMDB_BACKDROP_SIZE = 'w1280';

// ✅ clé TMDB (frontend)
const TMDB_API_KEY = process.env.REACT_APP_TMDB_API_KEY;

const isValidTrailerUrl = (url) => {
  if (typeof url !== "string") return false;
  const s = url.trim();
  if (!s) return false;
  const lower = s.toLowerCase();
  if (lower === "null" || lower === "undefined") return false;
  return /^https?:\/\//i.test(s);
};

const normalizePath = (p) => {
  if (!p) return '';
  const s = String(p).trim();
  if (!s) return '';
  return s.startsWith('/') ? s : `/${s}`;
};

const tmdbImageUrl = (filePath, size = TMDB_BACKDROP_SIZE) => {
  const p = normalizePath(filePath);
  if (!p) return '';
  return `${TMDB_IMG_BASE}${size}${p}`;
};

// Si tu as une URL TMDB mais en petite taille (w185, w300, w500, ...), upgrade en w1280
const upgradeTmdbSizedUrl = (url, size = TMDB_BACKDROP_SIZE) => {
  if (typeof url !== 'string') return '';
  const s = url.trim();
  if (!s) return '';
  if (!/image\.tmdb\.org\/t\/p\//i.test(s)) return s;
  return s.replace(/\/t\/p\/w\d+\//i, `/t/p/${size}/`);
};

const guessTmdbType = (movie) => {
  // essaie de deviner si c’est un film ou une série
  const t = String(movie?.title_type || movie?.type || movie?.media_type || '').toLowerCase();
  if (t.includes('tv') || t.includes('show') || t === 'series') return 'tv';
  return 'movie';
};

const Hero = ({ hero }) => {
  const movie = hero;

  const [isHovering, setIsHovering] = useState(false);
  const [showVideo, setShowVideo] = useState(false);
  const [isMuted, setIsMuted] = useState(true);
  const [videoFailed, setVideoFailed] = useState(false);

  // ✅ background image “finale” (TMDB HD si possible)
  const [bgUrl, setBgUrl] = useState('');

  const videoRef = useRef(null);
  const hoverInTimer = useRef(null);
  const stallTimer = useRef(null);

  const trailerUrl = useMemo(() => {
    const raw = movie?.trailer_clip_url;
    return typeof raw === 'string' ? raw.trim() : '';
  }, [movie?.trailer_clip_url]);

  const hasTrailer = useMemo(() => {
    return !videoFailed && isValidTrailerUrl(trailerUrl);
  }, [trailerUrl, videoFailed]);

  const safeClear = (tRef) => {
    if (tRef.current) {
      clearTimeout(tRef.current);
      tRef.current = null;
    }
  };

  const tryPlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;

    try { v.currentTime = 0; } catch {}
    const p = v.play?.();
    if (p && typeof p.catch === 'function') p.catch(() => {});
  }, []);

  // reset fail state quand on change de hero
  useEffect(() => {
    setVideoFailed(false);
    setShowVideo(false);
    setIsHovering(false);
    safeClear(hoverInTimer);
    safeClear(stallTimer);

    const v = videoRef.current;
    if (v) {
      try { v.pause(); } catch {}
      try { v.currentTime = 0; } catch {}
    }
  }, [movie?.id]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = isMuted;
  }, [isMuted]);

  const handleMouseEnter = () => {
    if (!hasTrailer) return;
    setIsHovering(true);

    safeClear(hoverInTimer);
    hoverInTimer.current = setTimeout(() => {
      tryPlay();
    }, HOVER_IN_DELAY_MS);
  };

  const handleMouseLeave = () => {
    setIsHovering(false);
    safeClear(hoverInTimer);
    safeClear(stallTimer);
    setShowVideo(false);

    const v = videoRef.current;
    if (v) {
      try { v.pause(); } catch {}
      try { v.currentTime = 0; } catch {}
    }
  };

  useEffect(() => {
    return () => {
      safeClear(hoverInTimer);
      safeClear(stallTimer);
    };
  }, []);

  const handleLoadedMetadata = () => {
    if (isHovering) tryPlay();
  };

  const handlePlaying = () => {
    safeClear(stallTimer);
    setShowVideo(true);
  };

  const startStallWatchdog = () => {
    safeClear(stallTimer);
    stallTimer.current = setTimeout(() => {
      if (!isHovering) return;
      setShowVideo(false);
      const v = videoRef.current;
      if (v) {
        try { v.pause(); } catch {}
      }
    }, STALL_HIDE_MS);
  };

  const handleWaiting = startStallWatchdog;
  const handleStalled = startStallWatchdog;

  const handleError = () => {
    safeClear(stallTimer);
    setShowVideo(false);
    setVideoFailed(true);
  };

  const handleEnded = () => {
    const v = videoRef.current;
    if (isHovering && v) {
      tryPlay();
    } else {
      setShowVideo(false);
    }
  };

  const toggleMute = useCallback(() => {
    const v = videoRef.current;
    const next = !isMuted;
    setIsMuted(next);

    if (v) {
      v.muted = next;
      if (!next && v.paused) {
        const p = v.play?.();
        if (p && typeof p.catch === 'function') p.catch(() => {});
      }
    }
  }, [isMuted]);

  // ✅ Résolution du background en HD via TMDB si possible
  useEffect(() => {
    let alive = true;
    const ctrl = typeof AbortController !== 'undefined' ? new AbortController() : null;

    const resolveBg = async () => {
      const fallbackRaw = movie?.landscape_image || movie?.landscape_url || '';
      const fallback = upgradeTmdbSizedUrl(fallbackRaw, TMDB_BACKDROP_SIZE) || fallbackRaw || '';

      // 1) Si on a déjà backdrop_path : direct
      if (movie?.backdrop_path) {
        const u = tmdbImageUrl(movie.backdrop_path, TMDB_BACKDROP_SIZE);
        if (alive) setBgUrl(u || fallback);
        return;
      }

      // 2) Si on a une URL TMDB “petite” en DB : upgrade sans API
      if (typeof fallbackRaw === 'string' && /image\.tmdb\.org\/t\/p\/w\d+\//i.test(fallbackRaw)) {
        const u = upgradeTmdbSizedUrl(fallbackRaw, TMDB_BACKDROP_SIZE);
        if (alive) setBgUrl(u || fallback);
        return;
      }

      // 3) Sinon : fetch TMDB par tmdb_id si dispo + clé dispo
      const tmdbId = movie?.tmdb_id ?? movie?.tmbd_id ?? movie?.tmdbId ?? movie?.tmbdId;
      if (!TMDB_API_KEY || !tmdbId) {
        if (alive) setBgUrl(fallback);
        return;
      }

      const mediaType = guessTmdbType(movie); // "movie" ou "tv"
      const url = `https://api.themoviedb.org/3/${mediaType}/${Number(tmdbId)}?api_key=${TMDB_API_KEY}`;

      try {
        const r = await fetch(url, { signal: ctrl?.signal });
        if (!r.ok) throw new Error(`TMDB ${r.status}`);
        const j = await r.json();

        const backdrop = j?.backdrop_path;
        const poster = j?.poster_path;

        const best = tmdbImageUrl(backdrop || poster, TMDB_BACKDROP_SIZE) || fallback;
        if (alive) setBgUrl(best);
      } catch (e) {
        // abort ou erreur : fallback DB
        if (alive) setBgUrl(fallback);
      }
    };

    resolveBg();

    return () => {
      alive = false;
      if (ctrl) ctrl.abort();
    };
  }, [
    movie?.id,
    movie?.backdrop_path,
    movie?.landscape_image,
    movie?.landscape_url,
    movie?.tmdb_id,
    movie?.tmbd_id,
    movie?.tmdbId,
    movie?.tmbdId,
    movie?.title_type,
    movie?.type,
    movie?.media_type,
  ]);

  const watchUrl = movie?.id ? `/watch/${movie.id}` : null;

  return (
    <div
      className="hero"
      style={{
        backgroundImage: bgUrl ? `url('${bgUrl}')` : undefined,
        backgroundSize: 'cover',
        backgroundPosition: 'center',
        backgroundRepeat: 'no-repeat',
      }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {hasTrailer && (
        <video
          key={movie?.id || trailerUrl} // ✅ force reset vidéo quand hero change
          ref={videoRef}
          src={trailerUrl}
          muted={isMuted}
          playsInline
          preload="metadata"
          loop
          onClick={toggleMute}
          onLoadedMetadata={handleLoadedMetadata}
          onPlaying={handlePlaying}
          onWaiting={handleWaiting}
          onStalled={handleStalled}
          onError={handleError}
          onEnded={handleEnded}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            zIndex: 0,
            opacity: showVideo ? 1 : 0,
            transition: 'opacity 180ms ease-out',
            pointerEvents: 'auto',
            cursor: 'pointer',
          }}
        />
      )}

      {hasTrailer && (
        <button
          className="unmute-btn"
          onClick={toggleMute}
          aria-label={isMuted ? 'Unmute trailer' : 'Mute trailer'}
          title={isMuted ? 'Unmute' : 'Mute'}
        >
          {isMuted ? '🔇' : '🔊'}
        </button>
      )}

      <div className="hero-overlay" style={{ position: 'relative', zIndex: 33333 }}>
        <h1>{movie?.title}</h1>
        <p>{movie?.tagline ?? movie?.description}</p>

        <div className="hero-buttons">
          <a
            className="hero-button play-button"
            href={watchUrl || '#'}
            onClick={(e) => {
              if (!watchUrl) return;
              e.preventDefault();

              logOutboundClickBeacon({
                title_id: movie.id,
                surface: 'hero',
                provider: 'watch_page',
                url: watchUrl,
              });

              window.location.href = watchUrl;
            }}
          >
            Play
          </a>

          {movie?.id ? (
            <a
              className="hero-button info-button"
              href={`/movies/${movie.id}`}
              onClick={() => {
                logTitleClick({
                  title_id: movie.id,
                  surface: 'hero',
                  position: 0,
                  row_title: 'Hero',
                });
              }}
            >
              More Info
            </a>
          ) : (
            <button className="hero-button info-button" disabled>More Info</button>
          )}
        </div>
      </div>
    </div>
  );
};

export default Hero;

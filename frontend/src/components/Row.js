// Row.jsx
import React, { useState, useRef, useEffect, useCallback } from 'react';
import Slider from 'react-slick';
import { useNavigate } from 'react-router-dom';
import './Row.css';
import { logImpressions, logTitleClick } from '../api/analyticsApi';

const LOAD_ON_HOVER_MS = 1000;
const STALL_HIDE_MS = 900;

const tmdbSized = (url, size = "w1000") => {
  if (!url) return url;
  return url.replace("/original/", `/${size}/`);
};


const NextArrow = ({ className, style, onClick }) => (
  <div className={`${className} custom-arrow`} style={{ ...style, display: 'flex', right: '10px' }} onClick={onClick}>
    <svg viewBox="0 0 1024 1024" className="icon" xmlns="http://www.w3.org/2000/svg" fill="#ffffff" stroke="#ffffff">
      <path d="M256 120.768L306.432 64 768 512l-461.568 448L256 903.232 659.072 512z" fill="#ffffff"></path>
    </svg>
  </div>
);

const PrevArrow = ({ className, style, onClick, isVisible }) => (
  <div className={`${className} custom-arrow`} style={{ ...style, display: isVisible ? 'flex' : 'none', left: '10px' }} onClick={onClick}>
    <svg viewBox="0 0 1024 1024" className="icon" xmlns="http://www.w3.org/2000/svg" fill="#ffffff" stroke="#ffffff">
      <path d="M768 903.232l-50.432 56.768L256 512l461.568-448 50.432 56.768L364.928 512z" fill="#ffffff"></path>
    </svg>
  </div>
);

/**
 * IMPORTANT: Get the real "slidesToShow" based on react-slick responsive settings.
 * This ensures impressions match what the user actually sees.
 */
const getSlidesToShowFromSettings = (settings) => {
  const w = window.innerWidth;

  // react-slick applies responsive rules when w <= breakpoint
  const responsive = (settings.responsive || []).slice().sort((a, b) => a.breakpoint - b.breakpoint);

  for (const r of responsive) {
    if (w <= r.breakpoint && r.settings && typeof r.settings.slidesToShow === 'number') {
      return r.settings.slidesToShow;
    }
  }
  return settings.slidesToShow || 4;
};

const Row = ({ title, movies }) => {
  const navigate = useNavigate();

  const [hoveredKey, setHoveredKey] = useState(null);
  const [visibleVideoKeys, setVisibleVideoKeys] = useState(() => new Set());
  const [isMutedMap, setIsMutedMap] = useState({});
  const [loadedTrailerKeys, setLoadedTrailerKeys] = useState(() => new Set());

  const videoRefs = useRef({});
  const hoverInTimers = useRef({});
  const stallTimers = useRef({});

  const sliderRef = useRef(null);
  const [showPrevArrow, setShowPrevArrow] = useState(false);

  // --- NEW: impression de-dupe (avoid spamming) ---
  const seenImpressionsRef = useRef(new Set());
  const displayedMovies = (() => {
    const out = [];
    const seen = new Set();
    for (const t of (Array.isArray(movies) ? movies : [])) {
      const id = t?.id;
      if (!id || seen.has(id)) continue;
      seen.add(id);
      out.push(t);
    }
    return out;
  })();


  const stopAllVideos = useCallback(() => {
    Object.keys(videoRefs.current).forEach((k) => {
      const v = videoRefs.current[k];
      if (v) {
        try { v.pause(); } catch { }
        try { v.currentTime = 0; } catch { }
      }
    });
    setVisibleVideoKeys(new Set());
    Object.keys(stallTimers.current).forEach((k) => {
      clearTimeout(stallTimers.current[k]);
      delete stallTimers.current[k];
    });
  }, []);

  const tryPlay = useCallback((key) => {
    const v = videoRefs.current[key];
    if (!v) return;
    try { v.currentTime = 0; } catch { }
    const p = v.play?.();
    if (p && typeof p.catch === 'function') p.catch(() => { });
  }, []);

  const safeClear = (store, key) => {
    if (store[key]) {
      clearTimeout(store[key]);
      delete store[key];
    }
  };

  const unloadVideo = (key) => {
    const v = videoRefs.current[key];
    if (!v) return;
    try { v.pause(); } catch { }
    try { v.removeAttribute('src'); } catch { }
    try { v.load(); } catch { }
  };

  const handleMouseEnter = (key, hasTrailer) => {
    if (!hasTrailer) return;
    stopAllVideos();
    setHoveredKey(key);

    safeClear(hoverInTimers.current, key);
    hoverInTimers.current[key] = setTimeout(() => {
      setLoadedTrailerKeys((prev) => {
        const next = new Set(prev);
        next.add(key);
        return next;
      });
      setTimeout(() => tryPlay(key), 50);
    }, LOAD_ON_HOVER_MS);
  };

  const handleMouseLeave = (key) => {
    setHoveredKey(null);
    safeClear(hoverInTimers.current, key);
    safeClear(stallTimers.current, key);

    setVisibleVideoKeys((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });

    unloadVideo(key);
    setLoadedTrailerKeys((prev) => {
      if (!prev.has(key)) return prev;
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };

  useEffect(() => {
    return () => {
      Object.keys(hoverInTimers.current).forEach((k) => clearTimeout(hoverInTimers.current[k]));
      Object.keys(stallTimers.current).forEach((k) => clearTimeout(stallTimers.current[k]));
    };
  }, []);

  const onLoadedMetadata = (key) => {
    if (hoveredKey === key) tryPlay(key);
  };

  const onPlaying = (key) => {
    safeClear(stallTimers.current, key);
    setVisibleVideoKeys((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  };

  const startStallWatchdog = (key) => {
    safeClear(stallTimers.current, key);
    stallTimers.current[key] = setTimeout(() => {
      if (hoveredKey === key) {
        setVisibleVideoKeys((prev) => {
          const next = new Set(prev);
          next.delete(key);
          return next;
        });
        const v = videoRefs.current[key];
        if (v) {
          try { v.pause(); } catch { }
        }
      }
    }, STALL_HIDE_MS);
  };

  const onWaiting = (key) => startStallWatchdog(key);
  const onStalled = (key) => startStallWatchdog(key);

  const onError = (key) => {
    safeClear(stallTimers.current, key);
    setVisibleVideoKeys((prev) => {
      const next = new Set(prev);
      next.delete(key);
      return next;
    });
  };

  const onEnded = (key) => {
    if (hoveredKey === key) {
      tryPlay(key);
    } else {
      setVisibleVideoKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
    }
  };

  const toggleMute = (e, key) => {
    e.stopPropagation();
    const next = !(isMutedMap[key] ?? true);
    setIsMutedMap((m) => ({ ...m, [key]: next }));
    const v = videoRefs.current[key];
    if (v) {
      v.muted = next;
      if (!next && v.paused) {
        const p = v.play?.();
        if (p && typeof p.catch === 'function') p.catch(() => { });
      }
    }
  };

  /** -------- Dynamic routing by type -------- */
  const getDetailPath = (t) => {
    const isTv = String(t?.type || '').toLowerCase() === 'tv';
    return `/${isTv ? 'tv' : 'movies'}/${t?.id}`;
  };

  // --- NEW: log internal click before navigate ---
  const handleCardClick = (t, index) => {
    if (t?.id) {
      logTitleClick({
        title_id: t.id,
        surface: 'home_row',
        position: index,
        row_title: title,
      });
    }
    navigate(getDetailPath(t));
  };
  /** ---------------------------------------- */

  const settings = {
    dots: false,
    infinite: false,
    speed: 500,
    slidesToShow: 4,
    slidesToScroll: 1,
    nextArrow: <NextArrow />,
    prevArrow: <PrevArrow isVisible={showPrevArrow} />,
    responsive: [
      { breakpoint: 1024, settings: { slidesToShow: 3, slidesToScroll: 1 } },
      { breakpoint: 600, settings: { slidesToShow: 2, slidesToScroll: 1 } },
      { breakpoint: 480, settings: { slidesToShow: 1, slidesToScroll: 1 } },
    ],
    afterChange: (current) => {
      const totalSlides = displayedMovies.length;
      const slidesToShow = getSlidesToShowFromSettings(settings);

      setShowPrevArrow(current > 0);

      // --- NEW: log visible impressions on slide change ---
      logVisible(current, slidesToShow);

      if (current >= totalSlides - slidesToShow) {
        setTimeout(() => {
          sliderRef.current?.slickGoTo(0);
        }, 500);
      }
    },
  };

  /**
   * --- NEW: Impression logging ---
   * Logs only the visible window (current .. current+slidesToShow-1) and de-dupes.
   */
  const logVisible = useCallback((startIndex, slidesToShowOverride) => {
    const slidesToShow = slidesToShowOverride ?? getSlidesToShowFromSettings(settings);
    const visible = displayedMovies.slice(startIndex, startIndex + slidesToShow);

    const items = [];
    visible.forEach((t, offset) => {
      const id = t?.id;
      if (!id) return;

      const pos = startIndex + offset;
      const uniq = `${title}:${id}:${pos}`;
      if (seenImpressionsRef.current.has(uniq)) return;
      seenImpressionsRef.current.add(uniq);

      items.push({
        title_id: id,
        position: pos,
        row_title: title,
      });
    });

    if (items.length) {
      logImpressions({
        surface: 'home_row',
        items,
      });
    }
  }, [displayedMovies, title]); // settings is stable here (object literal), don’t include it to avoid loops

  // --- NEW: initial impressions on mount / when row changes ---
  useEffect(() => {
    const slidesToShow = getSlidesToShowFromSettings(settings);
    logVisible(0, slidesToShow);

    // Reset de-dupe if the row title changes (optional; keeps it cleaner)
    // If you prefer to keep it across renders, remove these 2 lines.
    // seenImpressionsRef.current = new Set();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title]); // when the row title changes, treat it as a new surface

  return (
    <div className="row">
      <h2>{title}</h2>
      <Slider ref={sliderRef} {...settings}>
        {displayedMovies.map((movie, index) => {
          const key = `${title}-${movie.id}-${index}`;
          const trailerSrc = movie.trailer_clip_url || '';
          const posterSrc = movie?.landscape_image || movie?.poster;

          const hasProgress = typeof movie?.progress === 'number';
          const tagline = (movie?.tagline || '').trim();
          const displayText = tagline.length > 0 ? tagline : movie?.description;
          const isTagline = tagline.length > 0;

          const rawDate = movie?.release_date || movie?.releaseDate || '';
          const releaseYear = String(rawDate).match(/\d{4}/)?.[0] || '';

          let progressPercent = 0;
          if (hasProgress && movie?.duration) {
            const minutesString = String(movie.duration).replace(' min', '');
            const minutes = parseInt(minutesString, 10) || 0;
            const durationInSeconds = minutes * 60;
            progressPercent = (movie.progress / durationInSeconds) * 100;
          }

          const canRenderVideo = loadedTrailerKeys.has(key) && !!trailerSrc;
          const isVisible = visibleVideoKeys.has(key);
          const isMuted = isMutedMap[key] ?? true;

          return (
            <div
              key={key}
              data-id={key}
              className="movie-card"
              onClick={() => handleCardClick(movie, index)}
              onMouseEnter={() => handleMouseEnter(key, !!trailerSrc)}
              onMouseLeave={() => handleMouseLeave(key)}
              style={{ position: 'relative' }}
            >
              {canRenderVideo && (
                <video
                  ref={(el) => (videoRefs.current[key] = el)}
                  src={trailerSrc}
                  muted={isMuted}
                  loop
                  playsInline
                  preload="none"
                  poster={posterSrc}
                  onLoadedMetadata={() => onLoadedMetadata(key)}
                  onPlaying={() => onPlaying(key)}
                  onWaiting={() => onWaiting(key)}
                  onStalled={() => onStalled(key)}
                  onError={() => onError(key)}
                  onEnded={() => onEnded(key)}
                  style={{
                    position: 'absolute',
                    inset: 0,
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    opacity: isVisible ? 1 : 0,
                    transition: 'opacity 180ms ease-out',
                    pointerEvents: 'none',
                  }}
                />
              )}

              <img
                src={tmdbSized(posterSrc, "w780")}
                alt={movie?.title}
                loading="lazy"
                decoding="async"
                style={{
                  display: 'block',
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                  visibility: isVisible ? 'hidden' : 'visible',
                }}
              />

              {canRenderVideo && isVisible && (
                <button
                  className="row-unmute-btn"
                  onClick={(e) => toggleMute(e, key)}
                  aria-label={isMuted ? 'Unmute trailer' : 'Mute trailer'}
                  title={isMuted ? 'Unmute' : 'Mute'}
                  style={{
                    position: 'absolute',
                    top: 8,
                    right: 8,
                    zIndex: 3,
                    width: 26,
                    height: 26,
                    borderRadius: 9999,
                    border: 'none',
                    background: 'rgba(0,0,0,0.55)',
                    color: '#fff',
                    display: 'inline-flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    cursor: 'pointer',
                  }}
                >
                  {isMuted ? '🔇' : '🔊'}
                </button>
              )}

              <div className="movie-info">
                <p className="title-line" title={movie?.title}>
                  {movie?.title}
                  {movie?.type && (
                    <span className="media-type-badge">
                      {String(movie.type).toLowerCase() === 'tv' ? 'TV Show' : 'Movie'}
                    </span>
                  )}
                </p>

                {(releaseYear || movie?.rating) && (
                  <div className="meta-row">
                    {releaseYear && <span className="release-year">{releaseYear}</span>}
                    {movie?.rating && <span className="rating">★ {parseFloat(movie.rating).toFixed(1)}</span>}
                  </div>
                )}

                {hasProgress && (
                  <div className="progress-bar-container">
                    <div className="progress-bar-fill" style={{ width: `${progressPercent}%` }} />
                  </div>
                )}

                <p className={`movie-description ${isTagline ? 'is-tagline' : ''}`} title={displayText}>
                  {displayText}
                </p>
              </div>
            </div>
          );
        })}
      </Slider>
    </div>
  );
};

export default Row;

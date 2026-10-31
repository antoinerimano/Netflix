// Row.jsx
import React, { useState, useRef, useEffect, useCallback } from 'react';
import Slider from 'react-slick';
import { useNavigate } from 'react-router-dom';
import './Row.css';
import { logImpressions, logTitleClick, logOutboundClickBeacon } from '../api/analyticsApi';
import { hideWatchProgress, markNotInterested } from '../api/recoApi';
import { tmdbImage, IMG } from '../utils/tmdbImage';
import { ChevronRightIcon, MoreIcon, VolumeOnIcon, VolumeOffIcon } from '../design/icons';
import TitleOptions from './TitleOptions';

const LONG_PRESS_MS = 500; // touch: press and hold a card for its options

const LOAD_ON_HOVER_MS = 1000;
const STALL_HIDE_MS = 900;



// Mouse-only paging arrows (the remote moves card by card); aria-hidden: not in the TV focus order
const NextArrow = ({ className, onClick }) => {
  const disabled = String(className).includes('slick-disabled');
  return (
    <div className={`${className} row-arrow row-arrow--next`} aria-hidden="true" onClick={onClick} style={{ display: disabled ? 'none' : undefined }}>
      <ChevronRightIcon />
    </div>
  );
};

const PrevArrow = ({ className, onClick, isVisible }) => (
  <div className={`${className} row-arrow row-arrow--prev`} aria-hidden="true" onClick={onClick} style={{ display: isVisible ? undefined : 'none' }}>
    <ChevronRightIcon style={{ transform: 'rotate(180deg)' }} />
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
// Cards fully shown (slidesToShow has a fraction: the next card peeks in, showing the row scrolls)
const fullCards = (settings) => Math.max(1, Math.floor(getSlidesToShowFromSettings(settings)));

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
  const rowRef = useRef(null);
  const currentSlideRef = useRef(0);
  const [showPrevArrow, setShowPrevArrow] = useState(false);

  // titles removed from "Continue watching" during this visit
  const [removedIds, setRemovedIds] = useState(() => new Set());

  // --- NEW: impression de-dupe (avoid spamming) ---
  const seenImpressionsRef = useRef(new Set());
  const displayedMovies = (() => {
    const out = [];
    const seen = new Set();
    for (const t of (Array.isArray(movies) ? movies : [])) {
      const id = t?.id;
      if (!id || seen.has(id) || removedIds.has(id)) continue;
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

  // "Continue watching" items carry `resume`: go straight back to the player
  const getResumePath = (t) => {
    const { season, episode, position } = t?.resume || {};
    const params = new URLSearchParams();
    if (season && episode) {
      params.set('season', season);
      params.set('episode', episode);
    }
    if (position) params.set('t', position); // players that support it start there
    const qs = params.toString();
    return `/watch/${t.id}${qs ? `?${qs}` : ''}`;
  };

  const removeFromContinueWatching = (e, t) => {
    e?.stopPropagation();
    const profileId = localStorage.getItem('activeProfileId');
    setRemovedIds((prev) => new Set(prev).add(t.id));
    hideWatchProgress({ profileId, titleId: t.id }).catch(() => {});
  };

  // "Not interested": gone from this row now, never recommended again to this profile
  const handleNotInterested = (e, t) => {
    e?.stopPropagation();
    const profileId = localStorage.getItem('activeProfileId');
    setRemovedIds((prev) => new Set(prev).add(t.id));
    markNotInterested({ profileId, titleId: t.id, surface: 'home_row' }).catch(() => {});
  };

  // ---- Options sheet (hold OK, menu key, right click, long press, "⋯") ----
  const [options, setOptions] = useState(null); // { movie, index }
  const openOptions = (movie, index) => setOptions({ movie, index });
  const press = useRef({ timer: null, x: 0, y: 0, fired: false });
  const touchHandlers = (movie, index) => ({
    onPointerDown: (e) => {
      if (e.pointerType !== 'touch') return;
      const p = press.current;
      clearTimeout(p.timer);
      p.fired = false;
      p.x = e.clientX;
      p.y = e.clientY;
      p.timer = setTimeout(() => {
        p.fired = true;
        openOptions(movie, index);
      }, LONG_PRESS_MS);
    },
    onPointerMove: (e) => {
      const p = press.current;
      if (p.timer && Math.hypot(e.clientX - p.x, e.clientY - p.y) > 10) clearTimeout(p.timer); // a swipe
    },
    onPointerUp: () => clearTimeout(press.current.timer),
    onPointerCancel: () => clearTimeout(press.current.timer),
  });

  // --- NEW: log internal click before navigate ---
  const handleCardClick = (t, index) => {
    if (t?.id && t.resume) {
      const url = getResumePath(t);
      logOutboundClickBeacon({ title_id: t.id, surface: 'continue_watching', provider: 'watch_page', url });
      navigate(url);
      return;
    }
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

  // keyboard / TV remote: keep the focused card on screen (src/tv/spatialNavigation.js moves focus)
  const ensureCardVisible = (index) => {
    const slider = sliderRef.current;
    if (!slider) return;
    const show = fullCards(settings);
    const current = currentSlideRef.current;
    if (index < current) slider.slickGoTo(index);
    else if (index >= current + show) slider.slickGoTo(index - show + 1);
  };

  const settings = {
    dots: false,
    infinite: false,
    accessibility: false, // its own arrow-key handling would fight the TV navigation
    speed: 450,
    cssEase: 'cubic-bezier(0.2, 0, 0, 1)',
    // a fraction: part of the next card shows at the right edge (the row obviously scrolls)
    slidesToShow: 6.15,
    slidesToScroll: 1,
    nextArrow: <NextArrow />,
    prevArrow: <PrevArrow isVisible={showPrevArrow} />,
    responsive: [
      { breakpoint: 1920, settings: { slidesToShow: 5.15, slidesToScroll: 1 } },
      { breakpoint: 1400, settings: { slidesToShow: 4.15, slidesToScroll: 1 } },
      { breakpoint: 1024, settings: { slidesToShow: 3.15, slidesToScroll: 1 } },
      { breakpoint: 600, settings: { slidesToShow: 2.3, slidesToScroll: 1 } },
      { breakpoint: 430, settings: { slidesToShow: 2.1, slidesToScroll: 1 } },
      { breakpoint: 340, settings: { slidesToShow: 1.6, slidesToScroll: 1 } },
    ],
    afterChange: (current) => {
      const totalSlides = displayedMovies.length;
      const slidesToShow = fullCards(settings);
      currentSlideRef.current = current;

      setShowPrevArrow(current > 0);

      // --- NEW: log visible impressions on slide change ---
      logVisible(current, slidesToShow);

      // wrap back to the start at the end, but not while a keyboard / remote user is in this row
      const keyboardInRow = rowRef.current?.contains(document.activeElement);
      if (current >= totalSlides - slidesToShow && !keyboardInRow) {
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
    const slidesToShow = slidesToShowOverride ?? fullCards(settings);
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
    const slidesToShow = fullCards(settings);
    logVisible(0, slidesToShow);

    // Reset de-dupe if the row title changes (optional; keeps it cleaner)
    // If you prefer to keep it across renders, remove these 2 lines.
    // seenImpressionsRef.current = new Set();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title]); // when the row title changes, treat it as a new surface

  if (displayedMovies.length === 0) return null; // e.g. everything removed from Continue watching

  return (
    <section className="row" ref={rowRef} aria-label={title}>
      <h2 className="row__title">{title}</h2>
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
            progressPercent = Math.min(100, (movie.progress / durationInSeconds) * 100);
          }

          const canRenderVideo = loadedTrailerKeys.has(key) && !!trailerSrc;
          const isVisible = visibleVideoKeys.has(key);
          const isMuted = isMutedMap[key] ?? true;

          return (
            // react-slick overwrites tabIndex (-1) and style on each slide's root element:
            // this wrapper takes it, so the card itself stays focusable (TV remote / keyboard)
            <div key={key} className="row-slide">
            <div
              data-id={key}
              className="movie-card"
              tabIndex={0}
              role="button"
              aria-label={movie?.title}
              data-options=""
              onFocus={() => ensureCardVisible(index)}
              onClick={() => {
                if (press.current.fired) {
                  press.current.fired = false; // the long press opened the options
                  return;
                }
                handleCardClick(movie, index);
              }}
              onContextMenu={(e) => {
                // right click, Android long press, TV remote: hold OK / menu key
                e.preventDefault();
                openOptions(movie, index);
              }}
              {...touchHandlers(movie, index)}
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
                  poster={tmdbImage(posterSrc, IMG.backdropCard)}
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

              {/* shown when the artwork is missing / broken (the image covers it otherwise) */}
              <span className="row-card__fallback" aria-hidden="true">{movie?.title}</span>
              <img
                src={tmdbImage(posterSrc, IMG.backdropCard)}
                alt=""
                loading="lazy"
                decoding="async"
                onError={(e) => {
                  // landscape image broken: try the poster, then show the title tile
                  const img = e.currentTarget;
                  if (!img.dataset.fallback && movie?.poster && movie.poster !== posterSrc) {
                    img.dataset.fallback = '1';
                    img.src = tmdbImage(movie.poster, IMG.poster);
                  } else {
                    img.style.display = 'none';
                  }
                }}
                style={{
                  display: 'block',
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                  visibility: isVisible ? 'hidden' : 'visible',
                }}
              />

              {/* mouse / touch: options (the remote holds OK; not in its focus order) */}
              <button
                  type="button"
                  tabIndex={-1}
                  className="row-options-btn row-card-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    openOptions(movie, index);
                  }}
                  aria-label={`Options for ${movie?.title || 'this title'}`}
                  title="Options"
                >
                  <MoreIcon />
                </button>

              {canRenderVideo && isVisible && (
                <button
                  className="row-unmute-btn row-card-btn"
                  onClick={(e) => toggleMute(e, key)}
                  aria-label={isMuted ? 'Unmute trailer' : 'Mute trailer'}
                  title={isMuted ? 'Unmute' : 'Mute'}
                >
                  {isMuted ? <VolumeOffIcon /> : <VolumeOnIcon />}
                </button>
              )}

              {/* status on the artwork, always visible: where you are / what's new */}
              {movie?.resume ? (
                <span className="row-card-badge">
                  {movie.resume.season ? `S${movie.resume.season} · E${movie.resume.episode}` : 'Resume'}
                </span>
              ) : movie?.latest_episode ? (
                <span className="row-card-badge row-card-badge--new">
                  {`New · S${movie.latest_episode.season} E${movie.latest_episode.episode}`}
                </span>
              ) : null}

              {hasProgress && (
                <div className="progress-bar-container" aria-label={`${Math.round(progressPercent)}% watched`}>
                  <div className="progress-bar-fill" style={{ width: `${progressPercent}%` }} />
                </div>
              )}

              <div className="movie-info">
                {(releaseYear || movie?.rating) && (
                  <div className="meta-row">
                    {releaseYear && <span className="release-year">{releaseYear}</span>}
                    {movie?.rating && <span className="rating">★ {parseFloat(movie.rating).toFixed(1)}</span>}
                  </div>
                )}

                {/* "Why this?": reason computed with the recommendations */}
                {movie?.why && <p className="why-line">{movie.why}</p>}

                <p className={`movie-description ${isTagline ? 'is-tagline' : ''}`} title={displayText}>
                  {displayText}
                </p>
              </div>
            </div>
            {/* title under the card: always readable (TV, touch), the artwork rarely shows it */}
            <div className="row-card__caption" aria-hidden="true">
              <span className="row-card__title">{movie?.title}</span>
              {movie?.type ? (
                <span className="row-card__type">{String(movie.type).toLowerCase() === 'tv' ? 'Series' : 'Film'}</span>
              ) : null}
            </div>
            </div>
          );
        })}
      </Slider>

      <TitleOptions
        open={!!options}
        title={options?.movie}
        surface="home_row"
        onClose={() => setOptions(null)}
        onPlay={() => {
          const t = options.movie;
          if (t.resume) {
            handleCardClick(t, options.index); // straight back to the player
            return;
          }
          const url = `/watch/${t.id}`;
          logOutboundClickBeacon({ title_id: t.id, surface: 'home_row_options', provider: 'watch_page', url });
          navigate(url);
        }}
        onInfo={() => {
          const t = options.movie;
          logTitleClick({ title_id: t.id, surface: 'home_row', position: options.index, row_title: title });
          navigate(getDetailPath(t));
        }}
        onRemoveResume={options?.movie?.resume ? () => removeFromContinueWatching(null, options.movie) : undefined}
        onNotInterested={options?.movie && !options.movie.resume ? () => handleNotInterested(null, options.movie) : undefined}
      />
    </section>
  );
};

export default Row;

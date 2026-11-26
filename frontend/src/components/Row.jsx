// Row.jsx
import React, { useState, useRef, useEffect, useCallback } from 'react';
import Slider from 'react-slick';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { formatNumber } from '../i18n/format';
import { whyText } from '../i18n/catalogText';
import './Row.css';
import { logImpressions, logTitleClick, logOutboundClickBeacon } from '../api/analyticsApi';
import { hideWatchProgress, markNotInterested } from '../api/recoApi';
import { tmdbImage, IMG } from '../utils/tmdbImage';
import { ChevronLeftIcon, ChevronRightIcon, MoreIcon } from '../design/icons';
import TitleOptions from './TitleOptions';
import CardPreview from './preview/CardPreview';
import { previewStore } from './preview/previewStore';

const LONG_PRESS_MS = 500; // touch: press and hold a card for its options

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
    <ChevronLeftIcon />
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

// Top 10 rows (ROADMAP 9.4): at most this many, numbered in the order shown
export const TOP10_SIZE = 10;

// title: shown (translated); analyticsTitle: the row's stable name for analytics (same in every language)
// variant "top10": big numbers beside poster cards, the first TOP10_SIZE titles
const Row = ({ title: shownTitle, analyticsTitle, movies, variant }) => {
  const top10 = variant === 'top10';
  const { t, i18n } = useTranslation('catalog');
  const navigate = useNavigate();
  const title = analyticsTitle || shownTitle;

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
    return top10 ? out.slice(0, TOP10_SIZE) : out;
  })();


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

  // right-to-left (Arabic, Urdu): the row is mirrored in CSS (Row.css), so react-slick's own
  // swipe would scroll the wrong way; drag / swipe is handled here instead, reversed
  const rtl = i18n.dir() === 'rtl';
  const drag = useRef(null);
  const rtlSwipe = rtl ? {
    onPointerDown: (e) => {
      if (e.pointerType === 'mouse' && e.button !== 0) return;
      drag.current = { x: e.clientX, y: e.clientY, moved: false };
    },
    onPointerMove: (e) => {
      const d = drag.current;
      if (d && Math.abs(e.clientX - d.x) > 10 && Math.abs(e.clientX - d.x) > Math.abs(e.clientY - d.y)) d.moved = true;
    },
    onPointerUp: (e) => {
      const d = drag.current;
      drag.current = d && d.moved ? { moved: true } : null; // the click after a drag is swallowed below
      const slider = sliderRef.current;
      if (!d || !d.moved || !slider) return;
      const card = rowRef.current?.querySelector('.slick-slide')?.getBoundingClientRect().width || 300;
      const steps = Math.max(1, Math.round(Math.abs(e.clientX - d.x) / card));
      // finger to the right = the cards further left come in = forwards
      const target = currentSlideRef.current + (e.clientX > d.x ? steps : -steps);
      slider.slickGoTo(Math.max(0, Math.min(target, displayedMovies.length - fullCards(settings))));
    },
    onPointerCancel: () => { drag.current = null; },
    onDragStart: (e) => e.preventDefault(), // no ghost image while dragging a poster
    onClickCapture: (e) => {
      if (drag.current?.moved) { e.preventDefault(); e.stopPropagation(); }
      drag.current = null;
    },
  } : {};

  const settings = {
    dots: false,
    swipe: !rtl,
    infinite: false,
    accessibility: false, // its own arrow-key handling would fight the TV navigation
    speed: 450,
    cssEase: 'cubic-bezier(0.2, 0, 0, 1)',
    // remote / keyboard presses come faster than the 450 ms slide: a new move replaces the one
    // under way (react-slick drops slickGoTo while animating by default, leaving the focused card
    // off screen), and the row's position is where it is going, not where it was
    waitForAnimate: false,
    beforeChange: (_, next) => { currentSlideRef.current = next; },
    // a fraction: part of the next card shows at the right edge (the row obviously scrolls)
    slidesToShow: 6.15,
    slidesToScroll: 1,
    nextArrow: <NextArrow />,
    prevArrow: <PrevArrow isVisible={showPrevArrow} />,
    responsive: top10 ? [
      // a number + a poster per slide: about as many per screen as the wide cards
      { breakpoint: 1920, settings: { slidesToShow: 5.15, slidesToScroll: 1 } },
      { breakpoint: 1400, settings: { slidesToShow: 4.6, slidesToScroll: 1 } },
      { breakpoint: 1024, settings: { slidesToShow: 3.6, slidesToScroll: 1 } },
      { breakpoint: 600, settings: { slidesToShow: 2.4, slidesToScroll: 1 } },
      { breakpoint: 340, settings: { slidesToShow: 1.8, slidesToScroll: 1 } },
    ] : [
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
  }, [displayedMovies, title]); // eslint-disable-line react-hooks/exhaustive-deps -- settings: a new object each render (its values don't change), including it would loop

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
    <section className={`row${top10 ? ' row--top10' : ''}`} ref={rowRef} aria-label={shownTitle} {...rtlSwipe}>
      <h2 className="row__title">{shownTitle}</h2>
      <Slider ref={sliderRef} {...settings}>
        {displayedMovies.map((movie, index) => {
          const key = `${title}-${movie.id}-${index}`;
          const trailerSrc = movie.trailer_clip_url || '';
          // Top 10: the poster (portrait), the wide artwork if there is none
          const posterSrc = top10 ? movie?.poster || movie?.landscape_image : movie?.landscape_image || movie?.poster;
          const rank = index + 1;

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

          return (
            // react-slick overwrites tabIndex (-1) and style on each slide's root element:
            // this wrapper takes it, so the card itself stays focusable (TV remote / keyboard)
            <div key={key} className="row-slide">
            {top10 ? <span className="row-top10__rank" aria-hidden="true">{formatNumber(rank, undefined, i18n.resolvedLanguage)}</span> : null}
            <div className="row-slide__card">
            <div
              data-id={key}
              className="movie-card"
              tabIndex={0}
              role="button"
              aria-label={top10 ? t('card.rank', { rank: formatNumber(rank, undefined, i18n.resolvedLanguage), title: movie?.title || '' }) : movie?.title}
              data-options=""
              onFocus={(e) => {
                ensureCardVisible(index);
                // remote / keyboard only: a mouse click also focuses, its hover already asked
                if (e.currentTarget.matches(':focus-visible')) previewStore.request(key, trailerSrc, 'focus');
              }}
              onBlur={() => previewStore.cancel(key)}
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
              // mouse only: on a touch screen a tap opens the title
              onPointerEnter={(e) => e.pointerType === 'mouse' && previewStore.request(key, trailerSrc, 'mouse')}
              onPointerLeave={() => previewStore.cancel(key)}
              style={{ position: 'relative' }}
            >
              {/* shown when the artwork is missing / broken (the image covers it otherwise) */}
              <span className="row-card__fallback" aria-hidden="true">{movie?.title}</span>
              <img
                src={tmdbImage(posterSrc, top10 && movie?.poster ? IMG.poster : IMG.backdropCard)}
                alt=""
                loading="lazy"
                decoding="async"
                onError={(e) => {
                  // landscape image broken: try the poster (Top 10: the other way), then show the title tile
                  const img = e.currentTarget;
                  const other = top10 ? movie?.landscape_image : movie?.poster;
                  if (!img.dataset.fallback && other && other !== posterSrc) {
                    img.dataset.fallback = '1';
                    img.src = tmdbImage(other, top10 ? IMG.backdropCard : IMG.poster);
                  } else {
                    img.style.display = 'none';
                  }
                }}
                style={{
                  display: 'block',
                  width: '100%',
                  height: '100%',
                  objectFit: 'cover',
                }}
              />

              {/* the trailer preview, over the artwork (preview/previewStore.js: when) */}
              <CardPreview previewKey={key} src={trailerSrc} poster={tmdbImage(posterSrc, IMG.backdropCard)} />

              {/* mouse / touch: options (the remote holds OK; not in its focus order) */}
              <button
                  type="button"
                  tabIndex={-1}
                  className="row-options-btn row-card-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    openOptions(movie, index);
                  }}
                  aria-label={t('options.for', { title: movie?.title || '' })}
                  title={t('options.title')}
                >
                  <MoreIcon />
                </button>

              {/* status on the artwork, always visible: where you are / what's new */}
              {movie?.resume ? (
                <span className="row-card-badge">
                  {movie.resume.season ? t('episodeShort', { season: movie.resume.season, episode: movie.resume.episode }) : t('options.resume')}
                </span>
              ) : movie?.latest_episode ? (
                <span className="row-card-badge row-card-badge--new">
                  {t('card.newEpisode', { season: movie.latest_episode.season, episode: movie.latest_episode.episode })}
                </span>
              ) : null}

              {hasProgress && (
                <div className="progress-bar-container" aria-label={t('card.watched', { percent: formatNumber(progressPercent / 100, { style: 'percent' }, i18n.resolvedLanguage) })}>
                  <div className="progress-bar-fill" style={{ width: `${progressPercent}%` }} />
                </div>
              )}

              <div className="movie-info">
                {(releaseYear || movie?.rating) && (
                  <div className="meta-row">
                    {releaseYear && <span className="release-year">{releaseYear}</span>}
                    {movie?.rating && <span className="rating">★ {formatNumber(parseFloat(movie.rating), { minimumFractionDigits: 1, maximumFractionDigits: 1 }, i18n.resolvedLanguage)}</span>}
                  </div>
                )}

                {/* "Why this?": reason computed with the recommendations, worded in the app's language */}
                {whyText(movie) ? <p className="why-line">{whyText(movie)}</p> : null}

                <p className={`movie-description ${isTagline ? 'is-tagline' : ''}`} title={displayText}>
                  {displayText}
                </p>
              </div>
            </div>
            {/* title under the card: always readable (TV, touch), the artwork rarely shows it */}
            <div className="row-card__caption" aria-hidden="true">
              <span className="row-card__title">{movie?.title}</span>
              {movie?.type ? (
                <span className="row-card__type">{String(movie.type).toLowerCase() === 'tv' ? t('common:kind.tv') : t('common:kind.movie')}</span>
              ) : null}
            </div>
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

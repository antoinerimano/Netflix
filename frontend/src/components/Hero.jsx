// src/components/Hero.js
// Home page banner: full-bleed artwork fading into the page, the featured title, a meta line
// (year · ★ · type), Play + More info. The trailer starts by itself (muted) after a few seconds
// when the banner is on screen: TV remotes can't hover. It fades back to the artwork at the end.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import './Hero.css';
import { logOutboundClickBeacon, logTitleClick } from '../api/analyticsApi';
import { Button, Rating, Badge } from '../design';
import { PlayIcon, InfoIcon, VolumeOnIcon, VolumeOffIcon, DiceIcon } from '../design/icons';
import { tmdbImage, tmdbSrcSet, IMG } from '../utils/tmdbImage';

const TRAILER_DELAY_MS = 3000;

const isValidUrl = (url) => typeof url === 'string' && /^https?:\/\//i.test(url.trim());
const isTv = (t) => String(t?.type || t?.title_type || t?.media_type || '').toLowerCase() === 'tv';
const yearOf = (t) =>
  t?.release_year || String(t?.release_date || t?.first_air_date || '').match(/\d{4}/)?.[0] || '';

/** Artwork for the banner: the landscape image, else the poster (shown blurred, see CSS) */
export function heroArtwork(t) {
  const wide = t?.landscape_image || t?.landscape_url || '';
  if (wide) return { url: wide, wide: true };
  if (t?.poster) return { url: t.poster, wide: false };
  return null;
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

const Hero = ({ hero: title }) => {
  const { t } = useTranslation('catalog');
  const navigate = useNavigate();
  const rootRef = useRef(null);
  const videoRef = useRef(null);

  const [imageLoaded, setImageLoaded] = useState(false);
  const [videoOn, setVideoOn] = useState(false); // trailer visible
  const [videoFailed, setVideoFailed] = useState(false);
  const [muted, setMuted] = useState(true);
  const [ended, setEnded] = useState(false); // played once: stay on the artwork
  const [onScreen, setOnScreen] = useState(true);

  const art = heroArtwork(title);
  const trailer = (title?.trailer_clip_url || '').trim();
  const canPlayTrailer = isValidUrl(trailer) && !videoFailed && !prefersReducedMotion();

  // new title: start over from the artwork
  useEffect(() => {
    setImageLoaded(false);
    setVideoOn(false);
    setVideoFailed(false);
    setEnded(false);
  }, [title?.id]);

  // only play while the banner is on screen and the tab visible
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return undefined;
    const io = new IntersectionObserver(([entry]) => setOnScreen(entry.intersectionRatio > 0.4), {
      threshold: [0, 0.4, 1],
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const v = videoRef.current;
    if (!canPlayTrailer || !v || ended) return undefined;
    if (!onScreen) {
      v.pause();
      return undefined;
    }
    const timer = setTimeout(() => {
      if (document.visibilityState !== 'visible') return;
      v.play()?.catch(() => setVideoFailed(true)); // autoplay refused: stay on the artwork
    }, v.currentTime > 0 ? 300 : TRAILER_DELAY_MS); // resuming after scrolling back: no wait
    return () => clearTimeout(timer);
  }, [canPlayTrailer, onScreen, title?.id, ended]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = muted;
  }, [muted]);

  const watchUrl = title?.id ? `/watch/${title.id}` : null;
  const detailUrl = title?.id ? `/${isTv(title) ? 'tv' : 'movies'}/${title.id}` : null;

  const play = useCallback(() => {
    if (!watchUrl) return;
    logOutboundClickBeacon({ title_id: title.id, surface: 'hero', provider: 'watch_page', url: watchUrl });
    window.location.href = watchUrl;
  }, [title, watchUrl]);

  const moreInfo = useCallback(() => {
    if (!detailUrl) return;
    logTitleClick({ title_id: title.id, surface: 'hero', position: 0, row_title: 'Hero' });
    navigate(detailUrl);
  }, [title, detailUrl, navigate]);

  const description = useMemo(() => (title?.tagline || title?.description || '').trim(), [title]);

  if (!title) return <div className="hero hero--empty" aria-hidden="true" />;

  const year = yearOf(title);
  const rating = title.rating ?? title.vote_average;

  return (
    <section ref={rootRef} className={`hero${videoOn ? ' is-playing' : ''}`} aria-label={t('hero.featuredLabel', { title: title.title })}>
      <div className="hero__media" aria-hidden="true">
        {art ? (
          <picture>
            {/* phones (portrait): the poster fits the tall banner; a landscape image cropped to it
                kept only a slice of the picture */}
            {art.wide && title.poster ? (
              <source
                media="(max-width: 600px) and (orientation: portrait)"
                srcSet={tmdbSrcSet(title.poster, [342, 500, 780]) || tmdbImage(title.poster, IMG.posterLarge)}
                sizes="100vw"
              />
            ) : null}
            <img
              className={`hero__image${art.wide ? '' : ' hero__image--poster'}${imageLoaded ? ' is-loaded' : ''}`}
              src={tmdbImage(art.url, art.wide ? IMG.backdropHero : IMG.posterLarge)}
              srcSet={art.wide ? tmdbSrcSet(art.url, [780, 1280]) : undefined}
              sizes="100vw"
              alt=""
              fetchpriority="high"
              decoding="async"
              onLoad={() => setImageLoaded(true)}
            />
          </picture>
        ) : null}

        {canPlayTrailer ? (
          <video
            key={title.id}
            ref={videoRef}
            className="hero__video"
            src={trailer}
            muted={muted}
            playsInline
            preload="none"
            onPlaying={() => setVideoOn(true)}
            onEnded={() => {
              setVideoOn(false);
              setEnded(true);
            }}
            onError={() => {
              setVideoOn(false);
              setVideoFailed(true);
            }}
          />
        ) : null}
        <div className="hero__scrim" />
      </div>

      <div className="hero__content">
        <div className="hero__kicker">
          <Badge tone="brand">{isTv(title) ? t('common:kind.tv') : t('common:kind.movie')}</Badge>
          <span>{t('hero.featured')}</span>
        </div>

        <h1 className="hero__title">{title.title}</h1>

        <div className="hero__meta">
          {year ? <span>{year}</span> : null}
          {Number(rating) > 0 ? <Rating value={rating} /> : null}
          {title.resume ? <span>{t('hero.continueWatching')}</span> : null}
        </div>

        {description ? <p className="hero__description">{description}</p> : null}

        <div className="ui-actions hero__actions">
          <Button variant="primary" size="lg" icon={<PlayIcon />} onClick={play}>
            {title.resume ? t('options.resume') : t('options.play')}
          </Button>
          <Button variant="glass" size="lg" icon={<InfoIcon />} onClick={moreInfo}>
            {t('options.moreInfo')}
          </Button>
          {/* can't decide: one title that fits (components/pick/PickPage.jsx) */}
          <Button variant="glass" size="lg" icon={<DiceIcon />} label={t('pick.surprise')} onClick={() => navigate('/pick?surprise=1')} />
        </div>
      </div>

      {canPlayTrailer && videoOn ? (
        <Button
          className="hero__mute"
          variant="glass"
          icon={muted ? <VolumeOffIcon /> : <VolumeOnIcon />}
          label={muted ? t('trailer.soundOn') : t('trailer.soundOff')}
          onClick={() => setMuted((m) => !m)}
        />
      ) : null}
    </section>
  );
};

export default Hero;

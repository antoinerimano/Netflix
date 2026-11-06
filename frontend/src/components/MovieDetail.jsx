// src/components/MovieDetail.js
// Movie page: shared detail template (components/detail): hero with Watch / My List / ratings,
// then Trailer, Cast and Details sections.
import React, { useEffect, useState, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { usePageTitle } from '../utils/pageTitle';
import { useFormat, languageName as intlLanguageName } from '../i18n/format';
import { fetchMovieById } from '../api/titlesApi';
import { logOutboundClickBeacon, logActionBeacon } from '../api/analyticsApi';
import { fetchMyList, setInMyList } from '../api/myListApi';
import RatingButtons from './RatingButtons';
import Navbar from './Navbar';
import Footer from './Footer';
import DetailHero, { splitGenres, genreName } from './detail/DetailHero';
import CastRow, { castObjects } from './detail/CastRow';
import MoreLikeThis from './detail/MoreLikeThis';
import { Button, EmptyState, SectionTitle, Skeleton, friendlyError } from '../design';
import { PlayIcon, PlusIcon, CheckIcon } from '../design/icons';

/* --- Helpers --- */
/** countries: names, or TMDB objects ({ iso_3166_1, name }: shown in the app's language) */
export function getNames(list, regionName, key = 'name') {
  if (!list) return [];
  if (Array.isArray(list)) {
    return list
      .map((x) => {
        if (typeof x === 'string') return x;
        if (x?.iso_3166_1 && regionName) return regionName(x.iso_3166_1);
        return x?.[key] || x?.english_name;
      })
      .filter(Boolean);
  }
  if (typeof list === 'object') return Object.values(list).filter(Boolean).map(String);
  return [];
}
const yearOf = (d) => String(d || '').match(/\d{4}/)?.[0] || '';
/** "ja" -> "Japanese" in the app's language */
export const languageName = (code) => intlLanguageName(code);

/* --- Trailer embed --- */
function TrailerEmbed({ url }) {
  const { t } = useTranslation('catalog');
  if (!url) return null;
  const ytMatch =
    url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{6,})/) ||
    url.match(/[?&]v=([A-Za-z0-9_-]{6,})/);
  if (ytMatch?.[1]) {
    return (
      <div className="trailer-embed">
        <iframe
          src={`https://www.youtube.com/embed/${ytMatch[1]}?rel=0&modestbranding=1&hl=${document.documentElement.lang || 'en'}&cc_lang_pref=${document.documentElement.lang || 'en'}`}
          title={t('detail.trailer')}
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
      <iframe src={url} title={t('detail.trailer')} loading="lazy" />
    </div>
  );
}

/** The page's shape while it loads */
export function DetailSkeleton() {
  const { t } = useTranslation();
  return (
    <div className="detail-hero" aria-busy="true" aria-label={t('loading')}>
      <div className="detail-hero__content">
        <Skeleton width="4rem" height="1.4rem" />
        <Skeleton width="min(30rem, 80%)" height="3.5rem" />
        <Skeleton variant="text" width="14rem" />
        <div className="ui-actions">
          <Skeleton width="9rem" height="3.25rem" />
          <Skeleton variant="circle" width="2.75rem" height="2.75rem" />
          <Skeleton variant="circle" width="2.75rem" height="2.75rem" />
        </div>
        <Skeleton variant="text" width="min(36rem, 90%)" />
        <Skeleton variant="text" width="min(30rem, 75%)" />
      </div>
    </div>
  );
}

const MovieDetail = () => {
  const { t, i18n } = useTranslation('catalog');
  const fmt = useFormat();
  const { movieId } = useParams();
  const navigate = useNavigate();
  const [movie, setMovie] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const activeProfileId = localStorage.getItem('activeProfileId');
  const [isInList, setIsInList] = useState(false);
  const listTouched = useRef(false); // the user toggled My List: the server's first answer is stale
  usePageTitle(movie?.title);

  const cast = useMemo(() => castObjects(movie?.actors, { byPopularity: true }), [movie]);
  const countryList = useMemo(() => getNames(movie?.production_countries, fmt.regionName), [movie, fmt.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setLoadError(null);
    fetchMovieById(parseInt(movieId, 10))
      .then((data) => alive && setMovie(data))
      .catch((err) => {
        console.error('Failed to fetch movie:', err);
        if (alive) setLoadError(err);
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [movieId, i18n.resolvedLanguage]); // the title and synopsis come back in the app's language

  // My List (saved on the server, per profile)
  useEffect(() => {
    if (!movie?.id || !activeProfileId) return;
    let alive = true;
    listTouched.current = false;
    fetchMyList(activeProfileId)
      // a click made before this answer arrived wins (the answer predates it)
      .then((items) => alive && !listTouched.current && setIsInList(items.some((i) => i.id === movie.id)))
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
    listTouched.current = true;
    setIsInList(nextIsAdd); // instant feedback, undone if the server refuses
    setInMyList(activeProfileId, movie.id, nextIsAdd).catch(() => setIsInList(!nextIsAdd));
  };

  const watch = () => {
    const watchUrl = `/watch/${movie.id}`;
    logOutboundClickBeacon({ title_id: movie.id, surface: 'movie_detail', provider: 'watch_page', url: watchUrl });
    window.location.href = watchUrl;
  };

  if (loading) {
    return (
      <div className="detail">
        <Navbar />
        <DetailSkeleton />
      </div>
    );
  }

  if (!movie) {
    return (
      <div className="detail">
        <Navbar />
        <EmptyState
          page
          tone="error"
          title={t('detail.movieUnavailable')}
          actions={
            <>
              <Button variant="primary" to="/movies">{t('detail.browseMovies')}</Button>
              <Button variant="ghost" onClick={() => navigate(-1)}>{t('actions.goBack')}</Button>
            </>
          }
        >
          {friendlyError(loadError || { status: 404 }, 'movie')}
        </EmptyState>
      </div>
    );
  }

  const year = yearOf(movie.release_date) || movie.release_year;
  const runtime = fmt.formatRuntime(movie.runtime_minutes);
  const language = fmt.languageName(movie.original_language);
  const genres = splitGenres(movie.genre).map((g) => genreName(g));
  const starring = fmt.formatList(cast.slice(0, 3).map((a) => a.name || a.english_name));
  const released = movie.release_date ? fmt.formatDate(movie.release_date, { dateStyle: 'long' }) || movie.release_date : year;

  return (
    <div className="detail">
      <Navbar />

      <DetailHero
        title={movie}
        kind="movie"
        meta={[year, runtime, language]}
        credits={[
          { label: t('detail.starring'), value: starring },
          { label: t('detail.director'), value: movie.director },
        ]}
        actions={
          <>
            <Button variant="primary" size="lg" icon={<PlayIcon />} onClick={watch}>
              {t('detail.watch')}
            </Button>
            <Button
              variant="glass"
              icon={isInList ? <CheckIcon /> : <PlusIcon />}
              pressed={isInList}
              label={isInList ? t('options.inList') : t('options.addToList')}
              onClick={handleToggleList}
            />
            <RatingButtons titleId={movie.id} />
          </>
        }
      />

      <div className="detail-body">
        {movie.trailer_url ? (
          <section className="detail-section">
            <SectionTitle>{t('detail.trailer')}</SectionTitle>
            <TrailerEmbed url={movie.trailer_url} />
          </section>
        ) : null}

        <MoreLikeThis titleId={movie.id} />

        <CastRow cast={cast} />

        <section className="detail-section">
          <SectionTitle>{t('detail.details')}</SectionTitle>
          <dl className="detail-facts">
            {genres.length ? (
              <div>
                <dt>{t('detail.genres')}</dt>
                <dd>{fmt.formatList(genres, 'unit')}</dd>
              </div>
            ) : null}
            {released ? (
              <div>
                <dt>{t('detail.released')}</dt>
                <dd>{released}</dd>
              </div>
            ) : null}
            {runtime ? (
              <div>
                <dt>{t('detail.runtime')}</dt>
                <dd>{runtime}</dd>
              </div>
            ) : null}
            {language ? (
              <div>
                <dt>{t('detail.originalLanguage')}</dt>
                <dd>{language}</dd>
              </div>
            ) : null}
            {movie.director ? (
              <div>
                <dt>{t('detail.director')}</dt>
                <dd>{movie.director}</dd>
              </div>
            ) : null}
            {countryList.length ? (
              <div>
                <dt>{t('detail.countries')}</dt>
                <dd>{fmt.formatList(countryList, 'unit')}</dd>
              </div>
            ) : null}
          </dl>
        </section>
      </div>
      <Footer />
    </div>
  );
};

export default MovieDetail;

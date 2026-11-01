// src/components/TVShowDetail.js
// Show page: shared detail template (components/detail): hero with Watch / My List / ratings /
// new-episode alerts, then Episodes (season chips + episode cards), Cast and Details.
import React, { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useFormat, formatDate } from '../i18n/format';
import {
  fetchTitleById,
  fetchSeasons,
  fetchEpisodesBySeasonNumber,
} from '../api/titlesApi';
import { logOutboundClickBeacon, logActionBeacon } from '../api/analyticsApi';
import { fetchMyList, setInMyList } from '../api/myListApi';
import RatingButtons from './RatingButtons';
import FollowButton from './FollowButton';
import Navbar from './Navbar';
import Footer from './Footer';
import DetailHero, { splitGenres, genreName } from './detail/DetailHero';
import CastRow, { castObjects } from './detail/CastRow';
import MoreLikeThis from './detail/MoreLikeThis';
import { DetailSkeleton } from './MovieDetail';
import { Button, Chip, EmptyState, SectionTitle, Skeleton, friendlyError } from '../design';
import { PlayIcon, PlusIcon, CheckIcon, ChevronRightIcon } from '../design/icons';
import { tmdbImage, IMG } from '../utils/tmdbImage';

const getActiveProfileId = () => localStorage.getItem('activeProfileId');

const toYear = (s) => (s ? String(s).slice(0, 4) : '');

// Still image from TMDb (cards are ~260-400px wide)
const getStillUrl = (still_path) =>
  still_path ? `https://image.tmdb.org/t/p/w780/${String(still_path).replace(/^\//, '')}` : '';

const formatAirDate = (d, lng) => (d ? formatDate(String(d).slice(0, 10), { dateStyle: 'medium' }, lng) || d : '');

export default function TVShowDetail() {
  const { t, i18n } = useTranslation('catalog');
  const fmt = useFormat();
  const lng = i18n.resolvedLanguage;
  const { id } = useParams();
  const tvId = useMemo(() => Number(id), [id]);

  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState(null);
  const [err, setErr] = useState('');
  const [seasons, setSeasonsState] = useState([]);
  const [specials, setSpecials] = useState([]);
  const [activeSeasonNumber, setActiveSeasonNumber] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [episodesLoading, setEpisodesLoading] = useState(true);
  const [activeProfileId, setActiveProfileId] = useState(() => localStorage.getItem('activeProfileId'));
  const [isInList, setIsInList] = useState(false);
  const listTouched = useRef(false); // the user toggled My List: the server's first answer is stale
  // episodes whose synopsis is open (hidden by default: a 2-line cut was never enough)
  const [openSynopsis, setOpenSynopsis] = useState(() => new Set());
  const toggleSynopsis = (id) =>
    setOpenSynopsis((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const cast = useMemo(() => castObjects(title?.actors), [title]);
  const navigate = useNavigate();


  useEffect(() => {
    const onChange = () => setActiveProfileId(getActiveProfileId());
    window.addEventListener('activeProfileChanged', onChange);
    return () => window.removeEventListener('activeProfileChanged', onChange);
  }, []);

  // Load title + seasons
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setErr('');

    Promise.all([fetchTitleById(tvId), fetchSeasons(tvId)])
      .then(([t, list]) => {
        if (!alive) return;
        setTitle(t || null);

        const all = Array.isArray(list) ? list : [];
        const specialsList = all.filter((s) => s.season_number === 0);
        const normalList = all.filter((s) => s.season_number !== 0);

        setSpecials(specialsList);
        setSeasonsState(normalList);

        const first = normalList[0] || specialsList[0] || null;
        if (first) {
          setActiveSeasonNumber(first.season_number);
        }
      })
      .catch((e) => setErr(friendlyError(e, 'show')))
      .finally(() => alive && setLoading(false));

    return () => { alive = false; };
  }, [tvId, lng]); // the title, synopsis and season names come back in the app's language

  // Load episodes
  const loadEpisodes = useCallback(async (titleId, seasonNumber) => {
    if (seasonNumber == null) {
      setEpisodes([]);
      setEpisodesLoading(false);
      return;
    }
    setEpisodesLoading(true);
    try {
      const eps = await fetchEpisodesBySeasonNumber(titleId, seasonNumber);
      setEpisodes(Array.isArray(eps) ? eps : []);
    } catch {
      setEpisodes([]);
    } finally {
      setEpisodesLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeSeasonNumber == null) return;
    let cancelled = false;
    (async () => {
      await loadEpisodes(tvId, activeSeasonNumber);
      if (cancelled) return;
    })();
    return () => { cancelled = true; };
  }, [tvId, activeSeasonNumber, loadEpisodes, lng]);

  // My List (saved on the server, per profile)
  useEffect(() => {
    if (!title?.id || !activeProfileId) return;
    let alive = true;
    listTouched.current = false;
    fetchMyList(activeProfileId)
      // a click made before this answer arrived wins (the answer predates it)
      .then((items) => alive && !listTouched.current && setIsInList(items.some((it) => it.id === title.id)))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [title?.id, activeProfileId]);

  const handleToggleList = useCallback(() => {
    if (!title || !activeProfileId) return;

    const nextIsAdd = !isInList;

    logActionBeacon({
      title_id: title.id,
      action: 'add_to_list',
      surface: 'tv_detail',
      provider: nextIsAdd ? 'add' : 'remove',
    });

    listTouched.current = true;
    setIsInList(nextIsAdd); // instant feedback, undone if the server refuses
    setInMyList(activeProfileId, title.id, nextIsAdd).catch(() => setIsInList(!nextIsAdd));
  }, [title, isInList, activeProfileId]);

  if (loading) {
    return (
      <div className="detail">
        <Navbar />
        <DetailSkeleton />
      </div>
    );
  }

  if (err || !title) {
    return (
      <div className="detail">
        <Navbar />
        <EmptyState
          page
          tone="error"
          title={t('detail.showUnavailable')}
          actions={
            <>
              <Button variant="primary" to="/tv">{t('notifications.browse')}</Button>
              <Button variant="ghost" onClick={() => navigate(-1)}>{t('actions.goBack')}</Button>
            </>
          }
        >
          {err || friendlyError({ status: 404 }, 'show')}
        </EmptyState>
      </div>
    );
  }

  const year = toYear(title.first_air_date);
  const seasonCount = seasons.length;
  const language = fmt.languageName(title.original_language);
  const genres = splitGenres(title.genre).map((g) => genreName(g));
  const starring = fmt.formatList(cast.slice(0, 3).map((a) => a.name || a.english_name));
  const artwork = title.landscape_image || title.poster || '';

  // internal player page; season / episode only when one is chosen
  const watchBaseUrl = `/watch/${title.id}`;
  const buildWatchUrl = (seasonNumber, episodeNumber) => {
    if (seasonNumber == null || episodeNumber == null) return watchBaseUrl;
    return `${watchBaseUrl}?season=${encodeURIComponent(seasonNumber)}&episode=${encodeURIComponent(episodeNumber)}`;
  };
  const go = (url, surface, provider) => {
    logOutboundClickBeacon({ title_id: title?.id, surface, provider, url });
    window.location.href = url;
  };

  return (
    <div className="detail">
      <Navbar />

      <DetailHero
        title={title}
        kind="tv"
        meta={[
          year,
          seasonCount ? t('detail.seasonCount', { count: seasonCount }) : '',
          language,
        ]}
        credits={[{ label: t('detail.starring'), value: starring }]}
        actions={
          <>
            <Button
              variant="primary"
              size="lg"
              icon={<PlayIcon />}
              onClick={() => go(watchBaseUrl, 'tv_detail', 'watch_page')}
            >
              {t('detail.watch')}
            </Button>
            <Button
              variant="glass"
              icon={isInList ? <CheckIcon /> : <PlusIcon />}
              pressed={isInList}
              label={isInList ? t('options.inList') : t('options.addToList')}
              onClick={handleToggleList}
            />
            <RatingButtons titleId={title.id} />
            <FollowButton titleId={title.id} />
          </>
        }
      />

      <div className="detail-body">
        {/* EPISODES */}
        {seasons.length || specials.length ? (
          <section className="detail-section" aria-labelledby="detail-episodes-title">
            <div className="detail-section__head">
              <SectionTitle id="detail-episodes-title">{t('detail.episodes')}</SectionTitle>
              {/* seasons have no id in the API: compared by number */}
              <div className="detail-scroller tvd-seasons__chips" role="group" aria-label={t('detail.season')}>
                {seasons.map((s) => (
                  <Chip
                    key={s.season_number}
                    selected={activeSeasonNumber === s.season_number}
                    onClick={() => setActiveSeasonNumber(s.season_number)}
                  >
                    {t('detail.seasonNumber', { number: s.season_number })}
                  </Chip>
                ))}
                {specials.length > 0 && (
                  <Chip key="specials" selected={activeSeasonNumber === 0} onClick={() => setActiveSeasonNumber(0)}>
                    {t('detail.specials')}
                  </Chip>
                )}
              </div>
            </div>

            {episodesLoading ? (
              <div className="detail-episodes detail-episodes--loading" aria-busy="true">
                {[0, 1, 2, 3].map((i) => (
                  <div key={i}>
                    <Skeleton />
                    <Skeleton variant="text" width="70%" style={{ marginTop: 10 }} />
                  </div>
                ))}
              </div>
            ) : episodes.length === 0 ? (
              <EmptyState title={t('detail.noEpisodesTitle')}>{t('detail.noEpisodesText')}</EmptyState>
            ) : (
              <div key={activeSeasonNumber} className="detail-episodes" data-season={activeSeasonNumber}>
                {episodes.map((ep) => {
                  const url = buildWatchUrl(activeSeasonNumber, ep.episode_number);
                  const still = getStillUrl(ep.still_path);
                  const meta = [fmt.formatRuntime(ep.runtime), formatAirDate(ep.air_date, lng)]
                    .filter(Boolean)
                    .join(' · ');
                  let stillBackground;
                  if (still) stillBackground = `url(${still})`;
                  else if (artwork) stillBackground = `url(${tmdbImage(artwork, IMG.backdropCard)})`;
                  const synopsisOpen = openSynopsis.has(ep.id);
                  return (
                    <div key={ep.id} className="tvd-ep">
                    <div
                      className="tvd-ep-card"
                      tabIndex={0}
                      role="button"
                      aria-label={t('detail.watchEpisode', { season: activeSeasonNumber, episode: ep.episode_number, name: ep.name || '' })}
                      onClick={() =>
                        go(url, 'tv_episode', `watch_page_s${activeSeasonNumber}_e${ep.episode_number}`)
                      }
                    >
                      <div
                        className={`tvd-ep-card__still${still ? '' : ' tvd-ep-card__still--fallback'}`}
                        style={{ backgroundImage: stillBackground }}
                      >
                        {!still ? <span className="tvd-ep-card__number">{ep.episode_number}</span> : null}
                        <div className="tvd-ep-card__play" aria-hidden="true">
                          <span>
                            <PlayIcon />
                          </span>
                        </div>
                        {ep.runtime ? <span className="tvd-ep-card__runtime">{fmt.formatRuntime(ep.runtime)}</span> : null}
                        {/* mouse / remote: the full synopsis over the image after resting on
                            the episode a moment (touch screens: the "Synopsis" toggle below) */}
                        {ep.overview ? (
                          <div className="tvd-ep-card__overview" aria-hidden="true">
                            <p>{ep.overview}</p>
                          </div>
                        ) : null}
                      </div>
                      <div className="tvd-ep-card__title">
                        {ep.episode_number}. {ep.name || t('detail.episodeNumber', { number: ep.episode_number })}
                      </div>
                      {meta ? <div className="tvd-ep-card__meta">{meta}</div> : null}
                    </div>
                    {ep.overview ? (
                      <>
                        <button
                          type="button"
                          className={`tvd-ep__toggle${synopsisOpen ? ' is-open' : ''}`}
                          aria-expanded={synopsisOpen}
                          aria-controls={`ep-synopsis-${ep.id}`}
                          onClick={() => toggleSynopsis(ep.id)}
                        >
                          {synopsisOpen ? t('detail.hideSynopsis') : t('detail.synopsis')}
                          <ChevronRightIcon aria-hidden="true" />
                        </button>
                        {synopsisOpen ? (
                          <p id={`ep-synopsis-${ep.id}`} className="tvd-ep__synopsis">
                            {ep.overview}
                          </p>
                        ) : null}
                      </>
                    ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        ) : null}

        <MoreLikeThis titleId={title.id} />

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
            {title.first_air_date ? (
              <div>
                <dt>{t('detail.firstAired')}</dt>
                <dd>{fmt.formatDate(title.first_air_date, { dateStyle: 'long' }) || title.first_air_date}</dd>
              </div>
            ) : null}
            {seasonCount ? (
              <div>
                <dt>{t('detail.seasons')}</dt>
                <dd>{fmt.formatNumber(seasonCount)}</dd>
              </div>
            ) : null}
            {language ? (
              <div>
                <dt>{t('detail.originalLanguage')}</dt>
                <dd>{language}</dd>
              </div>
            ) : null}
          </dl>
        </section>
      </div>
      <Footer />
    </div>
  );
}

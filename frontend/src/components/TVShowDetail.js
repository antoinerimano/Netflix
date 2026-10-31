// src/components/TVShowDetail.js
// Show page: shared detail template (components/detail): hero with Watch / My List / ratings /
// new-episode alerts, then Episodes (season chips + episode cards), Cast and Details.
import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
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
import DetailHero, { splitGenres } from './detail/DetailHero';
import CastRow, { castObjects } from './detail/CastRow';
import { DetailSkeleton, languageName } from './MovieDetail';
import { Button, Chip, EmptyState, SectionTitle, Skeleton, friendlyError } from '../design';
import { PlayIcon, PlusIcon, CheckIcon } from '../design/icons';
import { tmdbImage, IMG } from '../utils/tmdbImage';

const getActiveProfileId = () => localStorage.getItem('activeProfileId');

const toYear = (s) => (s ? String(s).slice(0, 4) : '');

// Still image from TMDb (cards are ~260-400px wide)
const getStillUrl = (still_path) =>
  still_path ? `https://image.tmdb.org/t/p/w780/${String(still_path).replace(/^\//, '')}` : '';

const formatAirDate = (d) => {
  if (!d) return '';
  const date = new Date(`${d}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? d
    : date.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
};

export default function TVShowDetail() {
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
      .catch((e) => setErr(friendlyError(e, 'this show')))
      .finally(() => alive && setLoading(false));

    return () => { alive = false; };
  }, [tvId]);

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
  }, [tvId, activeSeasonNumber, loadEpisodes]);

  // My List (saved on the server, per profile)
  useEffect(() => {
    if (!title?.id || !activeProfileId) return;
    let alive = true;
    fetchMyList(activeProfileId)
      .then((items) => alive && setIsInList(items.some((it) => it.id === title.id)))
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
          title="Show unavailable"
          actions={
            <>
              <Button variant="primary" to="/tv">Browse TV shows</Button>
              <Button variant="ghost" onClick={() => navigate(-1)}>Go back</Button>
            </>
          }
        >
          {err || friendlyError({ status: 404 }, 'this show')}
        </EmptyState>
      </div>
    );
  }

  const year = toYear(title.first_air_date);
  const seasonCount = seasons.length;
  const language = languageName(title.original_language);
  const genres = splitGenres(title.genre);
  const starring = cast.slice(0, 3).map((a) => a.name || a.english_name).join(', ');
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
          seasonCount ? `${seasonCount} season${seasonCount > 1 ? 's' : ''}` : '',
          language,
        ]}
        credits={[{ label: 'Starring', value: starring }]}
        actions={
          <>
            <Button
              variant="primary"
              size="lg"
              icon={<PlayIcon />}
              onClick={() => go(watchBaseUrl, 'tv_detail', 'watch_page')}
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
              <SectionTitle id="detail-episodes-title">Episodes</SectionTitle>
              {/* seasons have no id in the API: compared by number */}
              <div className="detail-scroller tvd-seasons__chips" role="group" aria-label="Season">
                {seasons.map((s) => (
                  <Chip
                    key={s.season_number}
                    selected={activeSeasonNumber === s.season_number}
                    onClick={() => setActiveSeasonNumber(s.season_number)}
                  >
                    Season {s.season_number}
                  </Chip>
                ))}
                {specials.length > 0 && (
                  <Chip key="specials" selected={activeSeasonNumber === 0} onClick={() => setActiveSeasonNumber(0)}>
                    Specials
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
              <EmptyState title="No episodes yet">This season has no episodes available yet.</EmptyState>
            ) : (
              <div key={activeSeasonNumber} className="detail-episodes" data-season={activeSeasonNumber}>
                {episodes.map((ep) => {
                  const url = buildWatchUrl(activeSeasonNumber, ep.episode_number);
                  const still = getStillUrl(ep.still_path);
                  const meta = [ep.runtime ? `${ep.runtime} min` : '', formatAirDate(ep.air_date)]
                    .filter(Boolean)
                    .join(' · ');
                  let stillBackground;
                  if (still) stillBackground = `url(${still})`;
                  else if (artwork) stillBackground = `url(${tmdbImage(artwork, IMG.backdropCard)})`;
                  return (
                    <div
                      key={ep.id}
                      className="tvd-ep-card"
                      tabIndex={0}
                      role="button"
                      aria-label={`Watch season ${activeSeasonNumber} episode ${ep.episode_number}: ${ep.name || ''}`}
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
                        {ep.runtime ? <span className="tvd-ep-card__runtime">{ep.runtime}m</span> : null}
                      </div>
                      <div className="tvd-ep-card__title">
                        {ep.episode_number}. {ep.name || `Episode ${ep.episode_number}`}
                      </div>
                      {meta ? <div className="tvd-ep-card__meta">{meta}</div> : null}
                      {ep.overview ? <p className="tvd-ep-card__desc">{ep.overview}</p> : null}
                    </div>
                  );
                })}
              </div>
            )}
          </section>
        ) : null}

        <CastRow cast={cast} />

        <section className="detail-section">
          <SectionTitle>Details</SectionTitle>
          <dl className="detail-facts">
            {genres.length ? (
              <div>
                <dt>Genres</dt>
                <dd>{genres.join(', ')}</dd>
              </div>
            ) : null}
            {title.first_air_date ? (
              <div>
                <dt>First aired</dt>
                <dd>{formatAirDate(title.first_air_date)}</dd>
              </div>
            ) : null}
            {seasonCount ? (
              <div>
                <dt>Seasons</dt>
                <dd>{seasonCount}</dd>
              </div>
            ) : null}
            {language ? (
              <div>
                <dt>Original language</dt>
                <dd>{language}</dd>
              </div>
            ) : null}
          </dl>
        </section>
      </div>
    </div>
  );
}

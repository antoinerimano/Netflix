// src/components/TVShowDetail.js
import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  fetchTitleById,
  fetchSeasons,
  fetchEpisodesBySeasonNumber,
} from '../api/titlesApi';
import { logOutboundClickBeacon, logActionBeacon } from '../api/analyticsApi';
import { fetchMyList, setInMyList } from '../api/myListApi';
import RatingButtons from './RatingButtons';
import FollowButton from './FollowButton';
import './TVShowDetail.css';
import Navbar from './Navbar';
import { Button, EmptyState, Spinner, friendlyError } from '../design';
import { PlayIcon, PlusIcon, CheckIcon } from '../design/icons';
import { tmdbImage, tmdbSrcSet, tmdbBackground, IMG } from '../utils/tmdbImage';


const getActiveProfileId = () => localStorage.getItem('activeProfileId');

const toYear = (s) => (s ? String(s).slice(0, 4) : '');
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
    .filter((x) => x && (x.name || x.english_name));
};


// Still image from TMDb
const getStillUrl = (still_path) =>
  still_path
    ? `https://image.tmdb.org/t/p/w780/${String(still_path).replace(/^\//, '')}` // cards are ~260-400px wide
    : '';

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
  const castObjs = useMemo(() => getCastObjects(title?.actors), [title]);
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
      <div className="loading-container">
        <Spinner />
      </div>
    );
  }

  if (err || !title) {
    return (
      <div className="tvd">
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
  const vote = typeof title.vote_average === 'number' ? title.vote_average.toFixed(1) : (title.rating || '');

  // ✅ base watch page (your internal player page)
  const watchBaseUrl = `/watch/${title.id}`;

  // ✅ helper to include season/episode only
  const buildWatchUrl = (seasonNumber, episodeNumber) => {
    if (seasonNumber == null || episodeNumber == null) return watchBaseUrl;
    return `${watchBaseUrl}?season=${encodeURIComponent(seasonNumber)}&episode=${encodeURIComponent(episodeNumber)}`;
  };

  // Optional: keep the big watch button going to S1E1 OR to current season first ep
  const defaultWatchUrl = watchBaseUrl;

  return (
    <div className="tvd">
      <Navbar />

      {/* HERO */}
      <section className="tvd-hero">
        <div className="tvd-hero__backdrop" style={{ backgroundImage: tmdbBackground(title.landscape_image, IMG.backdropHero) }} />
        <div className="tvd-hero__overlay" />
      </section>

      {/* MAIN INFO */}
      <section className="tvd-content">
        <img
          className="tvd-content__poster"
          src={tmdbImage(title.poster, IMG.posterLarge)}
          srcSet={tmdbSrcSet(title.poster, [342, 500, 780])}
          sizes="(max-width: 768px) 60vw, 20vw"
          alt={title.title}
        />
        <div className="tvd-content__info">
          <h1 className="tvd-title">{title.title}</h1>
          <div className="tvd-meta">
            {year && <span>{year}</span>}
            {vote && <span>★ {vote}</span>}
            {title.genre && <span>{title.genre}</span>}
          </div>
          {castObjs.length ? (
            <section className="tvd-cast">
              <h3 className="tvd-section-title">Cast</h3>

              <div className="tvd-cast-grid">
                {castObjs.slice(0, 18).map((a, idx) => {
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
            </section>
          ) : null}

          <p className="tvd-description">{title.description}</p>

          {/* actions: one primary (Watch), the rest as round icon buttons */}
          <div className="ui-actions tvd-actions">
            <Button
              variant="primary"
              size="lg"
              icon={<PlayIcon />}
              href={defaultWatchUrl}
              onClick={(e) => {
                e.preventDefault();

                logOutboundClickBeacon({
                  title_id: title?.id,
                  surface: 'tv_detail',
                  provider: 'watch_page',
                  url: defaultWatchUrl,
                });

                window.location.href = defaultWatchUrl;
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
            <RatingButtons titleId={title.id} />
            <FollowButton titleId={title.id} />
          </div>
        </div>
      </section>

      {/* SEASONS */}
      <section className="tvd-seasons">
        <h3 className="tvd-section-title">Seasons</h3>
        <div className="tvd-seasons__chips">
          {/* seasons have no id in the API: compare by number (id === id was undefined === undefined,
              so every chip looked active) */}
          {seasons.map((s) => (
            <button
              key={s.season_number}
              className={`tvd-chip ${activeSeasonNumber === s.season_number ? 'is-active' : ''}`}
              aria-pressed={activeSeasonNumber === s.season_number}
              onClick={() => setActiveSeasonNumber(s.season_number)}
            >
              S{s.season_number}
            </button>
          ))}
          {specials.length > 0 && (
            <button
              key="specials"
              className={`tvd-chip ${activeSeasonNumber === 0 ? 'is-active' : ''}`}
              aria-pressed={activeSeasonNumber === 0}
              onClick={() => setActiveSeasonNumber(0)}
            >
              Specials
            </button>
          )}
        </div>
      </section>

      {/* EPISODES */}
      <section className="tvd-episodes" aria-labelledby="tvd-episodes-title">
        <div className="tvd-episodes__header">
          <h3
            id="tvd-episodes-title"
            className="tvd-section-title"
            aria-live="polite"
            aria-atomic="true"
          >
            {activeSeasonNumber === 0 ? 'Specials' : `Season ${activeSeasonNumber}`} Episodes
          </h3>
        </div>

        {episodesLoading ? (
          <div className="loading-container">
            <div className="loading-spinner"></div>
          </div>
        ) : (
          <div
            key={activeSeasonNumber}
            className="tvd-episodes__grid tvd-episodes__grid--fadein"
            data-season={activeSeasonNumber}
          >
            {episodes.map((ep) => {
              const episodeWatchUrl = buildWatchUrl(activeSeasonNumber, ep.episode_number);

              return (
                <div
                  key={ep.id}
                  className="tvd-ep-card"
                  tabIndex={0}
                  role="button"
                  aria-label={`Watch S${activeSeasonNumber} E${ep.episode_number}: ${ep.name || ''}`}
                  onClick={(e) => {
                    // the whole card plays the episode (Enter on a TV remote clicks the card)
                    if (e.target.closest('a')) return; // the Watch link handles itself
                    e.currentTarget.querySelector('.tvd-ep-card__play')?.click();
                  }}
                >
                  <div
                    className="tvd-ep-card__still"
                    style={{ backgroundImage: `url(${getStillUrl(ep.still_path)})` }}
                  />
                  <div className="tvd-ep-card__season-badge">
                    {activeSeasonNumber === 0 ? 'S0' : `S${activeSeasonNumber}`} · E{String(ep.episode_number).padStart(2, '0')}
                  </div>

                  <div className="tvd-ep-card__info">
                    <div className="tvd-ep-card__title">
                      E{ep.episode_number} · {ep.name}
                    </div>
                    <div className="tvd-ep-card__meta">
                      {ep.runtime ? `${ep.runtime}m` : ep.air_date}
                    </div>
                  </div>

                  <div className="tvd-ep-card__hover">
                    <div className="tvd-ep-card__hover-body">
                      {ep.overview && (
                        <div className="tvd-ep-card__hover-desc">
                          {ep.overview}
                          <br />
                        </div>
                      )}

                      {/* ✅ GARDE TES CLASSES: tvd-ep-card__play--1 */}
                      <div className="tvd-ep-card__hover-actions">
                        <a
                          className="tvd-ep-card__play tvd-ep-card__play--1"
                          href={episodeWatchUrl}
                          onClick={(e) => {
                            e.preventDefault();

                            logOutboundClickBeacon({
                              title_id: title?.id,
                              surface: 'tv_episode',
                              provider: `watch_page_s${activeSeasonNumber}_e${ep.episode_number}`,
                              url: episodeWatchUrl,
                            });

                            window.location.href = episodeWatchUrl;
                          }}
                        >
                          ▶ Watch
                        </a>
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <div className="tvd-footer">
        <Link to="/tv" className="tvd-btn-secondary">← Back to TV</Link>
      </div>
    </div>
  );
}

// src/components/TVShowDetail.js
import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  fetchTitleById,
  fetchSeasons,
  fetchEpisodesBySeasonNumber,
} from '../api/titlesApi';
import { logOutboundClickBeacon, logActionBeacon } from '../api/analyticsApi';
import './TVShowDetail.css';
import Navbar from './Navbar';


// ✅ My List helpers
const getActiveProfileId = () => localStorage.getItem('activeProfileId');
const loadList = (pid) => (pid ? JSON.parse(localStorage.getItem(`userList_${pid}`) || '[]') : []);
const saveList = (pid, list) => {
  if (!pid) return;
  localStorage.setItem(`userList_${pid}`, JSON.stringify(list));
};

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
    ? `https://image.tmdb.org/t/p/w1280/${String(still_path).replace(/^\//, '')}`
    : '';

export default function TVShowDetail() {
  const { id } = useParams();
  const tvId = useMemo(() => Number(id), [id]);

  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState(null);
  const [err, setErr] = useState('');
  const [seasons, setSeasonsState] = useState([]);
  const [specials, setSpecials] = useState([]);
  const [activeSeasonId, setActiveSeasonId] = useState(null);
  const [activeSeasonNumber, setActiveSeasonNumber] = useState(null);
  const [episodes, setEpisodes] = useState([]);
  const [episodesLoading, setEpisodesLoading] = useState(true);
  const [activeProfileId, setActiveProfileId] = useState(() => localStorage.getItem('activeProfileId'));
  const [list, setList] = useState(() => {
    const pid = localStorage.getItem('activeProfileId');
    return pid ? JSON.parse(localStorage.getItem(`userList_${pid}`) || '[]') : [];
  });
  const [isInList, setIsInList] = useState(false);
  const castObjs = useMemo(() => getCastObjects(title?.actors), [title]);
  const navigate = useNavigate();


  useEffect(() => {
    const onChange = () => {
      const pid = getActiveProfileId();
      setActiveProfileId(pid);
      setList(loadList(pid));
    };
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
          setActiveSeasonId(first.id);
          setActiveSeasonNumber(first.season_number);
        }
      })
      .catch((e) => setErr(e?.message || 'Failed to load show'))
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

  // Sync isInList when title changes
  useEffect(() => {
    if (!title) return;
    const inList = list.some((it) => it?.id === title.id);
    setIsInList(inList);
  }, [title, list]);

  // Persist list
  useEffect(() => {
    saveList(activeProfileId, list);
  }, [list, activeProfileId]);

  const handleToggleList = useCallback(() => {
    if (!title) return;

    const pid = localStorage.getItem('activeProfileId');
    if (!pid) return;

    const nextIsAdd = !isInList;

    logActionBeacon({
      title_id: title.id,
      action: 'add_to_list',
      surface: 'tv_detail',
      provider: nextIsAdd ? 'add' : 'remove',
    });

    setList((prev) => {
      const exists = prev.some((it) => it?.id === title.id);
      const next = exists ? prev.filter((it) => it?.id !== title.id) : [...prev, { ...title }];
      localStorage.setItem(`userList_${pid}`, JSON.stringify(next));
      return next;
    });
  }, [title, isInList]);

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner"></div>
      </div>
    );
  }

  if (err || !title) {
    return (
      <div className="tvd-loading">
        <p>{err || 'Not found'}</p>
        <Link to="/tv" className="tvd-btn-secondary">← Back</Link>
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
        <div className="tvd-hero__backdrop" style={{ backgroundImage: `url(${title.landscape_image || ''})` }} />
        <div className="tvd-hero__overlay" />
      </section>

      {/* MAIN INFO */}
      <section className="tvd-content">
        <img className="tvd-content__poster" src={title.poster} alt={title.title} />
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
            </section>
          ) : null}

          <p className="tvd-description">{title.description}</p>

          {/* ✅ GARDE TES CLASSES: tvd-actions + tvd-play--1 */}
          <div className="tvd-actions">
            <a
              className="tvd-play tvd-play--1"
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
              ▶ Watch
            </a>
          </div>

          <button
            type="button"
            className="tvd-add-button"
            onClick={handleToggleList}
          >
            {isInList ? 'Remove from My List' : 'Add to My List'}
          </button>
        </div>
      </section>

      {/* SEASONS */}
      <section className="tvd-seasons">
        <h3 className="tvd-section-title">Seasons</h3>
        <div className="tvd-seasons__chips">
          {seasons.map((s) => (
            <button
              key={s.id}
              className={`tvd-chip ${activeSeasonId === s.id ? 'is-active' : ''}`}
              onClick={() => { setActiveSeasonId(s.id); setActiveSeasonNumber(s.season_number); }}
            >
              S{s.season_number}
            </button>
          ))}
          {specials.length > 0 && (
            <button
              key={`specials-${specials[0].id}`}
              className={`tvd-chip ${activeSeasonId === specials[0].id ? 'is-active' : ''}`}
              onClick={() => { setActiveSeasonId(specials[0].id); setActiveSeasonNumber(0); }}
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
                <div key={ep.id} className="tvd-ep-card" tabIndex={0}>
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

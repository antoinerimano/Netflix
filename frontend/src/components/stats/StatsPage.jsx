// src/components/stats/StatsPage.jsx
// "Your year" (/stats, profile menu and the history page): the active profile's watching for one
// year, from its watch history (backend reco/stats.py): time, counts, streaks, a month chart,
// genres, top titles, favourite actors, and a picture to share.
// TV remote: every section can take the focus (Down walks through the whole recap, also the parts
// with nothing to press); years are a group; titles and actors open their page.
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { fetchStats } from '../../api/recoApi';
import { Avatar, Button, Chip, EmptyState, Skeleton, Toast, friendlyError } from '../../design';
import { ShareIcon, StarIcon } from '../../design/icons';
import { useFormat } from '../../i18n/format';
import { genreName } from '../detail/DetailHero';
import { IMG, tmdbImage } from '../../utils/tmdbImage';
import { drawShareImage, shareOrSave } from './shareImage';
import './stats.css';

function activeProfile() {
  try {
    return JSON.parse(localStorage.getItem('activeProfile') || 'null');
  } catch {
    return null;
  }
}

/** 12 columns, one series (minutes per month): a label on the busiest month only, the rest in the
 *  hover tooltip and the table read to screen readers. */
function MonthChart({ months, label }) {
  const { t } = useTranslation('account');
  const { formatDate, lng } = useFormat();
  const max = Math.max(...months, 1);
  const busiest = months.indexOf(Math.max(...months));
  const names = months.map((_, i) => formatDate(new Date(Date.UTC(2024, i, 15)), { month: 'short', timeZone: 'UTC' }));
  const longNames = months.map((_, i) => formatDate(new Date(Date.UTC(2024, i, 15)), { month: 'long', timeZone: 'UTC' }));
  const time = (m) => (m >= 60 ? t('stats.hoursShort', { count: Math.round(m / 60) }) : t('stats.minutesShort', { count: m }));
  return (
    <figure className="stats-months" aria-label={label}>
      <div className="stats-months__plot" aria-hidden="true">
        {months.map((m, i) => (
          <div key={i} className="stats-months__col" data-tip={`${longNames[i].charAt(0).toLocaleUpperCase(lng) + longNames[i].slice(1)} · ${time(m)}`}>
            {i === busiest && m > 0 ? <span className="stats-months__value">{time(m)}</span> : null}
            <span className="stats-months__bar" style={{ height: `${m ? Math.max(3, (m / max) * 100) : 0}%` }} />
          </div>
        ))}
      </div>
      <div className="stats-months__axis" aria-hidden="true">
        {names.map((n, i) => <span key={i}>{n}</span>)}
      </div>
      <table className="sr-only">
        <caption>{label}</caption>
        <tbody>
          {months.map((m, i) => (
            <tr key={i}><th scope="row">{longNames[i]}</th><td>{time(m)}</td></tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}

export default function StatsPage() {
  const { t } = useTranslation('account');
  const { formatDate, formatNumber } = useFormat();
  const navigate = useNavigate();
  const profile = activeProfile();
  const profileId = localStorage.getItem('activeProfileId');
  const [year, setYear] = useState(null); // null: the server's choice (latest year with history)
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [sharing, setSharing] = useState(false);
  const [toast, setToast] = useState('');
  const clearToast = useCallback(() => setToast(''), []);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await fetchStats(profileId, year));
    } catch (e) {
      setError(e);
    }
  }, [profileId, year]);

  useEffect(() => {
    load();
  }, [load]);

  const hours = data ? Math.round(data.minutes / 60) : 0;
  const headline = data
    ? data.minutes >= 60 ? t('stats.hours', { count: hours, formatted: formatNumber(hours) }) : t('stats.minutes', { count: data.minutes })
    : '';
  const day = (iso) => formatDate(`${iso}T12:00:00Z`, { day: 'numeric', month: 'long', timeZone: 'UTC' });
  const titleTime = (m) => (m >= 60 ? t('stats.hoursShort', { count: Math.round(m / 60) }) : t('stats.minutesShort', { count: m }));

  const share = async () => {
    setSharing(true);
    try {
      const facts = [];
      if (data.top_genres[0]) facts.push([t('stats.topGenre'), genreName(data.top_genres[0].genre)]);
      if (data.top_titles[0]) facts.push([t('stats.topTitle'), data.top_titles[0].title.title]);
      if (data.top_actors[0]) facts.push([t('stats.topActor'), data.top_actors[0].name]);
      if (data.longest_streak) facts.push([t('stats.longestStreak'), t('stats.days', { count: data.longest_streak.days })]);
      const blob = await drawShareImage({
        year: data.year,
        name: profile?.name || '',
        headline,
        sub: `${t('stats.titlesCount', { count: data.titles })} · ${t('stats.days', { count: data.days })}`,
        facts,
        brand: 'TAURUS',
      });
      const how = await shareOrSave(blob, `my-year-${data.year}.png`, t('stats.title', { year: data.year }));
      if (how === 'saved') setToast(t('stats.saved'));
    } catch (e) {
      setToast(friendlyError(e));
    } finally {
      setSharing(false);
    }
  };

  const years = useMemo(() => {
    const ys = data?.years || [];
    return ys.includes(data?.year) ? ys : [data?.year, ...ys].filter(Boolean);
  }, [data]);

  let body;
  if (error) {
    body = (
      <EmptyState tone="error" title={t('stats.loadError')} actions={<Button variant="primary" onClick={load}>{t('actions.tryAgain')}</Button>}>
        {friendlyError(error)}
      </EmptyState>
    );
  } else if (!data) {
    body = (
      <div className="stats-grid" aria-busy="true" aria-label={t('common:loading')}>
        <Skeleton className="stats-card stats-card--hero" height="14rem" />
        <Skeleton className="stats-card" height="10rem" />
        <Skeleton className="stats-card" height="10rem" />
      </div>
    );
  } else if (!data.minutes) {
    body = (
      <EmptyState
        icon={<StarIcon />}
        title={t('stats.emptyTitle')}
        actions={<Button variant="primary" to="/">{t('actions.goHome')}</Button>}
      >
        {t('stats.emptyText')}
      </EmptyState>
    );
  } else {
    const streak = data.longest_streak;
    body = (
      <div className="stats-grid">
        <section className="stats-card stats-card--hero" tabIndex={0} aria-label={`${data.year}. ${headline}`}>
          <p className="stats-hero__year">{data.year}</p>
          <p className="stats-hero__value">{headline}</p>
          <p className="stats-hero__note">{t('stats.estimate')}</p>
          <dl className="stats-tiles">
            {[
              ['titles', data.titles], ['movies', data.movies], ['shows', data.shows], ['episodes', data.episodes], ['daysWatched', data.days],
            ].map(([k, v]) => (
              <div key={k} className="stats-tile">
                <dt>{t(`stats.${k}`)}</dt>
                <dd>{formatNumber(v)}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="stats-card" tabIndex={0} aria-labelledby="stats-streak">
          <h2 id="stats-streak" className="stats-card__title">{t('stats.longestStreak')}</h2>
          <p className="stats-big">{streak ? t('stats.days', { count: streak.days }) : '—'}</p>
          {streak && streak.days > 1 ? <p className="stats-muted">{t('stats.fromTo', { from: day(streak.from), to: day(streak.to) })}</p> : null}
          {data.current_streak > 1 ? <p className="stats-muted">{t('stats.currentStreak', { count: data.current_streak })}</p> : null}
        </section>

        {data.first ? (
          <section className="stats-card" tabIndex={0} aria-labelledby="stats-first">
            <h2 id="stats-first" className="stats-card__title">{t('stats.first')}</h2>
            <p className="stats-big stats-big--title">{data.first.title.title}</p>
            <p className="stats-muted">{day(data.first.date)}</p>
          </section>
        ) : null}

        <section className="stats-card stats-card--wide" tabIndex={0} aria-labelledby="stats-months">
          <h2 id="stats-months" className="stats-card__title">{t('stats.byMonth')}</h2>
          <MonthChart months={data.months} label={t('stats.byMonth')} />
        </section>

        {data.top_genres.length ? (
          <section className="stats-card stats-card--wide" tabIndex={0} aria-labelledby="stats-genres">
            <h2 id="stats-genres" className="stats-card__title">{t('stats.genres')}</h2>
            <ul className="stats-bars">
              {data.top_genres.map((g) => (
                <li key={g.genre} className="stats-bars__row">
                  <span className="stats-bars__name">{genreName(g.genre)}</span>
                  <span className="stats-bars__track" aria-hidden="true">
                    {/* scaled to the top genre: it fills the track, the share is the text beside it */}
                    <span className="stats-bars__bar" style={{ width: `${Math.max(2, (g.share / data.top_genres[0].share) * 100)}%` }} />
                  </span>
                  <span className="stats-bars__value">{formatNumber(g.share, { style: 'percent' })}</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="stats-card stats-card--wide" aria-labelledby="stats-titles">
          <h2 id="stats-titles" className="stats-card__title">{t('stats.topTitles')}</h2>
          <ul className="ui-scroller stats-row" data-tv-group>
            {data.top_titles.map(({ title, minutes, episodes }) => (
              <li key={title.id}>
                <button type="button" className="stats-title" onClick={() => navigate(title.type === 'tv' ? `/tv/${title.id}` : `/movies/${title.id}`)}>
                  <span className="stats-title__art">
                    {title.poster ? <img src={tmdbImage(title.poster, IMG.poster)} alt="" loading="lazy" decoding="async" /> : null}
                  </span>
                  <span className="stats-title__name">{title.title}</span>
                  <span className="stats-muted">
                    {episodes ? `${t('stats.episodesCount', { count: episodes })} · ` : ''}{titleTime(minutes)}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        {data.top_actors.length ? (
          <section className="stats-card stats-card--wide" aria-labelledby="stats-actors">
            <h2 id="stats-actors" className="stats-card__title">{t('stats.actors')}</h2>
            <ul className="ui-scroller stats-row" data-tv-group>
              {data.top_actors.map((a) => (
                <li key={a.tmdb_id || a.name}>
                  <button type="button" className="stats-actor" disabled={!a.tmdb_id} onClick={() => navigate(`/actor/${a.tmdb_id}`)}>
                    <Avatar src={a.photo ? tmdbImage(a.photo, 'w185') : ''} name={a.name} size="6rem" radius="50%" />
                    <span className="stats-title__name">{a.name}</span>
                    <span className="stats-muted">{t('stats.titlesCount', { count: a.titles })}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="stats-card stats-card--wide stats-share" aria-labelledby="stats-share">
          <div>
            <h2 id="stats-share" className="stats-card__title">{t('stats.shareTitle')}</h2>
            <p className="stats-muted">{t('stats.shareText')}</p>
          </div>
          <Button variant="primary" icon={<ShareIcon />} loading={sharing} onClick={share}>{t('stats.share')}</Button>
        </section>
      </div>
    );
  }

  return (
    <div className="stats-page">
      <Navbar />
      <main className="stats">
        <header className="stats__head">
          <h1 className="stats__title">{t('stats.title', { year: data?.year || '' })}</h1>
          <p className="stats__subtitle">
            {profile ? <Avatar src={profile.avatar_url} name={profile.name} size="1.75rem" /> : null}
            <span>{t('stats.subtitle', { name: profile?.name || '' })}</span>
          </p>
          {years.length > 1 ? (
            <div className="stats__years" role="group" aria-label={t('stats.years')} data-tv-group>
              {years.map((y) => (
                <Chip key={y} selected={y === data?.year} onClick={() => setYear(y)}>{y}</Chip>
              ))}
            </div>
          ) : null}
        </header>
        {body}
      </main>
      <Footer />
      <Toast message={toast} onDone={clearToast} />
    </div>
  );
}

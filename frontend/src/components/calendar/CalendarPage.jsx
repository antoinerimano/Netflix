// src/components/calendar/CalendarPage.jsx
// "Upcoming" (/calendar): new episodes of the profile's shows (followed, in My List, watched lately)
// day by day for the next 30 days, what aired this past week, and popular shows coming back soon
// to follow (backend reco/calendar.py).
// TV remote: one row per day (Up / Down between days, Left / Right inside one: each row is a
// group that remembers its card). OK on an episode that's out opens the player on it, on one
// still to come opens the show. OK on a suggestion follows / unfollows it, and its episodes join
// the calendar.
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { fetchCalendar, setFollow } from '../../api/recoApi';
import { Button, EmptyState, Skeleton, friendlyError } from '../../design';
import { BellIcon, CalendarIcon, CheckIcon } from '../../design/icons';
import { useFormat } from '../../i18n/format';
import { IMG, tmdbImage } from '../../utils/tmdbImage';
import './calendar.css';

const DAY_MS = 86400000;
const toDay = (iso) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
const daysBetween = (from, to) => Math.round((toDay(to) - toDay(from)) / DAY_MS);

/** [{date, items}] in the order the episodes come */
function byDay(episodes) {
  const days = [];
  for (const e of episodes) {
    const last = days[days.length - 1];
    if (last?.date === e.air_date) last.items.push(e);
    else days.push({ date: e.air_date, items: [e] });
  }
  return days;
}

function EpisodeCard({ episode, aired, onOpen }) {
  const { t } = useTranslation('catalog');
  const show = episode.show;
  const image = episode.still || show.landscape_image || show.poster;
  const label = t('calendar.episodeLabel', { show: show.title, season: episode.season, episode: episode.episode_number });
  return (
    <li>
      <button type="button" className="cal-card" onClick={() => onOpen(episode, aired)} aria-label={`${label}. ${episode.name || ''}`}>
        <span className="cal-card__art">
          {image ? <img src={tmdbImage(image, IMG.backdropCard)} alt="" loading="lazy" decoding="async" /> : null}
          <span className="cal-card__badge">{t('episodeShort', { season: episode.season, episode: episode.episode_number })}</span>
        </span>
        <span className="cal-card__show">{show.title}</span>
        <span className="cal-card__name">{episode.name || ' '}</span>
        <span className="cal-card__why">{t(`calendar.reason.${episode.reason}`)}</span>
      </button>
    </li>
  );
}

function DayRow({ id, title, subtitle, episodes, aired, onOpen }) {
  return (
    <section className="cal-day" aria-labelledby={id}>
      <h2 id={id} className="cal-day__title">
        {title}
        {subtitle ? <span className="cal-day__sub">{subtitle}</span> : null}
      </h2>
      <ul className="ui-scroller cal-row" data-tv-group>
        {episodes.map((e) => (
          <EpisodeCard key={e.id} episode={e} aired={aired} onOpen={onOpen} />
        ))}
      </ul>
    </section>
  );
}

export default function CalendarPage() {
  const { t } = useTranslation('catalog');
  const { formatDate, lng } = useFormat();
  const navigate = useNavigate();
  const profileId = localStorage.getItem('activeProfileId');
  const [data, setData] = useState(null); // null: loading
  const [error, setError] = useState(null);
  const [followed, setFollowed] = useState({}); // suggestion id -> following (this visit)

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await fetchCalendar(profileId));
    } catch (e) {
      setError(e);
    }
  }, [profileId]);

  useEffect(() => {
    load();
  }, [load]);

  const open = (episode, aired) => {
    if (aired) navigate(`/watch/${episode.show.id}?season=${episode.season}&episode=${episode.episode_number}`);
    else navigate(`/tv/${episode.show.id}`);
  };

  const toggleFollow = async (show) => {
    const next = !followed[show.id];
    setFollowed((f) => ({ ...f, [show.id]: next }));
    try {
      await setFollow({ profileId, titleId: show.id, following: next });
      const fresh = await fetchCalendar(profileId);
      // keep the suggestion on screen (the remote stays on it); its episodes join the days above
      setData((d) => ({ ...fresh, suggestions: d?.suggestions || fresh.suggestions }));
    } catch {
      setFollowed((f) => ({ ...f, [show.id]: !next }));
    }
  };

  const dayTitle = (date) => {
    const diff = daysBetween(data.today, date);
    const long = formatDate(`${date}T12:00:00Z`, { weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC' });
    const cap = long.charAt(0).toLocaleUpperCase(lng) + long.slice(1);
    if (diff === 0) return { title: t('calendar.today'), subtitle: cap };
    if (diff === 1) return { title: t('calendar.tomorrow'), subtitle: cap };
    return { title: cap, subtitle: t('calendar.inDays', { count: diff }) };
  };

  let body;
  if (error) {
    body = (
      <EmptyState tone="error" title={t('calendar.loadError')} actions={<Button variant="primary" onClick={load}>{t('common:actions.tryAgain')}</Button>}>
        {friendlyError(error)}
      </EmptyState>
    );
  } else if (!data) {
    body = (
      <div className="cal-loading" aria-busy="true" aria-label={t('common:loading')}>
        {[0, 1].map((r) => (
          <div key={r} className="cal-day">
            <Skeleton variant="text" width="12rem" height="1.4rem" />
            <div className="cal-row cal-row--skeleton">
              {[0, 1, 2, 3].map((c) => <Skeleton key={c} className="cal-card__art" />)}
            </div>
          </div>
        ))}
      </div>
    );
  } else {
    const days = byDay(data.upcoming);
    body = (
      <>
        {data.tracked === 0 ? (
          <EmptyState icon={<CalendarIcon />} title={t('calendar.emptyTitle')}>{t('calendar.emptyText')}</EmptyState>
        ) : null}
        {data.tracked > 0 && !days.length ? <p className="cal-nothing">{t('calendar.nothingSoon')}</p> : null}

        {days.map((d) => {
          const { title, subtitle } = dayTitle(d.date);
          return <DayRow key={d.date} id={`cal-${d.date}`} title={title} subtitle={subtitle} episodes={d.items} aired={d.date === data.today} onOpen={open} />;
        })}

        {data.recent.length ? (
          <DayRow id="cal-recent" title={t('calendar.recent')} episodes={data.recent} aired onOpen={open} />
        ) : null}

        {data.suggestions.length ? (
          <section className="cal-day cal-suggest" aria-labelledby="cal-suggest">
            <h2 id="cal-suggest" className="cal-day__title">
              {t('calendar.suggestTitle')}
              <span className="cal-day__sub">{t('calendar.suggestText')}</span>
            </h2>
            <ul className="ui-scroller cal-row" data-tv-group>
              {data.suggestions.map((s) => {
                const on = !!followed[s.id];
                const diff = daysBetween(data.today, s.next.air_date);
                const when = diff <= 1 ? t(diff === 0 ? 'calendar.today' : 'calendar.tomorrow') : t('calendar.inDays', { count: diff });
                const ep = t('episodeShort', { season: s.next.season, episode: s.next.episode });
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      className={`cal-card cal-card--follow${on ? ' is-on' : ''}`}
                      aria-pressed={on}
                      aria-label={`${t('calendar.follow')}: ${s.title}, ${ep}, ${when}`}
                      onClick={() => toggleFollow(s)}
                    >
                      <span className="cal-card__art">
                        {s.landscape_image || s.poster ? (
                          <img src={tmdbImage(s.landscape_image || s.poster, IMG.backdropCard)} alt="" loading="lazy" decoding="async" />
                        ) : null}
                        <span className="cal-card__badge">{ep}</span>
                      </span>
                      <span className="cal-card__show">{s.title}</span>
                      <span className="cal-card__name">{when}</span>
                      <span className="cal-card__follow">
                        {on ? <CheckIcon /> : <BellIcon />}
                        {on ? t('calendar.following') : t('calendar.follow')}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ) : null}
      </>
    );
  }

  return (
    <div className="calendar-page">
      <Navbar />
      <main className="calendar">
        <header className="calendar__head">
          <h1 className="calendar__title">{t('calendar.title')}</h1>
          <p className="calendar__subtitle">{t('calendar.subtitle')}</p>
        </header>
        {body}
      </main>
      <Footer />
    </div>
  );
}

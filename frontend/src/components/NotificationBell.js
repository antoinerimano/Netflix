// src/components/NotificationBell.js
// Navbar bell: new episodes of the shows this profile follows ("Notify me" on a show page).
// Panel: header, "New" (unseen) and "Earlier" sections, episode cards (image, show, S/E, when),
// an empty state that explains how to get alerts. Phones: a full-width sheet under the bar.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { formatDate, formatRelativeDay } from '../i18n/format';
import { fetchNotifications, markNotificationsRead } from '../api/recoApi';
import { tmdbImage } from '../utils/tmdbImage';
import { BellIcon, PlayIcon, TvIcon } from '../design/icons';
import { Button } from '../design';
import './NotificationBell.css';

const REFRESH_MS = 5 * 60 * 1000;

/** "Today", "Yesterday", "3 days ago", "Mar 4" (in the app's language) */
function whenAired(dateStr, lng) {
  if (!dateStr) return '';
  const day = String(dateStr).slice(0, 10);
  const d = new Date(`${day}T00:00:00`);
  if (Number.isNaN(d.getTime())) return '';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((today - d) / 86400000);
  if (days < 7) return formatRelativeDay(Math.max(days, 0), lng);
  return formatDate(day, { month: 'short', day: 'numeric' }, lng);
}

function Item({ n, onOpen }) {
  const { t, i18n } = useTranslation('catalog');
  const when = whenAired(n.air_date, i18n.resolvedLanguage);
  return (
    <li>
      <button type="button" className={`notif__item${n.read ? '' : ' is-new'}`} onClick={() => onOpen(n)}>
        <span className="notif__thumb">
          {n.image ? (
            <img src={tmdbImage(n.image, 'w300')} alt="" loading="lazy" />
          ) : (
            <TvIcon className="notif__thumb-icon" aria-hidden="true" />
          )}
          <span className="notif__play" aria-hidden="true">
            <PlayIcon />
          </span>
        </span>
        <span className="notif__text">
          <span className="notif__show">{n.show}</span>
          <span className="notif__ep">
            {t('notifications.newEpisode', { season: n.season, episode: n.episode })}
          </span>
          {when ? <span className="notif__when">{when}</span> : null}
        </span>
        {n.read ? null : <span className="notif__dot" aria-label={t('notifications.new')} />}
      </button>
    </li>
  );
}

export default function NotificationBell() {
  const { t } = useTranslation('catalog');
  const navigate = useNavigate();
  const [profileId, setProfileId] = useState(() => localStorage.getItem('activeProfileId'));
  const [data, setData] = useState({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const load = useCallback(() => {
    if (!profileId) return;
    fetchNotifications(profileId)
      .then(setData)
      .catch(() => {});
  }, [profileId]);

  useEffect(() => {
    const onChange = () => setProfileId(localStorage.getItem('activeProfileId'));
    window.addEventListener('activeProfileChanged', onChange);
    return () => window.removeEventListener('activeProfileChanged', onChange);
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, [load]);

  // close when clicking or moving the focus (Tab / remote) elsewhere
  useEffect(() => {
    if (!open) return undefined;
    const onOutside = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener('mousedown', onOutside);
    document.addEventListener('focusin', onOutside);
    return () => {
      document.removeEventListener('mousedown', onOutside);
      document.removeEventListener('focusin', onOutside);
    };
  }, [open]);

  if (!profileId) return null;

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && data.unread > 0) {
      // seen: the badge goes; the items keep their "new" look until the panel is reopened
      markNotificationsRead(profileId).catch(() => {});
      setData((d) => ({ ...d, unread: 0 }));
    }
    if (!next) load(); // closed: next time, what was new is "Earlier"
  };

  const openEpisode = (n) => {
    setOpen(false);
    navigate(`/watch/${n.title_id}?season=${n.season}&episode=${n.episode}`);
  };

  const fresh = data.items.filter((n) => !n.read);
  const earlier = data.items.filter((n) => n.read);

  return (
    <div className="notif" ref={ref}>
      <button
        type="button"
        className="notif__button"
        onClick={toggle}
        aria-label={data.unread ? t('notifications.unread', { count: data.unread }) : t('notifications.title')}
        aria-expanded={open}
        title={t('notifications.subtitle')}
      >
        <BellIcon />
        {data.unread > 0 && <span className="notif__badge">{data.unread > 9 ? '9+' : data.unread}</span>}
      </button>

      {open && (
        <div className="notif__panel" role="dialog" aria-label={t('notifications.title')}>
          <header className="notif__head">
            <h2 className="notif__title">{t('notifications.title')}</h2>
            <span className="notif__sub">{t('notifications.subtitle')}</span>
          </header>

          {data.items.length === 0 ? (
            <div className="notif__empty">
              <span className="notif__empty-icon" aria-hidden="true">
                <BellIcon />
              </span>
              <p className="notif__empty-title">{t('notifications.emptyTitle')}</p>
              <p className="notif__empty-text">{t('notifications.emptyText')}</p>
              <Button
                variant="glass"
                size="sm"
                onClick={() => {
                  setOpen(false);
                  navigate('/tv');
                }}
              >
                {t('notifications.browse')}
              </Button>
            </div>
          ) : (
            <div className="notif__lists">
              {fresh.length ? (
                <section>
                  <h3 className="notif__group">{t('notifications.new')}</h3>
                  <ul className="notif__list">
                    {fresh.map((n) => (
                      <Item key={n.id} n={n} onOpen={openEpisode} />
                    ))}
                  </ul>
                </section>
              ) : null}
              {earlier.length ? (
                <section>
                  <h3 className="notif__group">{t('notifications.earlier')}</h3>
                  <ul className="notif__list">
                    {earlier.map((n) => (
                      <Item key={n.id} n={n} onOpen={openEpisode} />
                    ))}
                  </ul>
                </section>
              ) : null}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

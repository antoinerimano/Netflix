// src/components/NotificationBell.js
// Navbar bell: new episodes of the shows this profile follows ("Notify me" on a show page).
// Panel: header, "New" (unseen) and "Earlier" sections, episode cards (image, show, S/E, when),
// an empty state that explains how to get alerts. Phones: a full-width sheet under the bar.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchNotifications, markNotificationsRead } from '../api/recoApi';
import { tmdbImage } from '../utils/tmdbImage';
import { BellIcon, PlayIcon, TvIcon } from '../design/icons';
import { Button } from '../design';
import './NotificationBell.css';

const REFRESH_MS = 5 * 60 * 1000;

/** "Today", "Yesterday", "3 days ago", "Mar 4" */
function whenAired(dateStr) {
  if (!dateStr) return '';
  const d = new Date(`${String(dateStr).slice(0, 10)}T00:00:00`);
  if (Number.isNaN(d.getTime())) return '';
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((today - d) / 86400000);
  if (days <= 0) return 'Today';
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function Item({ n, onOpen }) {
  const when = whenAired(n.air_date);
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
            New episode · S{n.season} E{n.episode}
          </span>
          {when ? <span className="notif__when">{when}</span> : null}
        </span>
        {n.read ? null : <span className="notif__dot" aria-label="New" />}
      </button>
    </li>
  );
}

export default function NotificationBell() {
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
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
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
        aria-label={data.unread ? `${data.unread} new episode${data.unread > 1 ? 's' : ''}` : 'Notifications'}
        aria-expanded={open}
        title="New episodes of shows you follow"
      >
        <BellIcon />
        {data.unread > 0 && <span className="notif__badge">{data.unread > 9 ? '9+' : data.unread}</span>}
      </button>

      {open && (
        <div className="notif__panel" role="dialog" aria-label="Notifications">
          <header className="notif__head">
            <h2 className="notif__title">Notifications</h2>
            <span className="notif__sub">New episodes of the shows you follow</span>
          </header>

          {data.items.length === 0 ? (
            <div className="notif__empty">
              <span className="notif__empty-icon" aria-hidden="true">
                <BellIcon />
              </span>
              <p className="notif__empty-title">No new episodes yet</p>
              <p className="notif__empty-text">Tap the bell on a show's page to get an alert when a new episode is out.</p>
              <Button
                variant="glass"
                size="sm"
                onClick={() => {
                  setOpen(false);
                  navigate('/tv');
                }}
              >
                Browse TV shows
              </Button>
            </div>
          ) : (
            <div className="notif__lists">
              {fresh.length ? (
                <section>
                  <h3 className="notif__group">New</h3>
                  <ul className="notif__list">
                    {fresh.map((n) => (
                      <Item key={n.id} n={n} onOpen={openEpisode} />
                    ))}
                  </ul>
                </section>
              ) : null}
              {earlier.length ? (
                <section>
                  <h3 className="notif__group">Earlier</h3>
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

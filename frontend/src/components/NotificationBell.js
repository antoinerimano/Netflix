// src/components/NotificationBell.js
// Navbar bell: new episodes of the shows this profile follows ("Notify me").
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchNotifications, markNotificationsRead } from "../api/recoApi";
import "./NotificationBell.css";
import { tmdbImage } from "../utils/tmdbImage";

const REFRESH_MS = 5 * 60 * 1000;

export default function NotificationBell() {
  const navigate = useNavigate();
  const [profileId, setProfileId] = useState(() => localStorage.getItem("activeProfileId"));
  const [data, setData] = useState({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  const load = useCallback(() => {
    if (!profileId) return;
    fetchNotifications(profileId).then(setData).catch(() => {});
  }, [profileId]);

  useEffect(() => {
    const onChange = () => setProfileId(localStorage.getItem("activeProfileId"));
    window.addEventListener("activeProfileChanged", onChange);
    return () => window.removeEventListener("activeProfileChanged", onChange);
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  // close when clicking or moving the focus (Tab / remote) elsewhere
  useEffect(() => {
    if (!open) return;
    const onOutside = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", onOutside);
    document.addEventListener("focusin", onOutside);
    return () => {
      document.removeEventListener("mousedown", onOutside);
      document.removeEventListener("focusin", onOutside);
    };
  }, [open]);

  if (!profileId) return null;

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && data.unread > 0) {
      // seen: clear the badge (items keep their "new" look until the list is reopened)
      markNotificationsRead(profileId).catch(() => {});
      setData((d) => ({ ...d, unread: 0 }));
    }
  };

  const openEpisode = (n) => {
    setOpen(false);
    navigate(`/watch/${n.title_id}?season=${n.season}&episode=${n.episode}`);
  };

  return (
    <div className="notif" ref={ref}>
      <button
        type="button"
        className="notif__button"
        onClick={toggle}
        aria-label={data.unread ? `${data.unread} new episodes` : "Notifications"}
        title="New episodes of shows you follow"
      >
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {data.unread > 0 && <span className="notif__badge">{data.unread > 9 ? "9+" : data.unread}</span>}
      </button>

      {open && (
        <div className="notif__panel">
          {data.items.length === 0 ? (
            <div className="notif__empty">
              No new episodes yet. Click "Notify me" on a show to get an alert when one is out.
            </div>
          ) : (
            data.items.map((n) => (
              <button
                type="button"
                key={n.id}
                className={`notif__item${n.read ? "" : " notif__item--new"}`}
                onClick={() => openEpisode(n)}
              >
                {n.image ? <img src={tmdbImage(n.image, "w300")} alt="" loading="lazy" /> : <span className="notif__thumb" />}
                <span className="notif__text">
                  <strong>{n.show}</strong>
                  <span>New episode: S{n.season} E{n.episode}</span>
                </span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

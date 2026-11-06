// src/components/profiles/TastePage.jsx
// "What do you like to watch?" (/taste): a new profile picks a few titles it likes before its
// first home page (backend: reco/taste.py). The picks are saved as likes and the home page is
// rebuilt from them, so it is personal from the first visit. Skip is always there.
// Shown after creating a profile, and from the home page banner while a profile has no likes.
// TV remote: starts on the first poster, OK picks / unpicks, Right at a line's end goes on to the
// next line, Down from the last line lands on Continue in the pinned bar (Up returns to the poster
// you were on), Back = Skip (after sign up, the previous page would be the sign-up form).
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { fetchTasteTitles, saveTaste } from '../../api/recoApi';
import { Button, EmptyState, Skeleton, friendlyError } from '../../design';
import { CheckIcon } from '../../design/icons';
import { IMG, tmdbImage } from '../../utils/tmdbImage';
import { getActiveProfileId } from '../../utils/activeProfile';
import { setBackHandler } from '../../tv/spatialNavigation';
import '../PosterCard.css';
import './profiles.css';

const FIRST_SCREEN = 30; // the rest behind "Show more"

export default function TastePage() {
  const { t } = useTranslation('profiles');
  const navigate = useNavigate();
  const profileId = getActiveProfileId();
  const [titles, setTitles] = useState(null); // null: loading
  const [minPicks, setMinPicks] = useState(3);
  const [error, setError] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [picked, setPicked] = useState(() => new Set());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    setTitles(null);
    try {
      const data = await fetchTasteTitles(profileId);
      setTitles(data?.titles || []);
      if (data?.min_picks) setMinPicks(data.min_picks);
    } catch (e) {
      setError(e);
      setTitles([]);
    }
  }, [profileId]);

  useEffect(() => {
    load();
  }, [load]);

  // the remote starts on the first poster once they're here (otherwise the focus left behind by
  // the profile dialog landed on the nearest thing on screen: the "Import" link)
  const loaded = !!titles?.length;
  useEffect(() => {
    if (loaded) document.querySelector('.taste-card')?.focus({ preventScroll: true });
  }, [loaded]);

  const toggle = (id) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const goHome = useCallback(() => navigate('/', { replace: true }), [navigate]);
  useEffect(() => setBackHandler(goHome), [goHome]);

  const finish = async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await saveTaste(profileId, [...picked]);
      goHome();
    } catch (e) {
      setSaveError(friendlyError(e, 'profiles'));
      setSaving(false);
    }
  };

  const missing = Math.max(0, minPicks - picked.size);
  const shown = titles ? (showAll ? titles : titles.slice(0, FIRST_SCREEN)) : [];

  let body;
  if (titles === null) {
    body = (
      <div className="poster-grid taste__grid" aria-busy="true" aria-label={t('common:loading')}>
        {Array.from({ length: 18 }, (_, i) => (
          <Skeleton key={i} className="taste__skeleton" />
        ))}
      </div>
    );
  } else if (error || !titles.length) {
    body = (
      <EmptyState
        tone={error ? 'error' : 'empty'}
        title={error ? t('taste.loadError') : t('taste.none')}
        actions={
          <>
            {error ? <Button variant="primary" onClick={load}>{t('actions.tryAgain')}</Button> : null}
            <Button variant="secondary" onClick={goHome}>{t('taste.skip')}</Button>
          </>
        }
      >
        {error ? friendlyError(error, 'profiles') : null}
      </EmptyState>
    );
  } else {
    body = (
      <>
        <ul className="poster-grid taste__grid" data-tv-group>
          {shown.map((item, idx) => {
            const on = picked.has(item.id);
            return (
              <li key={item.id}>
                <button
                  type="button"
                  className={`taste-card${on ? ' is-picked' : ''}`}
                  aria-pressed={on}
                  data-tv-start={idx === 0 ? '' : undefined}
                  onClick={() => toggle(item.id)}
                >
                  <span className="poster-card__art">
                    <span className="poster-card__fallback">{item.title}</span>
                    {item.poster ? (
                      <img
                        src={tmdbImage(item.poster, IMG.poster)}
                        alt=""
                        loading={idx < 12 ? 'eager' : 'lazy'}
                        decoding="async"
                      />
                    ) : null}
                    <span className="taste-card__check" aria-hidden="true">
                      <CheckIcon />
                    </span>
                  </span>
                  <span className="taste-card__name">{item.title}</span>
                  {item.release_year ? <span className="taste-card__year">{item.release_year}</span> : null}
                </button>
              </li>
            );
          })}
        </ul>
        {!showAll && titles.length > FIRST_SCREEN ? (
          <div className="taste__more">
            <Button variant="glass" onClick={() => setShowAll(true)}>{t('taste.showMore')}</Button>
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="profile-gate taste">
      <header className="profiles__top">
        <img src="/logo/navbar-logo.svg" alt="Taurus" className="profiles__logo" width="927" height="108" />
      </header>
      <main className="taste__main">
        <div className="profiles__intro taste__intro">
          <h1 className="profiles__title">{t('taste.title')}</h1>
          <p className="taste__subtitle">{t('taste.subtitle', { count: minPicks })}</p>
          <Button variant="glass" size="sm" to="/import" className="taste__import">{t('taste.importLink')}</Button>
        </div>
        {body}
      </main>
      {titles?.length ? (
        <div className="taste__bar" role="region" aria-label={t('taste.barLabel')}>
          <p className="taste__count" aria-live="polite">
            {saveError || (missing ? t('taste.pickMore', { count: missing }) : t('taste.picked', { count: picked.size }))}
          </p>
          {/* remote: coming down from the posters lands on Continue (once it can be pressed) */}
          <div className="taste__actions" data-tv-group>
            <Button variant="ghost" onClick={goHome} disabled={saving}>{t('taste.skip')}</Button>
            <Button variant="primary" onClick={finish} disabled={missing > 0} loading={saving} data-tv-current>
              {saving ? t('taste.building') : t('actions.continue')}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

// src/components/collection/CollectionPage.jsx
// A franchise in watch order (/collection/:id): its movies numbered in release order, what the
// profile watched (checks, "2 of 4 watched"), and one button for what's next (backend
// reco/collections.py). Reached from a movie page ("Part of ...") and the home row "Next in your
// collections".
// TV remote: starts on the main button (watch next / start); Down goes to the movies (a group:
// Right / Left along, wrapping); OK opens a movie's page.
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { fetchCollection } from '../../api/recoApi';
import { Button, EmptyState, Skeleton, friendlyError } from '../../design';
import { PlayIcon } from '../../design/icons';
import { IMG, tmdbBackground } from '../../utils/tmdbImage';
import { usePageTitle } from '../../utils/pageTitle';
import PartCard from './PartCard';
import './collection.css';

export default function CollectionPage() {
  const { t } = useTranslation('catalog');
  const { id } = useParams();
  const navigate = useNavigate();
  const profileId = localStorage.getItem('activeProfileId');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await fetchCollection(profileId, id));
    } catch (e) {
      setError(e);
    }
  }, [profileId, id]);

  useEffect(() => {
    load();
  }, [load]);

  usePageTitle(data?.name); // "<name> | Tauruss" in the browser tab

  const openTitle = (title) => navigate(`/movies/${title.id}`);

  let body;
  if (error) {
    const missing = error?.response?.status === 404;
    body = (
      <EmptyState
        page
        tone={missing ? 'empty' : 'error'}
        title={missing ? t('collection.notFound') : t('collection.loadError')}
        actions={missing ? <Button variant="primary" to="/">{t('common:actions.goHome')}</Button> : <Button variant="primary" onClick={load}>{t('common:actions.tryAgain')}</Button>}
      >
        {missing ? null : friendlyError(error)}
      </EmptyState>
    );
  } else if (!data) {
    body = (
      <div className="coll" aria-busy="true" aria-label={t('common:loading')}>
        <Skeleton width="min(28rem, 80%)" height="3rem" />
        <div className="coll__parts">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="coll-part__art" />)}
        </div>
      </div>
    );
  } else {
    const started = data.watched > 0;
    const allSeen = !data.next && data.watched > 0;
    const pct = data.total ? Math.round((data.watched / data.total) * 100) : 0;
    body = (
      <>
        <header className="coll-hero" style={{ backgroundImage: tmdbBackground(data.backdrop, IMG.backdropHero) }}>
          <div className="coll-hero__shade" />
          <div className="coll-hero__content">
            <p className="coll-hero__kicker">{t('collection.kicker', { count: data.total })}</p>
            <h1 className="coll-hero__title">{data.name}</h1>
            <div className="coll-hero__progress">
              <span className="coll-meter" role="progressbar" aria-valuemin={0} aria-valuemax={data.total} aria-valuenow={data.watched} aria-label={t('collection.progress', { watched: data.watched, total: data.total })}>
                <span className="coll-meter__fill" style={{ width: `${pct}%` }} />
              </span>
              <span>{allSeen ? t('collection.allWatched') : t('collection.progress', { watched: data.watched, total: data.total })}</span>
            </div>
            {data.next ? (
              <div className="coll-hero__actions">
                <Button variant="primary" size="lg" icon={<PlayIcon />} onClick={() => navigate(`/watch/${data.next.id}`)}>
                  {started ? t('collection.watchNext', { title: data.next.title }) : t('collection.startWith', { title: data.next.title })}
                </Button>
              </div>
            ) : null}
          </div>
        </header>

        <section className="coll" aria-labelledby="coll-order">
          <h2 id="coll-order" className="coll__title">{t('collection.order')}</h2>
          <ul className="coll__parts" data-tv-group>
            {data.parts.map((p) => (
              <li key={p.title.id}>
                <PartCard part={p} onOpen={openTitle} />
              </li>
            ))}
          </ul>
        </section>
      </>
    );
  }

  return (
    <div className="collection-page">
      <Navbar />
      <main>{body}</main>
      <Footer />
    </div>
  );
}

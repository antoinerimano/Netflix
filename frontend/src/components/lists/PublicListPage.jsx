// src/components/lists/PublicListPage.jsx
// A shared list (/l/:shareId), for anyone with the link, signed in or not: its name, author,
// description and titles (posters that open their pages). Signed in: "Save a copy" (a private
// copy in your lists); signed out: "Make your own lists" (sign up). Django serves this address
// with the list's own title / description / picture for link previews (users/seo.py).
// TV remote: starts on the main button; the posters are a grid (a group, wrapping at line ends).
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { copyPublicList, fetchPublicList } from '../../api/listsApi';
import { Button, EmptyState, Skeleton, friendlyError } from '../../design';
import { IMG, tmdbImage } from '../../utils/tmdbImage';
import { usePageTitle } from '../../utils/pageTitle';
import '../PosterCard.css';
import './lists.css';

export default function PublicListPage() {
  const { t } = useTranslation('catalog');
  const { shareId } = useParams();
  const navigate = useNavigate();
  const profileId = localStorage.getItem('activeProfileId');
  const signedIn = !!localStorage.getItem('access') && !!profileId;
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  usePageTitle(data?.name);

  useEffect(() => {
    let alive = true;
    setError(null);
    fetchPublicList(shareId)
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e));
    return () => {
      alive = false;
    };
  }, [shareId]);

  const saveCopy = async () => {
    setBusy(true);
    try {
      const copy = await copyPublicList(profileId, shareId);
      navigate(`/lists/${copy.id}`);
    } catch (e) {
      setBusy(false);
      setError(e);
    }
  };

  let body;
  if (error) {
    const missing = error?.response?.status === 404;
    body = (
      <EmptyState
        page
        tone={missing ? 'empty' : 'error'}
        title={missing ? t('lists.notFound') : t('lists.loadError')}
        actions={<Button variant="primary" to="/">{t('common:actions.goHome')}</Button>}
      >
        {missing ? t('lists.notFoundText') : friendlyError(error)}
      </EmptyState>
    );
  } else if (!data) {
    body = (
      <div className="public-list" aria-busy="true" aria-label={t('common:loading')}>
        <Skeleton width="min(24rem, 80%)" height="2.5rem" />
        <div className="poster-grid">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} style={{ aspectRatio: '2 / 3' }} />)}</div>
      </div>
    );
  } else {
    body = (
      <div className="public-list">
        <header className="public-list__head">
          <p className="public-list__by">{t('lists.by', { name: data.owner })} · {t('lists.count', { count: data.count })}</p>
          <h1 className="public-list__title">{data.name}</h1>
          {data.description ? <p className="public-list__desc">{data.description}</p> : null}
          <div className="public-list__actions">
            {signedIn ? (
              <Button variant="primary" loading={busy} onClick={saveCopy}>{t('lists.saveCopy')}</Button>
            ) : (
              <Button variant="primary" to="/register">{t('lists.makeYourOwn')}</Button>
            )}
          </div>
        </header>
        <ul className="poster-grid public-list__grid" data-tv-group>
          {data.items.map(({ title }) => (
            <li key={title.id}>
              <button
                type="button"
                className="public-item"
                onClick={() => navigate(title.type === 'tv' ? `/tv/${title.id}` : `/movies/${title.id}`)}
              >
                <span className="public-item__art">
                  <span className="poster-card__fallback">{title.title}</span>
                  {title.poster ? <img src={tmdbImage(title.poster, IMG.poster)} alt="" loading="lazy" decoding="async" /> : null}
                </span>
                <span className="public-item__name">{title.title}</span>
                <span className="public-item__meta">
                  {[t(title.type === 'tv' ? 'common:kind.tv' : 'common:kind.movie'), title.release_year].filter(Boolean).join(' · ')}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="public-list-page">
      <Navbar />
      <main>{body}</main>
      <Footer />
    </div>
  );
}

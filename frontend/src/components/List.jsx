// List.jsx
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from './Navbar';
import MovieCard from './MovieCard';
import Footer from './Footer';
import './PosterCard.css';
import './browse/browse.css';
import { logTitleClick, logActionBeacon } from '../api/analyticsApi';
import { fetchMyList, setInMyList } from '../api/myListApi';
import { Button, EmptyState, Skeleton } from '../design';
import { PlusIcon } from '../design/icons';
import YourLists from './lists/YourLists';

const List = () => {
  const { t, i18n } = useTranslation('catalog');
  const navigate = useNavigate();

  const [activeProfileId, setActiveProfileId] = useState(() =>
    localStorage.getItem('activeProfileId')
  );
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const onChange = () => setActiveProfileId(localStorage.getItem('activeProfileId'));
    window.addEventListener('activeProfileChanged', onChange);
    return () => window.removeEventListener('activeProfileChanged', onChange);
  }, []);

  // load when profile changes (saved on the server, newest first)
  useEffect(() => {
    let alive = true;
    setError('');
    if (!activeProfileId) {
      setList([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    fetchMyList(activeProfileId)
      .then((items) => alive && setList(items))
      .catch(() => alive && setError(t('list.loadErrorText')))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [activeProfileId, i18n.resolvedLanguage]); // eslint-disable-line react-hooks/exhaustive-deps -- t follows the language

  const getDetailPath = (item) => {
    const isTv =
      String(item?.type || item?.media_type || '').toLowerCase() === 'tv' ||
      !!item?.first_air_date;
    return `/${isTv ? 'tv' : 'movies'}/${item?.id}`;
  };

  const handleItemClick = (item, index) => {
    if (item?.id) {
      logTitleClick({
        title_id: item.id,
        surface: 'my_list',
        position: index,
        row_title: 'My List',
      });
    }
    navigate(getDetailPath(item));
  };

  const handleRemove = (itemId) => {
    const before = list;
    setList((prev) => prev.filter((i) => i.id !== itemId));
    logActionBeacon({ title_id: itemId, action: 'add_to_list', surface: 'my_list', provider: 'remove' });
    setInMyList(activeProfileId, itemId, false).catch(() => setList(before)); // put it back if it failed
  };

  return (
    <div className="browse">
      <Navbar />
      {/* the page's title, then the lists this profile made ("New list"), then My List's titles */}
      <header className="browse__head">
        <div className="browse__titles">
          <h1 className="browse__title">{t('common:nav.myList')}</h1>
          {!loading && !error && list.length > 0 ? (
            <span className="browse__count">{t('list.count', { count: list.length })}</span>
          ) : null}
        </div>
      </header>
      {activeProfileId ? <YourLists key={activeProfileId} /> : null}
      {!loading && (error || list.length === 0) ? (
        error ? (
          <EmptyState
            tone="error"
            title={t('list.loadError')}
            actions={<Button variant="primary" onClick={() => window.location.reload()}>{t('actions.tryAgain')}</Button>}
          >
            {error}
          </EmptyState>
        ) : (
          <EmptyState
            icon={<PlusIcon />}
            title={t('list.emptyTitle')}
            actions={
              <>
                <Button variant="primary" to="/movies">{t('detail.browseMovies')}</Button>
                <Button variant="glass" to="/tv">{t('notifications.browse')}</Button>
              </>
            }
          >
            {t('list.emptyText')}
          </EmptyState>
        )
      ) : (
      <div className="poster-grid browse__body">
        {loading ? (
          Array.from({ length: 12 }, (_, i) => (
            <div key={i} className="browse__skeleton">
              <Skeleton style={{ aspectRatio: '2 / 3' }} />
              <Skeleton variant="text" width="80%" />
            </div>
          ))
        ) : (
          list.map((item, idx) => (
            <MovieCard
              key={item.id}
              movie={item}
              analytics={{ surface: 'my_list', position: idx, row_title: 'My List' }}
              onClick={() => handleItemClick(item, idx)}
              onRemove={() => handleRemove(item.id)}
            />
          ))
        )}
      </div>
      )}
      <Footer />
    </div>
  );
};

export default List;

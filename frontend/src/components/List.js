// List.jsx
import React, { useEffect, useState } from 'react';
import './Movies.css';
import { useNavigate } from 'react-router-dom';
import Navbar from './Navbar';
import MovieCard from './MovieCard';
import './List.css';
import { logTitleClick, logActionBeacon } from '../api/analyticsApi';
import { fetchMyList, setInMyList } from '../api/myListApi';

const List = () => {
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
      .catch(() => alive && setError('Could not load your list.'))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [activeProfileId]);

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
    <div>
      <Navbar />
      <div className="ps-store-movie-grid">
        {loading ? (
          <p>Loading…</p>
        ) : error ? (
          <p>{error}</p>
        ) : list.length > 0 ? (
          list.map((item, idx) => (
            <MovieCard
              key={item.id}
              movie={item}
              analytics={{ surface: 'my_list', position: idx, row_title: 'My List' }}
              onClick={() => handleItemClick(item, idx)}
              onRemove={() => handleRemove(item.id)}
            />
          ))
        ) : (
          <p>Your list is empty</p>
        )}
      </div>
    </div>
  );
};

export default List;

// List.jsx
import React, { useEffect, useRef, useState } from 'react';
import './Movies.css';
import { useNavigate } from 'react-router-dom';
import Navbar from './Navbar';
import MovieCard from './MovieCard';
import './List.css';
import { logTitleClick } from '../api/analyticsApi';

const List = () => {
  const navigate = useNavigate();

  const [activeProfileId, setActiveProfileId] = useState(() =>
    localStorage.getItem('activeProfileId')
  );
  const [list, setList] = useState([]);

  const hydrated = useRef(false);

  useEffect(() => {
    const onChange = () => setActiveProfileId(localStorage.getItem('activeProfileId'));
    window.addEventListener('activeProfileChanged', onChange);
    return () => window.removeEventListener('activeProfileChanged', onChange);
  }, []);

  // load when profile changes
  useEffect(() => {
    hydrated.current = false;

    if (!activeProfileId) {
      setList([]);
      return;
    }
    const raw = localStorage.getItem(`userList_${activeProfileId}`);
    setList(raw ? JSON.parse(raw) : []);

    Promise.resolve().then(() => {
      hydrated.current = true;
    });
  }, [activeProfileId]);

  // save only after initial load
  useEffect(() => {
    if (!activeProfileId) return;
    if (!hydrated.current) return;
    localStorage.setItem(`userList_${activeProfileId}`, JSON.stringify(list));
  }, [list, activeProfileId]);

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

  const handleRemove = (itemId) => setList((prev) => prev.filter((i) => i.id !== itemId));

  return (
    <div>
      <Navbar />
      <div className="ps-store-movie-grid">
        {list.length > 0 ? (
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

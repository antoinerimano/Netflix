// MovieCard.jsx
import React from 'react';
import './Movies.css';
import { useNavigate } from 'react-router-dom';
import { logTitleClick } from '../api/analyticsApi';
import { tmdbImage, tmdbSrcSet, IMG } from '../utils/tmdbImage';


const MovieCard = ({ movie, onRemove, onClick, analytics }) => {
  const navigate = useNavigate();





  const isTv =
    String(movie?.type || movie?.media_type || '')
      .toLowerCase() === 'tv' || !!movie?.first_air_date;

  const defaultNavigate = () => {
    navigate(`/${isTv ? 'tv' : 'movies'}/${movie.id}`);
  };

  const handleRootClick = () => {
    if (movie?.id) {
      logTitleClick({
        title_id: movie.id,
        surface: analytics?.surface || 'unknown',
        position: analytics?.position,
        row_title: analytics?.row_title,
      });
    }

    if (typeof onClick === 'function') onClick();
    else defaultNavigate();
  };


  return (
    <div className="ps-store-movie-card" onClick={handleRootClick}>
      <img src={tmdbImage(movie.poster, IMG.poster)} srcSet={tmdbSrcSet(movie.poster, [185, 342, 500])} sizes="(max-width: 600px) 45vw, 200px" alt={movie.title} className="ps-store-movie-poster" loading="lazy"
        decoding="async" />
      <div className="ps-store-movie-info">
        <h3 className="ps-store-movie-title">{movie.title}</h3>
        <p className="ps-store-movie-description">{movie.description}</p>
      </div>
      {onRemove && (
        <button
          className="remove-button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove(movie.id);
          }}
        >
          &times;
        </button>
      )}
    </div>
  );
};

export default MovieCard;

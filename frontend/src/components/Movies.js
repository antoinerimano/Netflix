import React, { useEffect, useState } from 'react';
import Navbar from '../components/Navbar';
import MovieCard from './MovieCard';
import { fetchMoviesPage, fetchGenres } from '../api/titlesApi';
import { useLocation, useNavigate } from "react-router-dom";

const PAGE_SIZE = 50;

const Movie = () => {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  const [genres, setGenres] = useState([]);

  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');

    const YEAR_MIN_BOUND = 1900;
  const YEAR_MAX_BOUND = new Date().getFullYear();

  const setYearMax = (val) => {
    const v = val === '' ? '' : String(val);
    setDraftFilters((prev) => clampYearRange({ ...prev, yearMax: v }));
  };

  const bumpYearMax = (delta) => {
    const current = draftFilters.yearMax === '' ? YEAR_MAX_BOUND : parseInt(draftFilters.yearMax, 10);
    let next = Number.isFinite(current) ? current + delta : YEAR_MAX_BOUND;

    if (next < YEAR_MIN_BOUND) next = YEAR_MIN_BOUND;
    if (next > YEAR_MAX_BOUND) next = YEAR_MAX_BOUND;

    setYearMax(next);
  };

  const handleYearMaxKeyDown = (e) => {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      bumpYearMax(1);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      bumpYearMax(-1);
    }
  };


  // Ce que l'utilisateur tape (NE déclenche PAS la recherche)
  const [draftFilters, setDraftFilters] = useState({
    genre: '',
    ratingMin: '',
    yearMin: '',
    yearMax: '',
    director: '',
    actor: '',
  });

  const navigate = useNavigate();
  const location = useLocation();

  // Ce qui est réellement appliqué (déclenche la recherche)
  const [appliedFilters, setAppliedFilters] = useState({});

  const readUrlState = () => {
    const sp = new URLSearchParams(location.search);

    const urlDraft = {
      genre: sp.get("genre") || "",
      ratingMin: sp.get("ratingMin") || "",
      yearMin: sp.get("yearMin") || "",
      yearMax: sp.get("yearMax") || "",
      director: sp.get("director") || "",
      actor: sp.get("actor") || "",
    };

    const urlApplied = Object.fromEntries(
      Object.entries(urlDraft).filter(([_, v]) => String(v || "").trim() !== "")
    );

    const urlPage = Math.max(1, parseInt(sp.get("page") || "1", 10) || 1);

    return { urlDraft, urlApplied, urlPage };
  };

  const pushUrlState = (next = {}) => {
    const sp = new URLSearchParams(location.search);

    ["genre", "ratingMin", "yearMin", "yearMax", "director", "actor", "page"].forEach((k) => {
      if (Object.prototype.hasOwnProperty.call(next, k)) {
        const v = next[k];
        if (v === "" || v == null) sp.delete(k);
        else sp.set(k, String(v));
      }
    });

    const qs = sp.toString();
    navigate({ search: qs ? `?${qs}` : "" }, { replace: false });
  };

  // 1) charger les genres (une fois)
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const g = await fetchGenres('movie');
        if (alive) setGenres(g);
      } catch (e) {
        console.error(e);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // 2) Charger selon l’URL (Back/Forward restaure la recherche)
  useEffect(() => {
    let alive = true;

    (async () => {
      const { urlDraft, urlApplied, urlPage } = readUrlState();

      // sync UI + applied
      setDraftFilters(urlDraft);
      setAppliedFilters(urlApplied);

      try {
        setError('');
        setLoading(true);

        let all = [];
        let lastRes = null;

        for (let p = 1; p <= urlPage; p++) {
          // eslint-disable-next-line no-await-in-loop
          lastRes = await fetchMoviesPage({
            page: p,
            pageSize: PAGE_SIZE,
            ...urlApplied,
          });

          const itemsP = lastRes.items || [];
          all = p === 1 ? itemsP : [...all, ...itemsP];
        }

        if (!alive) return;

        setItems(all);
        setPage(urlPage);

        const lastItems = (lastRes?.items || []);
        setHasMore(Boolean(lastRes?.next) || lastItems.length === PAGE_SIZE);
      } catch (e) {
        console.error(e);
        if (!alive) return;
        setError('Failed to load movies.');
        setItems([]);
        setHasMore(false);
        setPage(1);
      } finally {
        if (alive) setLoading(false);
      }
    })();

    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);

  const clampYearRange = (next) => {
    const ymin = next.yearMin === '' ? null : parseInt(next.yearMin, 10);
    const ymax = next.yearMax === '' ? null : parseInt(next.yearMax, 10);
    if (ymin !== null && ymax !== null && ymin > ymax) {
      return { ...next, yearMax: String(ymin) };
    }
    return next;
  };

  const handleDraftChange = (e) => {
    const { name, value } = e.target;
    setDraftFilters((prev) => clampYearRange({ ...prev, [name]: value }));
  };

  const handleMinRatingDraftChange = (e) => {
    let val = e.target.value === '' ? '' : parseInt(e.target.value, 10);
    if (Number.isNaN(val)) val = '';
    if (val !== '' && val < 1) val = 1;
    if (val !== '' && val > 10) val = 10;
    setDraftFilters((prev) => ({ ...prev, ratingMin: val === '' ? '' : String(val) }));
  };

  // Appliquer les filtres UNIQUEMENT au clic
  const handleApplyFilters = async () => {
    const cleaned = Object.fromEntries(
      Object.entries(draftFilters).filter(([_, v]) => String(v || '').trim() !== '')
    );

    setAppliedFilters(cleaned);

    // ✅ push dans l’URL => le useEffect(location.search) refait la requête
    pushUrlState({ ...cleaned, page: 1 });
  };

  const handleClearFilters = async () => {
    const empty = {
      genre: '',
      ratingMin: '',
      yearMin: '',
      yearMax: '',
      director: '',
      actor: '',
    };

    setDraftFilters(empty);
    setAppliedFilters({});

    // ✅ clear URL => le useEffect(location.search) recharge page 1 sans filtres
    pushUrlState({
      genre: '',
      ratingMin: '',
      yearMin: '',
      yearMax: '',
      director: '',
      actor: '',
      page: 1,
    });
  };

  const handleLoadMore = async () => {
    if (!hasMore || loadingMore) return;
    setLoadingMore(true);
    try {
      // ✅ page++ dans l’URL => useEffect recharge 1..page
      pushUrlState({ page: page + 1 });
    } catch (e) {
      console.error(e);
      setError('Failed to load more movies.');
    } finally {
      setLoadingMore(false);
    }
  };

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-spinner"></div>
      </div>
    );
  }

  return (
    <div>
      <Navbar />

      <div className="movie-filters">
        <select name="genre" value={draftFilters.genre} onChange={handleDraftChange}>
          <option value="">All Genres</option>
          {genres.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>

        <div className="filter-group">
          <div className="range-row">
            <div className="rating-input-wrapper">
              <label> Min.</label>
              <input
                type="number"
                name="ratingMin"
                min="1"
                max="10"
                step="1"
                value={draftFilters.ratingMin}
                onChange={handleMinRatingDraftChange}
                placeholder="1"
              />
              <span className="star">⭐</span>
            </div>
          </div>
        </div>

                <div className="filter-group">
          <div className="range-row">
            <input
              type="number"
              name="yearMin"
              value={draftFilters.yearMin}
              onChange={handleDraftChange}
              placeholder="1970"
            />

            <span className="to-text">to</span>

            <div className="year-max-control">
              <input
                type="number"
                name="yearMax"
                value={draftFilters.yearMax}
                onChange={handleDraftChange}     // garde ta logique (si tu veux taper)
                onKeyDown={handleYearMaxKeyDown} // ↑ ↓ au clavier
                placeholder="2025"
              />

              <div className="year-max-arrows">
                <button type="button" className="year-arrow-btn up" onClick={() => bumpYearMax(1)} aria-label="Increase max year">
                  ▲
                </button>
                <button type="button" className="year-arrow-btn down" onClick={() => bumpYearMax(-1)} aria-label="Decrease max year">
                  ▼
                </button>
              </div>
            </div>
          </div>
        </div>


        <input type="text" name="director" placeholder="Filter by director…" value={draftFilters.director} onChange={handleDraftChange} />
        <input type="text" name="actor" placeholder="Filter by actor…" value={draftFilters.actor} onChange={handleDraftChange} />

        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <button onClick={handleApplyFilters}>Search</button>
          <button onClick={handleClearFilters}>Clear</button>
        </div>
      </div>

      <div className="ps-store-movie-grid">
        {error && <div style={{ color: '#fff', padding: '2rem' }}>{error}</div>}

        {!error &&
          items.map((movie, idx) => (
            <MovieCard key={movie.id} movie={movie} analytics={{ surface: 'movies_grid', position: idx, row_title: 'Movies' }}/>
          ))}

        {!error && items.length === 0 && (
          <div style={{ color: '#fff', padding: '2rem' }}>No movies match your filters.</div>
        )}
      </div>

      {hasMore && (
        <div className="load-more-container" style={{ display: 'flex', justifyContent: 'center', margin: '24px 0 48px' }}>
          <button
            className="load-more-button"
            onClick={handleLoadMore}
            disabled={loadingMore}
            aria-label="Show more movies"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'transparent',
              border: 'none',
              cursor: loadingMore ? 'default' : 'pointer',
              padding: '10px 16px',
              fontSize: '1.2rem',
              color: '#fff',
              fontWeight: '600',
              opacity: loadingMore ? 0.6 : 1,
            }}
          >
            {loadingMore ? 'Loading…' : 'Show More'}
            <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 9l6 6 6-6" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
};

export default Movie;

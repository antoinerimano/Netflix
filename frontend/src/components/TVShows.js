// src/components/TVShows.js
import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import Navbar from './Navbar';
import { fetchTVShowsPage, fetchGenres } from '../api/titlesApi';
import './TVShows.css';
import { logTitleClick } from '../api/analyticsApi';


const toRating = (t) => {
  const r = parseFloat(t?.rating ?? t?.vote_average);
  return Number.isFinite(r) ? r : null;
};

const formatRating = (t) => {
  const r = toRating(t);
  return Number.isFinite(r) ? r.toFixed(1) : '—';
};

const tmdbSized = (url, size = "w342") => {
  if (!url) return url;
  return url.replace("/original/", `/${size}/`);
};

const PAGE_SIZE = 50;

export default function TVShows() {
  const [items, setItems] = useState([]);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState('');
  const [genres, setGenres] = useState([]);


  // l’utilisateur tape ici (pas de requête)
  const [draftFilters, setDraftFilters] = useState({
    genre: '',
    actor: '',
    ratingMin: '',
    query: '',
  });

  const navigate = useNavigate();
  const location = useLocation();

  // appliqué au clic Search
  const [appliedFilters, setAppliedFilters] = useState({});

  const readUrlState = () => {
    const sp = new URLSearchParams(location.search);

    const urlDraft = {
      genre: sp.get("genre") || "",
      actor: sp.get("actor") || "",
      ratingMin: sp.get("ratingMin") || "",
      query: sp.get("query") || "",
    };

    const urlApplied = Object.fromEntries(
      Object.entries(urlDraft).filter(([_, v]) => String(v || "").trim() !== "")
    );

    const urlPage = Math.max(1, parseInt(sp.get("page") || "1", 10) || 1);

    return { urlDraft, urlApplied, urlPage };
  };

  const pushUrlState = (next = {}) => {
    const sp = new URLSearchParams(location.search);

    ["genre", "actor", "ratingMin", "query", "page"].forEach((k) => {
      if (Object.prototype.hasOwnProperty.call(next, k)) {
        const v = next[k];
        if (v === "" || v == null) sp.delete(k);
        else sp.set(k, String(v));
      }
    });

    const qs = sp.toString();
    navigate({ search: qs ? `?${qs}` : "" }, { replace: false });
  };

  // Charger selon l’URL (Back/Forward restaure la recherche)
  useEffect(() => {
    let alive = true;

    (async () => {
      const { urlDraft, urlApplied, urlPage } = readUrlState();

      setDraftFilters(urlDraft);
      setAppliedFilters(urlApplied);

      try {
        setError('');
        setLoading(true);

        let all = [];
        let lastRes = null;

        for (let p = 1; p <= urlPage; p++) {
          // eslint-disable-next-line no-await-in-loop
          lastRes = await fetchTVShowsPage({
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
        setError('Failed to load TV shows.');
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

  useEffect(() => {
    (async () => {
      try {
        const g = await fetchGenres('tv');
        setGenres(g);
      } catch (e) {
        console.error(e);
      }
    })();
  }, []);


  const handleDraftChange = (e) => {
    const { name, value } = e.target;
    setDraftFilters((prev) => ({ ...prev, [name]: value }));
  };

  const handleMinRatingDraftChange = (e) => {
    let val = e.target.value === '' ? '' : parseInt(e.target.value, 10);
    if (Number.isNaN(val)) val = '';
    if (val !== '' && val < 1) val = 1;
    if (val !== '' && val > 10) val = 10;

    setDraftFilters((prev) => ({ ...prev, ratingMin: val === '' ? '' : String(val) }));
  };

  const handleApplyFilters = async () => {
    const cleaned = Object.fromEntries(
      Object.entries(draftFilters).filter(([_, v]) => String(v || '').trim() !== '')
    );

    setAppliedFilters(cleaned);

    // ✅ push dans l’URL => le useEffect(location.search) refait la requête
    pushUrlState({ ...cleaned, page: 1 });
  };

  const handleClearFilters = async () => {
    setDraftFilters({ genre: '', actor: '', ratingMin: '', query: '' });
    setAppliedFilters({});

    // ✅ clear URL => le useEffect(location.search) recharge page 1 sans filtres
    pushUrlState({ genre: '', actor: '', ratingMin: '', query: '', page: 1 });
  };

  const handleLoadMore = async () => {
    if (!hasMore || loadingMore) return;
    setLoadingMore(true);
    try {
      // ✅ page++ dans l’URL => useEffect recharge 1..page
      pushUrlState({ page: page + 1 });
    } catch (e) {
      console.error(e);
      setError('Failed to load more TV shows.');
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
    <div className="tvs">
      <Navbar />

      <div className="tvs-filters">
        <select name="genre" value={draftFilters.genre} onChange={handleDraftChange}>
          <option value="">All Genres</option>
          {genres.map(g => <option key={g} value={g}>{g}</option>)}
        </select>

        {/* Actor / Cast */}
        <input
          type="text"
          name="actor"
          placeholder="Filter by actor…"
          value={draftFilters.actor}
          onChange={handleDraftChange}
        />

        {/* Minimum Rating (1..10) */}
        <div className="tvs-filter-group">
          <div className="tvs-range-row">
            <input
              type="number"
              name="ratingMin"
              min="1"
              max="10"
              step="1"
              value={draftFilters.ratingMin}
              onChange={handleMinRatingDraftChange}
              placeholder="Min rating (1-10)"
            />
            <span className="tvs-to">⭐</span>
          </div>
        </div>

        {/* Title search */}
        <input
          type="text"
          name="query"
          placeholder="Search title…"
          value={draftFilters.query}
          onChange={handleDraftChange}
        />

        {/* Search / Clear */}
        <div
          className="load-more-container"
          style={{ display: 'flex', justifyContent: 'flex-start', margin: '12px 0 0', gap: '16px' }}
        >
          <button
            className="load-more-button"
            onClick={handleApplyFilters}
            aria-label="Search TV shows"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: '10px 16px',
              fontSize: '1.2rem',
              color: '#fff',
              fontWeight: '600',
              outline: 'none',
            }}
          >
            Search
          </button>

          <button
            className="load-more-button"
            onClick={handleClearFilters}
            aria-label="Clear TV show filters"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              background: 'transparent',
              border: 'none',
              cursor: 'pointer',
              padding: '10px 16px',
              fontSize: '1.2rem',
              color: '#fff',
              fontWeight: '600',
              outline: 'none',
            }}
          >
            Clear
          </button>
        </div>
      </div>

      <div className="tvs-grid">
        {items.map((show, idx) => (
          <Link key={show.id} to={`/tv/${show.id}`} className="tvs-card" onClick={() => {
            logTitleClick({
              title_id: show.id,
              surface: 'tv_grid',
              position: idx,
              row_title: 'TVShows',
            });
          }}>
            <img
              src={tmdbSized(show.poster, "w342")}
              alt={show.title}
              loading="lazy"
              decoding="async"
            />
            <div className="tvs-card__meta">
              <div className="tvs-card__title">{show.title}</div>
              <div className="tvs-card__sub">{formatRating(show)}/10</div>
            </div>
          </Link>
        ))}

        {error && <div className="tvs-empty">{error}</div>}
        {!error && items.length === 0 && <div className="tvs-empty">No TV shows match your filters.</div>}
      </div>

      {/* Show More */}
      {hasMore && (
        <div className="load-more-container" style={{ display: 'flex', justifyContent: 'center', margin: '24px 0 48px' }}>
          <button
            className="load-more-button"
            onClick={handleLoadMore}
            disabled={loadingMore}
            aria-label="Show more TV shows"
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
              outline: 'none',
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
}

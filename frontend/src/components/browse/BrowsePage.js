// src/components/browse/BrowsePage.js
// Movies and TV Shows pages (one design for both): title + count, search box, genre chips,
// sort, a Filters sheet (rating, decade, director / actor), active filter pills, a poster grid
// that loads more as you scroll, skeletons / empty / error states.
// State lives in the URL (shareable, Back restores it) and the scroll position is restored when
// coming back from a title.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Navbar from '../Navbar';
import Footer from '../Footer';
import MovieCard from '../MovieCard';
import { fetchTitlesPage, fetchGenres } from '../../api/titlesApi';
import { Button, Chip, EmptyState, Modal, Skeleton, friendlyError } from '../../design';
import { SearchIcon, CloseIcon } from '../../design/icons';
import '../PosterCard.css';
import './browse.css';

const PAGE_SIZE = 48; // divisible by 2, 3, 4, 6 and 8 columns
const FILTER_KEYS = ['query', 'genre', 'sort', 'ratingMin', 'yearMin', 'yearMax', 'director', 'actor'];

const SORTS = [
  { value: '', label: 'Popular' },
  { value: 'rating', label: 'Top rated' },
  { value: 'newest', label: 'Newest' },
  { value: 'title', label: 'A–Z' },
];
const RATINGS = [
  { value: '', label: 'Any' },
  { value: '6', label: '6+' },
  { value: '7', label: '7+' },
  { value: '8', label: '8+' },
];
const THIS_YEAR = new Date().getFullYear();
const DECADES = [
  { label: 'Any', min: '', max: '' },
  { label: `${THIS_YEAR - 1}–${THIS_YEAR}`, min: String(THIS_YEAR - 1), max: '' },
  { label: '2020s', min: '2020', max: '2029' },
  { label: '2010s', min: '2010', max: '2019' },
  { label: '2000s', min: '2000', max: '2009' },
  { label: '1990s', min: '1990', max: '1999' },
  { label: '1980s', min: '1980', max: '1989' },
  { label: 'Before 1980', min: '', max: '1979' },
];

const COPY = {
  movie: { title: 'Movies', noun: 'movies', one: 'movie', search: 'Search movies' },
  tv: { title: 'TV Shows', noun: 'shows', one: 'show', search: 'Search shows' },
};

const readFilters = (search) => {
  const sp = new URLSearchParams(search);
  return Object.fromEntries(FILTER_KEYS.map((k) => [k, sp.get(k) || '']));
};

function decadeLabel(min, max) {
  const d = DECADES.find((x) => x.min === (min || '') && x.max === (max || ''));
  if (d) return d.label;
  if (min && max) return `${min}–${max}`;
  if (min) return `From ${min}`;
  return `Until ${max}`;
}

export default function BrowsePage({ kind = 'movie' }) {
  const copy = COPY[kind];
  const location = useLocation();
  const navigate = useNavigate();

  const filters = useMemo(() => readFilters(location.search), [location.search]);
  const filtersKey = FILTER_KEYS.map((k) => filters[k]).join('|');
  const urlPage = Math.max(1, parseInt(new URLSearchParams(location.search).get('page') || '1', 10) || 1);

  const [items, setItems] = useState([]);
  const [count, setCount] = useState(null);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState(null);
  const [genres, setGenres] = useState([]);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [draft, setDraft] = useState(filters); // inside the Filters sheet, applied on "Show"
  const [query, setQuery] = useState(filters.query); // search box (applied after a pause)

  /** Change the URL (replace: typing / filtering doesn't stack Back steps) */
  const setUrl = useCallback(
    (changes) => {
      const sp = new URLSearchParams(location.search);
      Object.entries(changes).forEach(([k, v]) => {
        if (v === '' || v == null || (k === 'page' && Number(v) <= 1)) sp.delete(k);
        else sp.set(k, String(v));
      });
      const qs = sp.toString();
      navigate({ search: qs ? `?${qs}` : '' }, { replace: true });
    },
    [location.search, navigate]
  );
  const applyFilters = useCallback((changes) => setUrl({ ...changes, page: '' }), [setUrl]);

  // genres for the chips (cached by the server)
  useEffect(() => {
    let alive = true;
    fetchGenres(kind)
      .then((g) => alive && setGenres(g))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [kind]);

  // search box -> URL after a short pause
  useEffect(() => setQuery(filters.query), [filters.query]);
  useEffect(() => {
    if (query === filters.query) return undefined;
    const t = setTimeout(() => applyFilters({ query: query.trim() }), 350);
    return () => clearTimeout(t);
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  // filters changed (or first visit): load pages 1..page of the URL at once (Back restores them)
  const scrollKey = `browse-scroll:${location.pathname}?${filtersKey}`;
  const restoreScroll = useRef(true);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    const pages = Array.from({ length: urlPage }, (_, i) => i + 1);
    Promise.all(pages.map((p) => fetchTitlesPage({ type: kind, page: p, pageSize: PAGE_SIZE, ...filters })))
      .then((results) => {
        if (!alive) return;
        const seen = new Set();
        const all = results.flatMap((r) => r.items || []).filter((t) => !seen.has(t.id) && seen.add(t.id));
        setItems(all);
        setCount(results[0]?.count ?? all.length);
        setPage(urlPage);
        setHasMore(Boolean(results[results.length - 1]?.next));
      })
      .catch((e) => {
        if (!alive) return;
        setError(e);
        setItems([]);
        setHasMore(false);
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [filtersKey, kind]); // eslint-disable-line react-hooks/exhaustive-deps -- urlPage: only on first load

  // back from a title: same scroll position as when the user left
  useEffect(() => {
    if (loading || !restoreScroll.current) return;
    restoreScroll.current = false;
    let y = 0;
    try {
      y = Number(sessionStorage.getItem(scrollKey) || 0);
    } catch {
      y = 0;
    }
    if (y > 0) requestAnimationFrame(() => window.scrollTo(0, y));
  }, [loading, scrollKey]);
  useEffect(() => {
    let t = null;
    const onScroll = () => {
      clearTimeout(t);
      t = setTimeout(() => {
        try {
          sessionStorage.setItem(scrollKey, String(Math.round(window.scrollY)));
        } catch {
          /* private mode: no restore */
        }
      }, 150);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      clearTimeout(t);
      window.removeEventListener('scroll', onScroll);
    };
  }, [scrollKey]);

  const loadMore = useCallback(async () => {
    if (!hasMore || loadingMore || loading) return;
    setLoadingMore(true);
    try {
      const next = page + 1;
      const res = await fetchTitlesPage({ type: kind, page: next, pageSize: PAGE_SIZE, ...filters });
      setItems((prev) => {
        const seen = new Set(prev.map((t) => t.id));
        return [...prev, ...(res.items || []).filter((t) => !seen.has(t.id))];
      });
      setPage(next);
      setHasMore(Boolean(res.next));
      setUrl({ page: next }); // Back from a title restores this many pages
    } catch (e) {
      setHasMore(false);
    } finally {
      setLoadingMore(false);
    }
  }, [hasMore, loadingMore, loading, page, kind, filters, setUrl]);

  // more posters when the end of the grid comes near (the button stays for remotes / keyboards)
  const sentinelRef = useRef(null);
  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return undefined;
    const io = new IntersectionObserver((entries) => entries[0].isIntersecting && loadMore(), { rootMargin: '900px 0px' });
    io.observe(el);
    return () => io.disconnect();
  }, [loadMore]);

  const openFilters = () => {
    setDraft(filters);
    setFiltersOpen(true);
  };
  const advancedCount = ['ratingMin', 'yearMin', 'yearMax', 'director', 'actor'].filter((k) => filters[k]).length;
  const pills = [
    filters.ratingMin && { key: 'ratingMin', label: `★ ${filters.ratingMin}+`, clear: { ratingMin: '' } },
    (filters.yearMin || filters.yearMax) && {
      key: 'years',
      label: decadeLabel(filters.yearMin, filters.yearMax),
      clear: { yearMin: '', yearMax: '' },
    },
    filters.director && { key: 'director', label: `Director: ${filters.director}`, clear: { director: '' } },
    filters.actor && { key: 'actor', label: `With ${filters.actor}`, clear: { actor: '' } },
  ].filter(Boolean);
  const anyFilter = FILTER_KEYS.some((k) => k !== 'sort' && filters[k]);
  const clearAll = () => {
    setQuery('');
    applyFilters(Object.fromEntries(FILTER_KEYS.filter((k) => k !== 'sort').map((k) => [k, ''])));
  };

  let body;
  if (loading) {
    body = (
      <div className="poster-grid" aria-busy="true" aria-label="Loading">
        {Array.from({ length: 18 }, (_, i) => (
          <div key={i} className="browse__skeleton">
            <Skeleton style={{ aspectRatio: '2 / 3' }} />
            <Skeleton variant="text" width="80%" />
            <Skeleton variant="text" width="45%" />
          </div>
        ))}
      </div>
    );
  } else if (error) {
    body = (
      <EmptyState
        tone="error"
        title={`Couldn't load ${copy.noun}`}
        actions={<Button variant="primary" onClick={() => applyFilters({})}>Try again</Button>}
      >
        {friendlyError(error, `these ${copy.noun}`)}
      </EmptyState>
    );
  } else if (!items.length) {
    body = (
      <EmptyState
        icon={<SearchIcon />}
        title={`No ${copy.noun} found`}
        actions={anyFilter ? <Button variant="secondary" onClick={clearAll}>Clear filters</Button> : null}
      >
        {filters.query ? `Nothing starts with “${filters.query}”. ` : ''}Try another genre or fewer filters.
      </EmptyState>
    );
  } else {
    body = (
      <>
        <div className="poster-grid">
          {items.map((t, idx) => (
            <MovieCard
              key={t.id}
              movie={{ ...t, type: t.type || kind }}
              priority={idx < 12}
              analytics={{ surface: kind === 'tv' ? 'tv_grid' : 'movies_grid', position: idx, row_title: copy.title }}
            />
          ))}
        </div>
        <div ref={sentinelRef} className="browse__more">
          {hasMore ? (
            <Button variant="glass" loading={loadingMore} onClick={loadMore}>
              Show more {copy.noun}
            </Button>
          ) : items.length > PAGE_SIZE ? (
            <p className="browse__end">You've reached the end.</p>
          ) : null}
        </div>
      </>
    );
  }

  return (
    <div className="browse">
      <Navbar />

      <header className="browse__head">
        <div className="browse__titles">
          <h1 className="browse__title">{filters.genre || copy.title}</h1>
          {count != null && !loading ? (
            <span className="browse__count">
              {count.toLocaleString()} {count === 1 ? copy.one : copy.noun}
            </span>
          ) : null}
        </div>
        <label className="browse__search">
          <SearchIcon aria-hidden="true" />
          <input
            type="search"
            value={query}
            placeholder={copy.search}
            aria-label={copy.search}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query ? (
            <button type="button" className="browse__search-clear" aria-label="Clear search" onClick={() => setQuery('')}>
              <CloseIcon />
            </button>
          ) : null}
        </label>
      </header>

      <div className="browse__bar">
        <div className="ui-scroller browse__genres" role="group" aria-label="Genre">
          <Chip selected={!filters.genre} onClick={() => applyFilters({ genre: '' })}>
            All
          </Chip>
          {genres.map((g) => (
            <Chip key={g} selected={filters.genre === g} onClick={() => applyFilters({ genre: filters.genre === g ? '' : g })}>
              {g}
            </Chip>
          ))}
        </div>
        <div className="browse__controls">
          <label className="browse__sort">
            <span className="sr-only">Sort by</span>
            <select value={filters.sort} onChange={(e) => applyFilters({ sort: e.target.value })}>
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <Button variant="glass" size="sm" onClick={openFilters} className="browse__filters-btn">
            Filters{advancedCount ? <span className="browse__badge">{advancedCount}</span> : null}
          </Button>
        </div>
      </div>

      {pills.length ? (
        <div className="browse__pills" aria-label="Active filters">
          {pills.map((p) => (
            <button key={p.key} type="button" className="browse__pill" onClick={() => applyFilters(p.clear)} aria-label={`Remove filter ${p.label}`}>
              {p.label}
              <CloseIcon aria-hidden="true" />
            </button>
          ))}
          <button type="button" className="browse__pill browse__pill--clear" onClick={clearAll}>
            Clear all
          </button>
        </div>
      ) : null}

      <main className="browse__body">{body}</main>

      <Footer />

      <Modal
        open={filtersOpen}
        onClose={() => setFiltersOpen(false)}
        title="Filters"
        size="md"
        scrollable={false}
        initialFocus=".browse-filters .ui-chip.is-selected"
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => setDraft((d) => ({ ...d, ratingMin: '', yearMin: '', yearMax: '', director: '', actor: '' }))}
            >
              Reset
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setFiltersOpen(false);
                applyFilters({
                  ratingMin: draft.ratingMin,
                  yearMin: draft.yearMin,
                  yearMax: draft.yearMax,
                  director: draft.director.trim(),
                  actor: draft.actor.trim(),
                });
              }}
            >
              Show results
            </Button>
          </>
        }
      >
        <div className="browse-filters">
          <fieldset>
            <legend>Rating</legend>
            <div className="browse-filters__chips">
              {RATINGS.map((r) => (
                <Chip key={r.label} selected={draft.ratingMin === r.value} onClick={() => setDraft((d) => ({ ...d, ratingMin: r.value }))}>
                  {r.value ? `★ ${r.label}` : r.label}
                </Chip>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend>{kind === 'tv' ? 'First aired' : 'Released'}</legend>
            <div className="browse-filters__chips">
              {DECADES.map((d) => (
                <Chip
                  key={d.label}
                  selected={draft.yearMin === d.min && draft.yearMax === d.max}
                  onClick={() => setDraft((x) => ({ ...x, yearMin: d.min, yearMax: d.max }))}
                >
                  {d.label}
                </Chip>
              ))}
            </div>
          </fieldset>

          <div className="browse-filters__fields">
            {kind === 'movie' ? (
              <label className="browse-filters__field">
                <span>Director</span>
                <input
                  type="text"
                  value={draft.director}
                  placeholder="e.g. Christopher Nolan"
                  onChange={(e) => setDraft((d) => ({ ...d, director: e.target.value }))}
                />
              </label>
            ) : null}
            <label className="browse-filters__field">
              <span>Actor</span>
              <input
                type="text"
                value={draft.actor}
                placeholder="e.g. Zendaya"
                onChange={(e) => setDraft((d) => ({ ...d, actor: e.target.value }))}
              />
            </label>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// src/pages/SearchPage.js
// Search (/search?q=...&type=movie|tv): a big search field, All / Movies / TV Shows, results as a
// poster grid with why each one matched ("With Bryan Cranston", "Like CSI"...). Before typing:
// recent searches (this profile, this device) and popular titles. Phones open this page from the
// navbar's search icon; desktop gets here from "See all results" / Enter in the navbar field.
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import Navbar from '../components/Navbar';
import Footer from '../components/Footer';
import MovieCard from '../components/MovieCard';
import { searchTitles, fetchTitlesPage } from '../api/titlesApi';
import { Chip, EmptyState, SectionTitle, Skeleton, friendlyError, Button } from '../design';
import { SearchIcon, CloseIcon } from '../design/icons';
import '../components/PosterCard.css';
import '../components/browse/browse.css';
import './SearchPage.css';

const TYPES = [
  { value: 'all', label: 'All' },
  { value: 'movie', label: 'Movies' },
  { value: 'tv', label: 'TV Shows' },
];
const MAX_RECENT = 8;
const recentKey = () => `recentSearches:${localStorage.getItem('activeProfileId') || ''}`;
const readRecent = () => {
  try {
    const list = JSON.parse(localStorage.getItem(recentKey()) || '[]');
    return Array.isArray(list) ? list.filter((x) => typeof x === 'string') : [];
  } catch {
    return [];
  }
};
const writeRecent = (list) => {
  try {
    localStorage.setItem(recentKey(), JSON.stringify(list.slice(0, MAX_RECENT)));
  } catch {
    /* private mode: no history */
  }
};

function PosterSkeletons({ count = 12 }) {
  return (
    <div className="poster-grid" aria-busy="true" aria-label="Loading">
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="browse__skeleton">
          <Skeleton style={{ aspectRatio: '2 / 3' }} />
          <Skeleton variant="text" width="80%" />
        </div>
      ))}
    </div>
  );
}

export default function SearchPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const urlQuery = params.get('q') || '';
  const type = TYPES.some((t) => t.value === params.get('type')) ? params.get('type') : 'all';

  const [query, setQuery] = useState(urlQuery);
  const [results, setResults] = useState(null); // null: nothing searched yet
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [recent, setRecent] = useState(readRecent);
  const [popular, setPopular] = useState(null);
  const inputRef = useRef(null);

  const setUrl = useCallback(
    (changes) => {
      const sp = new URLSearchParams(location.search);
      Object.entries(changes).forEach(([k, v]) => (v && v !== 'all' ? sp.set(k, v) : sp.delete(k)));
      const qs = sp.toString();
      navigate({ search: qs ? `?${qs}` : '' }, { replace: true });
    },
    [location.search, navigate]
  );

  // typing -> URL after a short pause (the URL drives the search: shareable, Back restores it)
  useEffect(() => setQuery(urlQuery), [urlQuery]);
  useEffect(() => {
    if (query.trim() === urlQuery) return undefined;
    const t = setTimeout(() => setUrl({ q: query.trim() }), 300);
    return () => clearTimeout(t);
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const q = urlQuery.trim();
    if (!q) {
      setResults(null);
      setError(null);
      return undefined;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    searchTitles({ q, type, limit: 60 })
      .then((list) => alive && setResults(list))
      .catch((e) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [urlQuery, type]);

  // before typing: popular titles (cached by the server)
  useEffect(() => {
    if (popular) return undefined;
    let alive = true;
    fetchTitlesPage({ page: 1, pageSize: 18 })
      .then((r) => alive && setPopular(r.items || []))
      .catch(() => alive && setPopular([]));
    return () => {
      alive = false;
    };
  }, [popular]);

  const remember = useCallback((q) => {
    const term = (q || '').trim();
    if (term.length < 2) return;
    const next = [term, ...readRecent().filter((x) => x.toLowerCase() !== term.toLowerCase())];
    writeRecent(next);
    setRecent(next.slice(0, MAX_RECENT));
  }, []);
  const forget = (term) => {
    const next = readRecent().filter((x) => x !== term);
    writeRecent(next);
    setRecent(next);
  };
  const clearRecent = () => {
    writeRecent([]);
    setRecent([]);
  };

  const submit = (e) => {
    e.preventDefault();
    setUrl({ q: query.trim() });
    remember(query);
    inputRef.current?.blur(); // phones: hide the keyboard to see the results
  };

  const hasQuery = !!urlQuery.trim();
  let body;
  if (!hasQuery) {
    body = (
      <>
        {recent.length ? (
          <section className="search__section">
            <div className="search__section-head">
              <SectionTitle as="h2">Recent searches</SectionTitle>
              <button type="button" className="search__clear-all" onClick={clearRecent}>
                Clear
              </button>
            </div>
            <ul className="search__recent">
              {recent.map((term) => (
                <li key={term}>
                  <Chip onClick={() => setUrl({ q: term })}>{term}</Chip>
                  <button type="button" className="search__forget" aria-label={`Remove ${term}`} onClick={() => forget(term)}>
                    <CloseIcon />
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <section className="search__section">
          <SectionTitle as="h2">Popular right now</SectionTitle>
          {popular === null ? (
            <PosterSkeletons />
          ) : (
            <div className="poster-grid search__grid">
              {popular.map((t, idx) => (
                <MovieCard key={t.id} movie={t} analytics={{ surface: 'search_popular', position: idx, row_title: 'Popular' }} />
              ))}
            </div>
          )}
        </section>
      </>
    );
  } else if (loading && !results) {
    body = <PosterSkeletons />;
  } else if (error) {
    body = (
      <EmptyState tone="error" title="Search isn't working right now" actions={<Button variant="primary" onClick={() => setUrl({ q: urlQuery })}>Try again</Button>}>
        {friendlyError(error, 'results')}
      </EmptyState>
    );
  } else if (results && !results.length) {
    body = (
      <EmptyState icon={<SearchIcon />} title={`No results for “${urlQuery}”`}>
        Try a title, an actor, a director, a genre or a year - or describe it: “90s crime shows like CSI”.
      </EmptyState>
    );
  } else if (results) {
    body = (
      <section className="search__section" aria-live="polite">
        <p className="search__count">
          {results.length >= 60 ? 'Top 60 results' : `${results.length} result${results.length === 1 ? '' : 's'}`} for “{urlQuery}”
        </p>
        <div className={`poster-grid search__grid${loading ? ' is-stale' : ''}`}>
          {results.map((t, idx) => (
            <MovieCard
              key={`${t.type}-${t.id}`}
              movie={t}
              note={t.match || ''}
              priority={idx < 12}
              onClick={() => {
                remember(urlQuery);
                navigate(`/${String(t.type).toLowerCase() === 'tv' ? 'tv' : 'movies'}/${t.id}`);
              }}
              analytics={{ surface: 'search_page', position: idx, row_title: `search:${urlQuery}` }}
            />
          ))}
        </div>
      </section>
    );
  }

  return (
    <div className="browse search">
      <Navbar />
      <main className="search__main">
        <form className="search__form" role="search" onSubmit={submit}>
          <label className="search__field">
            <SearchIcon aria-hidden="true" />
            <input
              ref={inputRef}
              type="search"
              value={query}
              placeholder="Titles, people, genres…"
              aria-label="Search movies and TV shows"
              autoComplete="off"
              enterKeyHint="search"
              // phones / desktop: ready to type; TV remotes open their keyboard with OK instead
              autoFocus={!document.documentElement.classList.contains('tv-device')}
              onChange={(e) => setQuery(e.target.value)}
            />
            {query ? (
              <button
                type="button"
                className="search__clear"
                aria-label="Clear search"
                onClick={() => {
                  setQuery('');
                  setUrl({ q: '' });
                  inputRef.current?.focus();
                }}
              >
                <CloseIcon />
              </button>
            ) : null}
          </label>
          <div className="ui-scroller search__types" role="group" aria-label="Type">
            {TYPES.map((t) => (
              <Chip key={t.value} selected={type === t.value} onClick={() => setUrl({ type: t.value })}>
                {t.label}
              </Chip>
            ))}
          </div>
        </form>
        {body}
      </main>
      <Footer />
    </div>
  );
}

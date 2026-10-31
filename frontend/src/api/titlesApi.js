// src/api/titlesApi.js
import http from './http';

// ---------- base axios ----------
// shared client: adds the JWT header and refreshes it when it expires
const API = http;

// Normalize DRF list vs non-paginated responses
const unwrapList = (data) => {
  if (!data) return [];
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.results)) return data.results;
  // sometimes DRF is configured with a different key
  if (data && Array.isArray(data.items)) return data.items;
  return [];
};

// ---------- core helpers over /titles ----------
const listTitles = async (params = {}) => {
  const res = await API.get('/titles/', { params });
  return unwrapList(res.data);
};
const getTitle  = async (id) => (await API.get(`/titles/${id}/`)).data;
const create    = async (payload) => (await API.post('/titles/', payload)).data;
const update    = async (id, payload) => (await API.put(`/titles/${id}/`, payload)).data;
const remove    = async (id) => (await API.delete(`/titles/${id}/`)).data;

// ---------- filters (client-side) ----------
const _filterByGenre = (items, genre) =>
  items.filter((t) => (t.genre || '').toLowerCase().includes(String(genre).toLowerCase()));

const _filterByRating = (items, minRating) =>
  items.filter((t) => {
    const val = typeof t.vote_average === 'number' ? t.vote_average : parseFloat(t.rating || '0');
    return val >= Number(minRating);
  });

const _filterMoviesByReleaseYear = (items, year) =>
  items.filter((t) => String(t.release_year || (t.release_date || '').slice(0, 4)) === String(year));

const _filterTVByFirstAirYear = (items, year) =>
  items.filter((t) => String((t.first_air_date || '').slice(0, 4)) === String(year));

const _filterByDirector = (items, director) =>
  items.filter((t) => (t.director || '').toLowerCase().includes(String(director).toLowerCase()));

const _filterByActor = (items, actor) =>
  items.filter(
    (t) => Array.isArray(t.cast) &&
      t.cast.some((n) => (n || '').toLowerCase().includes(String(actor).toLowerCase()))
  );

// =====================================================================
// A) MOVIES
// =====================================================================
const API_TYPE_MOVIE = 'movie';
const MOVIE_PARAMS = { type: API_TYPE_MOVIE };

export const fetchMovies = async () => listTitles(MOVIE_PARAMS);
export const fetchMovieById = async (id) => getTitle(id);
export const createMovie = async (movieData) => create({ type: API_TYPE_MOVIE, ...movieData });
export const updateMovie = async (id, movieData) => update(id, { type: API_TYPE_MOVIE, ...movieData });
export const deleteMovie = async (id) => remove(id);

export const fetchMoviesByGenre = async (genre) => _filterByGenre(await fetchMovies(), genre);
export const fetchMoviesByRating = async (rating) => _filterByRating(await fetchMovies(), rating);
export const fetchMoviesByReleaseYear = async (year) => _filterMoviesByReleaseYear(await fetchMovies(), year);
export const fetchMoviesByDirector = async (director) => _filterByDirector(await fetchMovies(), director);
export const fetchMoviesByActor = async (actor) => _filterByActor(await fetchMovies(), actor);

// =====================================================================
// B) TV
// =====================================================================
const API_TYPE_TV = 'tv';
const TV_PARAMS = { type: API_TYPE_TV };

export const fetchTVShows = async () => listTitles(TV_PARAMS);
export const fetchTitleById = async (id) => getTitle(id);
export const fetchTVShowById = async (id) => getTitle(id); // alias

export const createTVShow = async (data) => create({ type: API_TYPE_TV, ...data });
export const updateTVShow = async (id, data) => update(id, { type: API_TYPE_TV, ...data });
export const deleteTVShow = async (id) => remove(id);

export const fetchTVShowsByGenre = async (genre) => _filterByGenre(await fetchTVShows(), genre);
export const fetchTVShowsByRating = async (rating) => _filterByRating(await fetchTVShows(), rating);
export const fetchTVShowsByFirstAirYear = async (year) => _filterTVByFirstAirYear(await fetchTVShows(), year);
export const fetchTVShowsByDirector = async (director) => _filterByDirector(await fetchTVShows(), director);
export const fetchTVShowsByActor = async (actor) => _filterByActor(await fetchTVShows(), actor);

// ---------- stream providers ----------
// [{ key, label, domain, movie_path, episode_path, status }], providers that are down come last.
// Links are domain + path, with {tmdb_id} {imdb_id} {season} {episode} filled in (see buildProviderLinks).
let providersPromise = null;

export function fetchProviders() {
  if (!providersPromise) {
    providersPromise = API.get('/providers/')
      .then((res) => (Array.isArray(res.data) ? res.data : []))
      .catch((err) => {
        providersPromise = null; // retry on next call
        throw err;
      });
  }
  return providersPromise;
}

/**
 * Build the playable links for a movie ({ tmdb_id, imdb_id }) or an episode
 * ({ tmdb_id, season, episode }). Providers missing a needed value are skipped.
 * Optional values.start (seconds): resume point, for providers with a start_param.
 */
export function buildProviderLinks(providers, values, kind = 'movie') {
  return (providers || [])
    .map((p) => {
      const path = kind === 'episode' ? p.episode_path : p.movie_path;
      if (!path) return null;
      let missing = false;
      const filled = path.replace(/\{(\w+)\}/g, (_, name) => {
        const v = values[name];
        if (v === undefined || v === null || v === '') missing = true;
        return encodeURIComponent(String(v ?? ''));
      });
      if (missing) return null;
      let url = p.domain + filled;
      // resume: start at values.start seconds, for providers that support it (start_param)
      if (values.start > 0 && p.start_param) {
        url += `${url.includes('?') ? '&' : '?'}${encodeURIComponent(p.start_param)}=${Math.floor(values.start)}`;
      }
      return { key: p.key, label: p.label, url, down: p.status === 'down', sendsEvents: !!p.sends_events };
    })
    .filter(Boolean);
}

// ---------- seasons / episodes ----------
// NOTE: these unwrap lists to handle DRF pagination automatically

export async function fetchSeasons(titleId) {
  const res = await API.get(`/titles/${titleId}/seasons/`);
  return unwrapList(res.data);
}

/**
 * Returns the Season object by TMDb-like season_number from the action response.
 */
export async function fetchSeasonByNumber(titleId, seasonNumber) {
  const seasons = await fetchSeasons(titleId);
  return seasons.find((s) => Number(s.season_number) === Number(seasonNumber)) || null;
}

/**
 * Returns EPISODES for a season_number.
 * Works even though the backend action ignores ?number= — we filter client-side.
 */
export async function fetchEpisodesBySeasonNumber(titleId, seasonNumber) {
  const season = await fetchSeasonByNumber(titleId, seasonNumber);
  if (!season) return [];
  // The action embeds episodes in each season object
  return Array.isArray(season.episodes) ? season.episodes : [];
}

/**
 * (Optional) If you ever need episodes by Season DB id (from SeasonViewSet nested route),
 * keep this variant. It works when you call the nested router URL.
 */
export async function fetchEpisodesBySeasonId(titleId, seasonId) {
  if (!seasonId) return [];
  const res = await API.get(`/titles/${titleId}/seasons/${seasonId}/episodes/`);
  return unwrapList(res.data);
}

/**
 * Existing title fetcher (keep whatever you already had)
 */

// =====================================================================
// C) factory
// =====================================================================
export const makeTitlesApi = (mode = 'movie') => {
  const params = { type: mode === 'tv' ? API_TYPE_TV : API_TYPE_MOVIE };
  const createType = mode === 'tv' ? API_TYPE_TV : API_TYPE_MOVIE;

  return {
    fetchAll: async () => listTitles(params),
    fetchById: async (id) => getTitle(id),
    create: async (data) => create({ type: createType, ...data }),
    update: async (id, data) => update(id, { type: createType, ...data }),
    remove: async (id) => remove(id),

    filterByGenre: async (genre) => _filterByGenre(await listTitles(params), genre),
    filterByRating: async (minRating) => _filterByRating(await listTitles(params), minRating),
    filterByYear: async (year) =>
      mode === 'tv'
        ? _filterTVByFirstAirYear(await listTitles(params), year)
        : _filterMoviesByReleaseYear(await listTitles(params), year),
    filterByDirector: async (name) => _filterByDirector(await listTitles(params), name),
    filterByActor: async (name) => _filterByActor(await listTitles(params), name),
  };
};

const unwrapPaginated = (data) => {
  if (!data) return { items: [], count: 0, next: null, previous: null };
  if (Array.isArray(data)) return { items: data, count: data.length, next: null, previous: null };

  // DRF default pagination keys
  if (Array.isArray(data.results)) {
    return {
      items: data.results,
      count: Number(data.count || 0),
      next: data.next || null,
      previous: data.previous || null,
    };
  }

  // fallback
  if (Array.isArray(data.items)) {
    return {
      items: data.items,
      count: Number(data.count || data.total || 0),
      next: data.next || null,
      previous: data.previous || null,
    };
  }

  return { items: [], count: 0, next: null, previous: null };
};

const listTitlesPage = async (params = {}) => {
  const res = await API.get('/titles/', { params });
  return unwrapPaginated(res.data);
};

// MOVIES (paginé + filtres)
export const fetchMoviesPage = async ({
  page = 1,
  pageSize = 50,
  genre = '',
  ratingMin = '',
  yearMin = '',
  yearMax = '',
  director = '',
  actor = '',
} = {}) => {
  // DRF page number pagination: ?page=1&page_size=50
  // (si ton DRF utilise "page_size", c’est ça. Sinon adapte.)
  return listTitlesPage({
    type: API_TYPE_MOVIE,
    page,
    page_size: pageSize,

    // IMPORTANT: ces filtres doivent être gérés par le backend,
    // sinon ils ne feront rien (ou alors tu filtres après, mais ça casse l’objectif)
    genre,
    ratingMin,
    yearMin,
    yearMax,
    director,
    actor,
  });
};


export const fetchTVShowsPage = async ({
  page = 1,
  pageSize = 50,
  genre = '',
  actor = '',
  ratingMin = '',
  query = '',
} = {}) => {
  return listTitlesPage({
    type: 'tv',
    page,
    page_size: pageSize,
    genre,
    actor,
    ratingMin,
    query,
  });
};

export const fetchGenres = async (type = 'movie') => {
  const res = await API.get('/titles/genres/', { params: { type } });
  return Array.isArray(res.data) ? res.data : [];
};


export const searchTitles = async ({ q, type = 'all', limit = 15 } = {}) => {
  const res = await API.get('/titles/search/', {
    params: { q, type, limit },
  });
  return Array.isArray(res.data) ? res.data : [];
};



export const fetchTitlesByActorTmdbId = async (tmdbId) => {
  const res = await API.get("/actors/titles/", {
    params: { tmdb_id: tmdbId },
  });
  return unwrapList(res.data);
};


/**
 * One page of movies or shows (Movies / TV Shows pages). Every filter works for both types.
 * sort: popular (default) | rating | newest | title. Returns { items, count, next, previous }.
 */
export const fetchTitlesPage = async ({
  type,
  page = 1,
  pageSize = 48,
  sort = '',
  query = '',
  genre = '',
  ratingMin = '',
  yearMin = '',
  yearMax = '',
  director = '',
  actor = '',
} = {}) => {
  const params = { type, page, page_size: pageSize, sort, query, genre, ratingMin, yearMin, yearMax, director, actor };
  Object.keys(params).forEach((k) => (params[k] === '' || params[k] == null) && delete params[k]);
  return listTitlesPage(params);
};

/** "More like this": titles nearest to this one (embeddings), best first */
export const fetchSimilarTitles = async (titleId, limit = 18) => {
  const res = await API.get(`/titles/${encodeURIComponent(titleId)}/similar/`, { params: { limit } });
  return Array.isArray(res.data) ? res.data : [];
};

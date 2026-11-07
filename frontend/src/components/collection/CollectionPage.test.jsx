// A franchise page: numbered parts, watched checks, "Coming soon", the main button (start / next /
// none when everything is seen), and a collection that doesn't exist.
import React, { Suspense } from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import CollectionPage from './CollectionPage';
import { fetchCollection } from '../../api/recoApi';

vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../Footer', () => ({ default: () => null }));
vi.mock('../../api/recoApi', () => ({ fetchCollection: vi.fn() }));

const movie = (id, title, year) => ({ id, type: 'movie', title, poster: '', release_year: year });
const parts = (watched) => [
  { title: movie(1, 'The Godfather', 1972), position: 1, watched: watched > 0, upcoming: false },
  { title: movie(2, 'The Godfather Part II', 1974), position: 2, watched: watched > 1, upcoming: false },
  { title: movie(3, 'The Godfather Part IV', null), position: 3, watched: false, upcoming: true },
];
const base = { id: 230, name: 'The Godfather Collection', poster: '', backdrop: '', total: 3 };

function renderPage() {
  localStorage.setItem('activeProfileId', '3');
  return render(
    <Suspense fallback="loading">
      <MemoryRouter initialEntries={['/collection/230']}>
        <Routes>
          <Route path="/collection/:id" element={<CollectionPage />} />
        </Routes>
      </MemoryRouter>
    </Suspense>
  );
}

afterEach(() => vi.resetAllMocks());

test('half watched: what comes next, checks, coming soon', async () => {
  fetchCollection.mockResolvedValue({ ...base, parts: parts(1), watched: 1, next: movie(2, 'The Godfather Part II', 1974) });
  renderPage();
  expect(await screen.findByRole('heading', { name: 'The Godfather Collection' })).toBeInTheDocument();
  expect(fetchCollection).toHaveBeenCalledWith('3', '230');
  expect(screen.getByText('Collection · 3 movies')).toBeInTheDocument();
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '1');
  expect(screen.getByRole('button', { name: 'Watch next: The Godfather Part II' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Part 1, The Godfather, 1972, Watched' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Part 3, The Godfather Part IV, Coming soon' })).toBeInTheDocument();
});

test('nothing watched: start with the first one; all seen: no button', async () => {
  fetchCollection.mockResolvedValueOnce({ ...base, parts: parts(0), watched: 0, next: movie(1, 'The Godfather', 1972) });
  const { unmount } = renderPage();
  expect(await screen.findByRole('button', { name: 'Start with The Godfather' })).toBeInTheDocument();
  unmount();

  fetchCollection.mockResolvedValueOnce({ ...base, parts: parts(2), watched: 2, next: null });
  renderPage();
  expect(await screen.findByText('All watched')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /^Watch next|^Start with/ })).toBeNull();
});

test('a collection that does not exist', async () => {
  fetchCollection.mockRejectedValue({ response: { status: 404 } });
  renderPage();
  expect(await screen.findByText('Collection not found')).toBeInTheDocument();
});

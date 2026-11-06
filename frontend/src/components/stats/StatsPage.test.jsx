// "Your year": the headline, the counts, genre bars scaled to the top one, years to switch, and
// the empty state when nothing was watched.
import React, { Suspense } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import StatsPage from './StatsPage';
import { fetchStats } from '../../api/recoApi';

vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../Footer', () => ({ default: () => null }));
vi.mock('../../api/recoApi', () => ({ fetchStats: vi.fn() }));

const title = (id, name, type = 'movie') => ({ id, type, title: name, poster: '', landscape_image: '' });
const YEAR = {
  year: 2025, years: [2026, 2025], minutes: 605, titles: 3, movies: 2, shows: 1, episodes: 4, days: 5,
  longest_streak: { days: 3, from: '2025-03-01', to: '2025-03-03' }, current_streak: 0,
  months: [0, 0, 310, 0, 0, 0, 95, 0, 0, 0, 0, 200],
  top_genres: [{ genre: 'Crime', minutes: 300, share: 0.5 }, { genre: 'Drama', minutes: 150, share: 0.25 }],
  top_titles: [{ title: title(1, 'Heat'), minutes: 170, episodes: 0 }, { title: title(2, 'Night Shift', 'tv'), minutes: 140, episodes: 3 }],
  top_actors: [{ name: 'Al Pacino', tmdb_id: 1158, photo: '', titles: 2, minutes: 270 }],
  first: { title: title(1, 'Heat'), date: '2025-03-01' },
};

function renderPage() {
  localStorage.setItem('activeProfileId', '3');
  localStorage.setItem('activeProfile', JSON.stringify({ id: 3, name: 'Sam' }));
  return render(
    <Suspense fallback="loading">
      <MemoryRouter>
        <StatsPage />
      </MemoryRouter>
    </Suspense>
  );
}

afterEach(() => vi.resetAllMocks());

test('the year in numbers, genres scaled to the top one, switching year', async () => {
  fetchStats.mockResolvedValue(YEAR);
  const { container } = renderPage();

  expect(await screen.findByText('About 10 hours')).toBeInTheDocument();
  expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Your 2025');
  expect(screen.getByText('3 days')).toBeInTheDocument(); // longest streak
  expect(screen.getByRole('button', { name: /Night Shift/ })).toHaveTextContent('3 episodes · 2 h');
  expect(screen.getByRole('button', { name: /Al Pacino/ })).toHaveTextContent('2 titles');

  const bars = container.querySelectorAll('.stats-bars__bar');
  expect(bars[0].style.width).toBe('100%'); // the top genre fills the track
  expect(bars[1].style.width).toBe('50%');
  expect(screen.getByText('50%')).toBeInTheDocument(); // its share, as text

  expect(container.querySelector('.stats-months__value')).toHaveTextContent('5 h'); // the busiest month only
  expect(container.querySelectorAll('.stats-months__value')).toHaveLength(1);

  fireEvent.click(screen.getByRole('button', { name: '2026' }));
  expect(fetchStats).toHaveBeenLastCalledWith('3', 2026);
});

test('nothing watched yet', async () => {
  fetchStats.mockResolvedValue({ ...YEAR, years: [], minutes: 0, titles: 0, top_genres: [], top_titles: [], top_actors: [], first: null });
  renderPage();
  expect(await screen.findByText('Nothing to count yet')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Share my year' })).toBeNull();
});

// "Watch history": entries grouped Today / Yesterday / a date, an episode shows its season, number
// and name, Download asks for the CSV, a paused and empty history says so.
import React, { Suspense } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import HistoryPage from './HistoryPage';
import { downloadHistory, fetchHistory } from '../../api/historyApi';

vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../Footer', () => ({ default: () => null }));
vi.mock('../../api/historyApi', () => ({
  fetchHistory: vi.fn(),
  removeHistoryItem: vi.fn(),
  clearHistory: vi.fn(),
  setHistoryPaused: vi.fn(),
  downloadHistory: vi.fn(),
}));

const daysAgo = (n) => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  d.setHours(20, 30, 0, 0);
  return d.toISOString();
};
const show = { id: 7, type: 'tv', title: 'Night Shift', poster: '', landscape_image: '' };
const movie = { id: 8, type: 'movie', title: 'Heat', poster: '', landscape_image: '' };

function renderPage() {
  localStorage.setItem('activeProfileId', '3');
  localStorage.setItem('activeProfile', JSON.stringify({ id: 3, name: 'Sam' }));
  return render(
    <Suspense fallback="loading">
      <MemoryRouter>
        <HistoryPage />
      </MemoryRouter>
    </Suspense>
  );
}

afterEach(() => vi.resetAllMocks());

test('entries by day, episodes with their name, download', async () => {
  fetchHistory.mockResolvedValue({
    paused: false,
    next: null,
    items: [
      { id: 1, watched_at: daysAgo(0), season: 1, episode: 2, episode_info: { id: 9, episode_number: 2, name: 'Shift 2' }, title: show },
      { id: 2, watched_at: daysAgo(1), season: null, episode: null, episode_info: null, title: movie },
      { id: 3, watched_at: daysAgo(5), season: null, episode: null, episode_info: null, title: movie },
    ],
  });
  renderPage();

  const today = await screen.findByRole('region', { name: 'Today' });
  expect(within(today).getByRole('button', { name: /^Night Shift/ })).toHaveTextContent('S1 · E2 · Shift 2');
  expect(screen.getByRole('region', { name: 'Yesterday' })).toHaveTextContent('Film');
  expect(document.querySelectorAll('.history-day')).toHaveLength(3); // today, yesterday, 5 days ago
  expect(screen.getAllByRole('button', { name: 'Remove Heat from history' })).toHaveLength(2);

  fireEvent.click(screen.getByRole('button', { name: 'Download (.csv)' }));
  expect(downloadHistory).toHaveBeenCalledWith('3');
});

test('paused and empty: says nothing is saved', async () => {
  fetchHistory.mockResolvedValue({ paused: true, next: null, items: [] });
  renderPage();
  expect(await screen.findByText('History is paused')).toBeInTheDocument();
  expect(screen.getByRole('switch', { name: /Pause watch history/ })).toHaveAttribute('aria-checked', 'true');
  expect(screen.getByRole('button', { name: 'Clear history' })).toBeDisabled();
});

// "What to watch?": the choices go with the request, "Show me" again leaves out what was shown,
// /pick?surprise=1 asks for one title with no time limit (regression: it went with the default
// "under 90 min", set in the same click), "Nothing fits".
import React, { Suspense } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import PickPage from './PickPage';
import { fetchPicks } from '../../api/recoApi';
import { logImpressions, logTitleClick } from '../../api/analyticsApi';

vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../Footer', () => ({ default: () => null }));
vi.mock('../../api/recoApi', () => ({ fetchPicks: vi.fn() }));
vi.mock('../../api/analyticsApi', () => ({ logImpressions: vi.fn(), logTitleClick: vi.fn() }));

const item = (id, title, type = 'movie', minutes = 88) => ({ id, type, title, poster: '', release_year: 2001, description: 'x', minutes });

function renderPage(path = '/pick') {
  localStorage.setItem('activeProfileId', '3');
  return render(
    <Suspense fallback="loading">
      <MemoryRouter initialEntries={[path]}>
        <PickPage />
      </MemoryRouter>
    </Suspense>
  );
}

beforeEach(() => {
  logImpressions.mockResolvedValue({});
  logTitleClick.mockResolvedValue({});
});
afterEach(() => vi.resetAllMocks());

test('the choices go with the request; again leaves out what was shown', async () => {
  fetchPicks.mockResolvedValueOnce({ items: [item(1, 'Amélie'), item(2, 'Sitcom', 'tv', 22)], candidates: 9 });
  fetchPicks.mockResolvedValueOnce({ items: [item(3, 'Heat')], candidates: 9 });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'About 2 hours' }));
  fireEvent.click(screen.getByRole('button', { name: 'Funny' }));
  fireEvent.click(screen.getByRole('button', { name: 'Show me' }));
  expect(await screen.findByRole('button', { name: /Amélie/ })).toHaveTextContent('1 hr 28 min');
  expect(screen.getByRole('button', { name: /Sitcom/ })).toHaveTextContent('22 min an episode');
  expect(fetchPicks).toHaveBeenLastCalledWith('3', { time: '120', mood: 'funny', count: 6, exclude: [] });

  fireEvent.click(screen.getByRole('button', { name: 'Show me others' }));
  expect(await screen.findByRole('button', { name: /Heat/ })).toBeInTheDocument();
  expect(fetchPicks).toHaveBeenLastCalledWith('3', { time: '120', mood: 'funny', count: 6, exclude: [1, 2] });
});

test('surprise: one title, no time limit, then another one', async () => {
  fetchPicks.mockResolvedValueOnce({ items: [item(7, 'The Godfather', 'movie', 175)], candidates: 50 });
  fetchPicks.mockResolvedValueOnce({ items: [item(8, 'Inception', 'movie', 148)], candidates: 50 });
  renderPage('/pick?surprise=1');
  expect(await screen.findByRole('heading', { name: 'The Godfather' })).toBeInTheDocument();
  expect(fetchPicks).toHaveBeenCalledWith('3', { time: 'any', mood: 'any', count: 1, exclude: [] });
  expect(screen.getByRole('button', { name: 'No limit' })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Another one' }));
  expect(await screen.findByRole('heading', { name: 'Inception' })).toBeInTheDocument();
  expect(fetchPicks).toHaveBeenLastCalledWith('3', { time: 'any', mood: 'any', count: 1, exclude: [7] });
});

test('nothing fits', async () => {
  fetchPicks.mockResolvedValue({ items: [], candidates: 0 });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Show me' }));
  expect(await screen.findByText('Nothing fits')).toBeInTheDocument();
  expect(screen.getByText('Try another mood or more time.')).toBeInTheDocument();
});

// roadmap 8.7 (backend reco/ai_report.py): what is shown is logged with the A/B group the server
// put this profile in, and a click on a suggestion is logged from the "pick" surface
test('logs what it shows, with the group, and what gets clicked', async () => {
  fetchPicks.mockResolvedValueOnce({ items: [item(1, 'Amélie'), item(2, 'Heat')], candidates: 9, arm: 'control' });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Show me' }));
  fireEvent.click(await screen.findByRole('button', { name: /Heat/ }));
  expect(logImpressions).toHaveBeenCalledWith({
    items: [{ title_id: 1, position: 0 }, { title_id: 2, position: 1 }],
    row_type: 'pick:control',
  });
  expect(logTitleClick).toHaveBeenCalledWith({ title_id: 2, surface: 'pick', position: 1 });
});

test('the surprise: Watch counts as a click too', async () => {
  fetchPicks.mockResolvedValueOnce({ items: [item(7, 'Amélie')], candidates: 9, arm: 'ai' });
  renderPage('/pick?surprise=1');
  fireEvent.click(await screen.findByRole('button', { name: 'Watch' }));
  expect(logImpressions).toHaveBeenCalledWith({ items: [{ title_id: 7, position: 0 }], row_type: 'pick:ai' });
  expect(logTitleClick).toHaveBeenCalledWith({ title_id: 7, surface: 'pick', position: 0 });
});

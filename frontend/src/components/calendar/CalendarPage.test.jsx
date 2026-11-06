// "Upcoming": days titled Today / Tomorrow / a date, an episode out today opens the player on it,
// one still to come opens the show, the week's episodes have their own row.
import React, { Suspense } from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import CalendarPage from './CalendarPage';
import { fetchCalendar } from '../../api/recoApi';

vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../Footer', () => ({ default: () => null }));
vi.mock('../../api/recoApi', () => ({ fetchCalendar: vi.fn(), setFollow: vi.fn() }));

const show = { id: 7, type: 'tv', title: 'Night Shift', poster: '', landscape_image: '' };
const ep = (id, season, number, date, name) => ({ id, season, episode_number: number, air_date: date, name, still: '', show, reason: 'follow' });

function Where() {
  const loc = useLocation();
  return <p data-testid="where">{loc.pathname + loc.search}</p>;
}

function renderPage() {
  localStorage.setItem('activeProfileId', '3');
  return render(
    <Suspense fallback="loading">
      <MemoryRouter initialEntries={['/calendar']}>
        <Routes>
          <Route path="/calendar" element={<CalendarPage />} />
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>
    </Suspense>
  );
}

afterEach(() => vi.resetAllMocks());

test('days, the week row, and where an episode leads', async () => {
  fetchCalendar.mockResolvedValue({
    today: '2026-11-06',
    tracked: 1,
    recent: [ep(1, 1, 1, '2026-11-03', 'Shift 1')],
    upcoming: [ep(2, 1, 2, '2026-11-06', 'Shift 2'), ep(3, 1, 3, '2026-11-07', 'Shift 3'), ep(4, 1, 4, '2026-11-16', 'Shift 4')],
    suggestions: [],
  });
  renderPage();

  const today = await screen.findByRole('region', { name: /^Today/ });
  expect(today).toHaveTextContent('Friday, November 6');
  expect(screen.getByRole('region', { name: /^Tomorrow/ })).toHaveTextContent('Shift 3');
  expect(screen.getByRole('region', { name: /^Monday, November 16/ })).toHaveTextContent('In 10 days');
  expect(screen.getByRole('region', { name: 'Out this past week' })).toHaveTextContent('Shift 1');

  // out today: the player on that episode
  fireEvent.click(within(today).getByRole('button', { name: /Night Shift, season 1, episode 2/ }));
  expect(screen.getByTestId('where')).toHaveTextContent('/watch/7?season=1&episode=2');
});

test('an episode still to come opens the show', async () => {
  fetchCalendar.mockResolvedValue({
    today: '2026-11-06', tracked: 1, recent: [], upcoming: [ep(3, 1, 3, '2026-11-07', 'Shift 3')], suggestions: [],
  });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /Night Shift, season 1, episode 3/ }));
  expect(screen.getByTestId('where')).toHaveTextContent('/tv/7');
});

test('a calendar that could not load offers to try again', async () => {
  fetchCalendar.mockRejectedValue({ response: { status: 500 } });
  renderPage();
  expect(await screen.findByText("Couldn't load your calendar")).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
});

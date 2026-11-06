// "What do you like to watch?": Continue only once enough titles are picked, the picks are sent,
// then the home page opens. Skip goes home without saving anything.
import React, { Suspense } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import TastePage from './TastePage';
import { fetchTasteTitles, saveTaste } from '../../api/recoApi';

vi.mock('../../api/recoApi', () => ({
  fetchTasteTitles: vi.fn(),
  saveTaste: vi.fn(),
}));

const TITLES = [1, 2, 3, 4].map((id) => ({ id, type: 'movie', title: `Movie ${id}`, poster: '', release_year: 2000 + id }));

function renderPage() {
  localStorage.setItem('activeProfileId', '7');
  return render(
    <Suspense fallback="loading">
      <MemoryRouter initialEntries={['/taste']}>
        <Routes>
          <Route path="/taste" element={<TastePage />} />
          <Route path="/" element={<p>home page</p>} />
        </Routes>
      </MemoryRouter>
    </Suspense>
  );
}

beforeEach(() => {
  fetchTasteTitles.mockResolvedValue({ titles: TITLES, min_picks: 3 });
  saveTaste.mockResolvedValue({ liked: 3, home: 'rebuilt' });
});
afterEach(() => vi.clearAllMocks());

test('Continue waits for enough picks, then saves them and opens the home page', async () => {
  renderPage();
  const pick = async (name) => fireEvent.click(await screen.findByRole('button', { name: new RegExp(name) }));
  const cont = await screen.findByRole('button', { name: 'Continue' });
  expect(cont).toBeDisabled();
  expect(screen.getByText('Pick 3 more')).toBeInTheDocument();

  await pick('Movie 1');
  await pick('Movie 2');
  await pick('Movie 4');
  await pick('Movie 4'); // unpicked again
  expect(screen.getByText('Pick 1 more')).toBeInTheDocument();
  await pick('Movie 3');
  expect(screen.getByRole('button', { name: /Movie 3/ })).toHaveAttribute('aria-pressed', 'true');
  expect(cont).toBeEnabled();

  fireEvent.click(cont);
  expect(await screen.findByText('home page')).toBeInTheDocument();
  expect(saveTaste).toHaveBeenCalledWith('7', [1, 2, 3]);
});

test('Skip goes home without saving', async () => {
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Skip for now' }));
  expect(await screen.findByText('home page')).toBeInTheDocument();
  await waitFor(() => expect(saveTaste).not.toHaveBeenCalled());
});

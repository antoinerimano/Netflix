// "Ask Taurus" (/ask): starters before the first question, the answer (reply, titles, follow-ups),
// the earlier turns sent back, logging (shown / clicked), the AI cap ("come back tomorrow", nothing
// to tap) and a failure (the chips stay to try again).
import React, { Suspense } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import AskPage from './AskPage';
import { askTaurus } from '../../api/recoApi';
import { logImpressions, logTitleClick } from '../../api/analyticsApi';

vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../Footer', () => ({ default: () => null }));
vi.mock('../../api/recoApi', () => ({ askTaurus: vi.fn() }));
vi.mock('../../api/analyticsApi', () => ({ logImpressions: vi.fn(), logTitleClick: vi.fn() }));

const film = (id, title, type = 'movie') => ({ id, type, title, poster: '', release_year: 2001, minutes: 95 });
const failure = (status, code) => Object.assign(new Error('failed'), { response: { status, data: code ? { code } : {} } });

function renderPage() {
  localStorage.setItem('activeProfileId', '3');
  return render(
    <Suspense fallback="loading">
      <MemoryRouter initialEntries={['/ask']}>
        <Routes>
          <Route path="/ask" element={<AskPage />} />
          <Route path="/movies/:id" element={<p>movie page</p>} />
        </Routes>
      </MemoryRouter>
    </Suspense>
  );
}

beforeEach(() => {
  askTaurus.mockReset();
  logImpressions.mockReset();
  logImpressions.mockResolvedValue({});
  logTitleClick.mockReset();
  logTitleClick.mockResolvedValue({});
});

test('a starter asks, the answer shows, follow-ups replace the starters', async () => {
  askTaurus.mockResolvedValueOnce({ reply: 'Two light picks.', items: [film(1, 'Amélie'), film(2, 'Paddington')], chips: ['Shorter', 'A series instead'] });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Something funny tonight' }));
  expect(await screen.findByText('Two light picks.')).toBeTruthy();
  expect(askTaurus).toHaveBeenCalledWith('3', 'Something funny tonight', []);
  expect(screen.getByRole('button', { name: /Amélie/ })).toHaveTextContent('1 hr 35 min');
  expect(screen.queryByRole('button', { name: 'Something funny tonight' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Shorter' })).toBeTruthy();
  expect(logImpressions).toHaveBeenCalledWith({ items: [{ title_id: 1, position: 0 }, { title_id: 2, position: 1 }], row_type: 'ask' });
});

test('a follow-up sends the earlier turns back; a title opens and is logged', async () => {
  askTaurus
    .mockResolvedValueOnce({ reply: 'First.', items: [film(1, 'Amélie')], chips: ['Shorter'] })
    .mockResolvedValueOnce({ reply: 'Shorter ones.', items: [film(5, 'Short One')], chips: [] });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Something funny tonight' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Shorter' }));
  expect(await screen.findByText('Shorter ones.')).toBeTruthy();
  expect(askTaurus).toHaveBeenLastCalledWith('3', 'Shorter', [{ message: 'Something funny tonight', reply: 'First.' }]);
  fireEvent.click(screen.getByRole('button', { name: /Short One/ }));
  expect(logTitleClick).toHaveBeenCalledWith({ title_id: 5, surface: 'ask', position: 0 });
  expect(await screen.findByText('movie page')).toBeTruthy();
});

test('typed with a keyboard', async () => {
  askTaurus.mockResolvedValueOnce({ reply: 'Ok.', items: [], chips: [] });
  renderPage();
  fireEvent.change(await screen.findByRole('textbox', { name: 'What do you feel like watching?' }), { target: { value: '  a heist film  ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Ask' }));
  expect(await screen.findByText('Ok.')).toBeTruthy();
  expect(askTaurus).toHaveBeenCalledWith('3', 'a heist film', []);
});

test('the AI cap: come back tomorrow, nothing left to tap', async () => {
  askTaurus.mockRejectedValueOnce(failure(429, 'ai_budget'));
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'A series to binge' }));
  expect(await screen.findByText('Taurus is resting for today. Come back tomorrow.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Something funny tonight' })).toBeNull();
  expect(screen.queryByRole('textbox')).toBeNull();
});

test('a failure: the starters stay to try again', async () => {
  askTaurus.mockRejectedValueOnce(failure(503)).mockResolvedValueOnce({ reply: 'Back.', items: [], chips: [] });
  renderPage();
  fireEvent.click(await screen.findByRole('button', { name: 'Something feel-good' }));
  expect(await screen.findByText('Taurus can\'t answer right now. Try again in a moment.')).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Something feel-good' }));
  expect(await screen.findByText('Back.')).toBeTruthy();
});

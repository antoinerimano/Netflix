// "Catch me up" (backend reco/recap.py): no button without anything to recap, the recap in
// paragraphs with the AI note, "Resume S2 E2", a daily / monthly AI cap -> "come back tomorrow"
// with no "Try again", a failure -> "Try again" that works.
import React, { Suspense } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import '../../i18n';
import RecapButton from './RecapButton';
import { fetchRecap } from '../../api/recoApi';

vi.mock('../../api/recoApi', () => ({ fetchRecap: vi.fn() }));

const AT = { available: true, season: 2, episode: 2 };
const failure = (status, code) => Object.assign(new Error('failed'), { response: { status, data: code ? { code } : {} } });

function renderButton(onResume = vi.fn()) {
  render(
    <Suspense fallback="loading">
      <RecapButton titleId={10} profileId="3" onResume={onResume} />
    </Suspense>
  );
  return onResume;
}

// braces: a function returned from beforeEach is run as a clean-up after the test (the mock itself!)
beforeEach(() => {
  fetchRecap.mockReset();
});

it('stays hidden when there is nothing to recap', async () => {
  fetchRecap.mockResolvedValue({ available: false });
  renderButton();
  await vi.waitFor(() => expect(fetchRecap).toHaveBeenCalledWith('3', 10, { peek: true }));
  expect(screen.queryByRole('button', { name: 'Catch me up' })).toBeNull();
});

it('opens the recap, then resumes at the episode', async () => {
  fetchRecap.mockImplementation((_p, _t, opts) =>
    Promise.resolve(opts?.peek ? AT : { ...AT, text: 'Season 1: it starts.\n\nSeason 2: it goes on.' })
  );
  const onResume = renderButton();
  fireEvent.click(await screen.findByRole('button', { name: 'Catch me up' }));
  expect(await screen.findByText('Season 1: it starts.')).toBeTruthy();
  expect(screen.getByText('Season 2: it goes on.')).toBeTruthy();
  expect(screen.getByText('Everything before season 2, episode 2: no spoilers.')).toBeTruthy();
  expect(screen.getByText(/Written by AI/)).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Resume S2 E2' }));
  expect(onResume).toHaveBeenCalledWith(2, 2);
});

it('says come back tomorrow when an AI cap is reached, without Try again', async () => {
  fetchRecap.mockImplementation((_p, _t, opts) => {
    if (opts?.peek) return Promise.resolve(AT);
    return Promise.reject(failure(429, 'ai_budget'));
  });
  renderButton();
  fireEvent.click(await screen.findByRole('button', { name: 'Catch me up' }));
  expect(await screen.findByText('Recaps are taking a break for today. Come back tomorrow.')).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Resume S2 E2' })).toBeTruthy(); // still there
});

it('offers Try again after a failure, and it works', async () => {
  let calls = 0;
  fetchRecap.mockImplementation((_p, _t, opts) => {
    if (opts?.peek) return Promise.resolve(AT);
    calls += 1;
    return calls === 1 ? Promise.reject(failure(503)) : Promise.resolve({ ...AT, text: 'Back on track.' });
  });
  renderButton();
  fireEvent.click(await screen.findByRole('button', { name: 'Catch me up' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Try again' }));
  expect(await screen.findByText('Back on track.')).toBeTruthy();
});

// "More like this" (roadmap 8.7): each card is logged as shown with the list it came from (TMDB's
// recommendations or the embeddings), once, when the row is on screen; nothing when it's empty.
import React, { Suspense } from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import MoreLikeThis from './MoreLikeThis';
import { fetchSimilarTitles } from '../../api/titlesApi';
import { logImpressions } from '../../api/analyticsApi';

vi.mock('../../api/titlesApi', () => ({ fetchSimilarTitles: vi.fn() }));
vi.mock('../../api/analyticsApi', () => ({ logImpressions: vi.fn(), logTitleClick: vi.fn(), logOutboundClickBeacon: vi.fn() }));

const film = (id, title, source) => ({ id, type: 'movie', title, poster: '', release_year: 2000, source });

function renderRow() {
  return render(
    <Suspense fallback="loading">
      <MemoryRouter>
        <MoreLikeThis titleId={5} />
      </MemoryRouter>
    </Suspense>
  );
}

beforeEach(() => {
  logImpressions.mockReset();
  logImpressions.mockResolvedValue({});
});

it('logs each card with its source, once', async () => {
  fetchSimilarTitles.mockResolvedValue([film(1, 'Inception', 'tmdb'), film(2, 'Heat', 'embeddings'), film(3, 'Old', undefined)]);
  renderRow();
  expect((await screen.findAllByText('Inception')).length).toBeGreaterThan(0);
  await vi.waitFor(() => expect(logImpressions).toHaveBeenCalledTimes(1));
  expect(logImpressions).toHaveBeenCalledWith({
    items: [
      { title_id: 1, position: 0, row_type: 'more_like_this:tmdb' },
      { title_id: 2, position: 1, row_type: 'more_like_this:embeddings' },
      { title_id: 3, position: 2, row_type: 'more_like_this:embeddings' }, // an older answer: no source
    ],
  });
});

it('logs nothing when there is nothing similar', async () => {
  fetchSimilarTitles.mockResolvedValue([]);
  const { container } = renderRow();
  await vi.waitFor(() => expect(fetchSimilarTitles).toHaveBeenCalled());
  await new Promise((r) => setTimeout(r, 20));
  expect(container.querySelector('.detail-section')).toBeNull();
  expect(logImpressions).not.toHaveBeenCalled();
});

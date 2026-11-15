// The title page's top: content notes from the AI tags (roadmap 8.4): "Contains: ..." in a fixed
// order, unknown values dropped, nothing at all without notes, never a stop for the remote.
import React, { Suspense } from 'react';
import { render, screen } from '@testing-library/react';
import '../../i18n';
import i18n from '../../i18n';
import DetailHero, { contentNotesText } from './DetailHero';

const film = (extra = {}) => ({ id: 1, title: 'Heat', genre: 'Crime, Drama', description: 'A heist.', ...extra });

function renderHero(title) {
  return render(
    <Suspense fallback="loading">
      <DetailHero title={title} kind="movie" meta={['1995']} />
    </Suspense>
  );
}

describe('content notes', () => {
  const t = i18n.getFixedT('en', 'catalog');

  it('reads them in the vocabulary order, in words', () => {
    expect(contentNotesText(['strong_language', 'violence', 'gore'], t, 'en')).toBe(
      'Contains: violence, gore, and strong language'
    );
  });

  it('drops values it does not know, and says nothing without notes', () => {
    expect(contentNotesText(['made_up', 'nudity'], t, 'en')).toBe('Contains: nudity');
    expect(contentNotesText(['made_up'], t, 'en')).toBe('');
    expect(contentNotesText([], t, 'en')).toBe('');
    expect(contentNotesText(undefined, t, 'en')).toBe('');
  });

  it('shows them on the page as plain text', async () => {
    const { container } = renderHero(film({ content_notes: ['violence', 'strong_language'] }));
    const notes = await screen.findByText('Contains: violence and strong language');
    expect(notes.closest('.detail-hero__notes')).not.toBeNull();
    // not a control: no tab stop, nothing the remote has to cross
    expect(notes.closest('[tabindex], button, a')).toBeNull();
    expect(container.querySelector('.detail-hero__notes svg')).not.toBeNull();
  });

  it('leaves the line out when the title has none', async () => {
    const { container } = renderHero(film({ content_notes: [] }));
    await screen.findByRole('heading', { name: 'Heat' });
    expect(container.querySelector('.detail-hero__notes')).toBeNull();
  });
});

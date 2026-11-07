// "Add to a list": the lists with a check where the title is, OK toggles it, a new list starts
// with the title, an empty name is refused, the focus lands on the first list once they arrive.
import React, { Suspense } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import '../../i18n';
import ListPicker from './ListPicker';
import { createList, fetchLists, setInList } from '../../api/listsApi';

vi.mock('../../api/listsApi', () => ({ fetchLists: vi.fn(), createList: vi.fn(), setInList: vi.fn() }));

const title = { id: 5, type: 'movie', title: 'Heat' };

function renderPicker() {
  localStorage.setItem('activeProfileId', '3');
  return render(
    <Suspense fallback="loading">
      <ListPicker title={title} open onClose={() => {}} />
    </Suspense>
  );
}

afterEach(() => vi.resetAllMocks());

test('toggles the title in a list, the focus starts on the first list', async () => {
  fetchLists.mockResolvedValue({ lists: [
    { id: 1, name: 'Heists', count: 2, contains: true, covers: [] },
    { id: 2, name: 'Sunday', count: 0, contains: false, covers: [] },
  ] });
  setInList.mockResolvedValue();
  renderPicker();
  const heists = await screen.findByRole('button', { name: /Heists/ });
  expect(fetchLists).toHaveBeenCalledWith('3', 5);
  expect(heists).toHaveAttribute('aria-pressed', 'true');
  await waitFor(() => expect(heists).toHaveFocus());

  const sunday = screen.getByRole('button', { name: /Sunday/ });
  fireEvent.click(sunday);
  expect(sunday).toHaveAttribute('aria-pressed', 'true');
  expect(sunday).toHaveTextContent('1 title');
  expect(setInList).toHaveBeenCalledWith('3', 2, 5, true);
  expect(await screen.findByText('Added to Sunday')).toBeInTheDocument();
});

test('a new list starts with the title; an empty name is refused', async () => {
  fetchLists.mockResolvedValue({ lists: [] });
  createList.mockResolvedValue({ id: 9, name: 'Mafia', count: 1, covers: [] });
  renderPicker();
  const field = await screen.findByPlaceholderText('e.g. Best heist movies');
  fireEvent.click(screen.getByRole('button', { name: 'Create' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Give the list a name.');
  expect(createList).not.toHaveBeenCalled();

  fireEvent.change(field, { target: { value: 'Mafia' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create' }));
  expect(await screen.findByRole('button', { name: /Mafia/ })).toHaveAttribute('aria-pressed', 'true');
  expect(createList).toHaveBeenCalledWith('3', { name: 'Mafia', titleId: 5 });
});

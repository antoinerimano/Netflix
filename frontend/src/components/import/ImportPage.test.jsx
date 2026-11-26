// "Import your history": the summary after an import (focus on "Go to your home page", titles not
// found) and a refused file. The server is mocked.
import React, { Suspense } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { vi } from 'vitest';
import '../../i18n';
import ImportPage from './ImportPage';
import { importAniList, importFiles } from '../../api/importApi';

vi.mock('../Navbar', () => ({ default: () => null }));
vi.mock('../Footer', () => ({ default: () => null }));
vi.mock('../../api/importApi', () => ({ importFiles: vi.fn(), importAniList: vi.fn() }));

const SUMMARY = { liked: 2, disliked: 0, watched: 5, listed: 1, matched: 7, not_found: 1, not_found_examples: ['Lost (1999)'] };

function renderPage() {
  localStorage.setItem('activeProfileId', '7');
  localStorage.setItem('activeProfile', JSON.stringify({ id: 7, name: 'Sam' }));
  return render(
    <Suspense fallback="loading">
      <MemoryRouter>
        <ImportPage />
      </MemoryRouter>
    </Suspense>
  );
}

afterEach(() => vi.resetAllMocks()); // queued answers must not leak into the next test

test('a file import: summary, focus on "Go to your home page", titles not found on demand', async () => {
  importFiles.mockResolvedValue(SUMMARY);
  const { container } = renderPage();
  const file = new File(['x'], 'ratings.csv', { type: 'text/csv' });
  fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } });

  expect(await screen.findByRole('heading', { name: 'Import done' })).toBeInTheDocument();
  expect(importFiles).toHaveBeenCalledWith('7', [file]);
  expect(screen.getByRole('button', { name: 'Go to your home page' })).toHaveFocus();
  expect(screen.queryByText('Lost (1999)')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Show titles not found' }));
  expect(screen.getByText('Lost (1999)')).toBeInTheDocument();
});

test('Letterboxd first, IMDb a press away, an unreadable file is explained', async () => {
  importFiles.mockRejectedValue({ response: { status: 400, data: { code: 'unknown_format' } } });
  const { container } = renderPage();
  expect(await screen.findByRole('button', { name: /Letterboxd/ })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: /IMDb/ }));
  expect(screen.getByRole('button', { name: /IMDb/ })).toHaveAttribute('aria-pressed', 'true');

  const file = new File(['a,b\n'], 'notes.csv', { type: 'text/csv' });
  fireEvent.change(container.querySelector('input[type="file"]'), { target: { files: [file] } });
  expect(await screen.findByRole('alert')).toHaveTextContent("We couldn't read that file.");
  expect(importFiles).toHaveBeenCalledWith('7', [file]);
});

test('AniList: a user name, no file; a list that cannot be read is explained', async () => {
  importAniList.mockRejectedValueOnce({ response: { status: 404, data: { code: 'anilist_not_found' } } });
  importAniList.mockResolvedValueOnce(SUMMARY);
  const { container } = renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /AniList/ }));
  expect(container.querySelector('input[type="file"]')).toBeNull();
  const field = screen.getByRole('textbox', { name: 'AniList user name' });
  fireEvent.change(field, { target: { value: ' Alice_1 ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Import my list' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Check the name, and that your list is public');
  expect(importAniList).toHaveBeenCalledWith('7', 'Alice_1');
  fireEvent.click(screen.getByRole('button', { name: 'Import my list' }));
  expect(await screen.findByRole('heading', { name: 'Import done' })).toBeInTheDocument();
});

test('MyAnimeList: its export file (.xml.gz)', async () => {
  const { container } = renderPage();
  fireEvent.click(await screen.findByRole('button', { name: /MyAnimeList/ }));
  expect(container.querySelector('input[type="file"]')).toHaveAttribute('accept', '.xml,.gz');
  expect(screen.getByText(/panel\.php\?go=export/)).toBeInTheDocument();
});

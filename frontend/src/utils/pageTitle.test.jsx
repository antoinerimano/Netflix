// usePageTitle: a title / actor page names the browser tab, and gives it back when it closes.
import React from 'react';
import { render } from '@testing-library/react';
import '../i18n';
import { currentPageTitle, usePageTitle } from './pageTitle';

function Page({ name }) {
  usePageTitle(name);
  return null;
}

beforeEach(() => {
  document.title = 'Tauruss – Stream Movies & TV Shows Online in HD';
});

test('sets "<name> | Tauruss" and restores the app title on leaving', () => {
  const { rerender, unmount } = render(<Page name="Heat" />);
  expect(document.title).toBe('Heat | Tauruss');
  expect(currentPageTitle()).toBe('Heat | Tauruss');

  rerender(<Page name="The Wire" />); // next title, same page component
  expect(document.title).toBe('The Wire | Tauruss');

  unmount();
  expect(currentPageTitle()).toBeNull();
  expect(document.title).not.toContain('The Wire');
  expect(document.title).toContain('Tauruss');
});

test('nothing while the name is still loading', () => {
  render(<Page name="" />);
  expect(document.title).toBe('Tauruss – Stream Movies & TV Shows Online in HD');
  expect(currentPageTitle()).toBeNull();
});

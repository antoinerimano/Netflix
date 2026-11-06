// Sign-in page: translated, and the "Create an account" link renders (regression: an empty link
// when the translation used <link>, an HTML void tag).
import React, { Suspense } from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import i18n from '../i18n';
import Login from './Login';
import { AuthContext } from './AuthContext';

function renderLogin() {
  return render(
    <Suspense fallback="loading">
      <AuthContext.Provider value={{ setIsAuthenticated: () => {} }}>
        <MemoryRouter>
          <Login />
        </MemoryRouter>
      </AuthContext.Provider>
    </Suspense>
  );
}

afterEach(async () => {
  await i18n.changeLanguage('en');
});

test('links to sign up', async () => {
  renderLogin();
  const link = await screen.findByRole('link', { name: 'Create an account' });
  expect(link).toHaveAttribute('href', '/register');
});

test('is translated', async () => {
  await i18n.changeLanguage('fr');
  renderLogin();
  expect(await screen.findByRole('heading', { name: 'Bon retour parmi nous' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Créer un compte' })).toHaveAttribute('href', '/register');
});

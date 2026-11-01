import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Routes, Route, Navigate, useLocation, useNavigationType } from 'react-router-dom';
import HomePage from './pages/HomePage';
import Movies from './components/Movies';
import MovieDetail from './components/MovieDetail';
import TVShows from './components/TVShows';
import TVShowDetail from './components/TVShowDetail';
import List from './components/List';
import AccountManagement from './components/AccountManagement';
import Register from './components/Register';
import Login from './components/Login';
import CreateProfile from './components/CreateProfile';
import ConfirmPasswordReset from './components/ConfirmPasswordReset';
import ConfirmEmailChange from './components/ConfirmEmailChange';
import AdminMovies from './components/AdminMovies';
import AdminUsers from './components/AdminUsers';
import WatchPage from './components/WatchPage';
import ActorDetail from './components/ActorDetails';
import ProtectedStaffRoute from './ProtectedStaffRoute';
import ProtectedRoute from './ProtectedRoute';
import DesignSystemPage from './design/DesignSystemPage';
import NotFound from './pages/NotFound';
import ProfilesPage from './components/profiles/ProfilesPage';
import SearchPage from './pages/SearchPage';
import { restorePlace } from './tv/spatialNavigation';
import { useTranslation } from 'react-i18next';

// ✅ add this
import AdManagerLoader from './components/AdManagerLoader';

function App() {
  // the browser tab / installed app title in the app's language
  const { t } = useTranslation();
  useEffect(() => {
    document.title = t('meta.title');
  }, [t]);

  // a profile switch remounts every page for the new profile (its home, list, age limit...)
  // instead of reloading the whole app
  const [profileKey, setProfileKey] = useState(() => localStorage.getItem('activeProfileId') || '');
  useEffect(() => {
    const onChange = () => setProfileKey(localStorage.getItem('activeProfileId') || '');
    window.addEventListener('activeProfileChanged', onChange);
    return () => window.removeEventListener('activeProfileChanged', onChange);
  }, []);

  // a new page starts at the top (a title opened from far down a row opened half-scrolled);
  // Back / Forward keep their place (the browse pages restore theirs)
  const location = useLocation();
  const navigationType = useNavigationType();
  // a new page starts at the top (Back keeps the place). Only when the page itself changes: a
  // page updating its own URL (browse filters, "load more") must not jump back to the top.
  const lastPath = useRef(location.pathname);
  useLayoutEffect(() => {
    if (lastPath.current === location.pathname) return;
    lastPath.current = location.pathname;
    if (navigationType !== 'POP') window.scrollTo(0, 0);
    else restorePlace(); // Back: the remote lands on the item it was on
  }, [location.pathname, navigationType]);

  return (
    <>
      {/* ✅ charge le script 1 seule fois pour toute l'app */}
      <AdManagerLoader />

      {/* each page fades in (design/base.css .page-enter): keyed on the path only, so filters /
          search in the URL don't replay it */}
      <div className="page-enter" key={location.pathname}>
      <Routes key={profileKey}>
        {/* "Who's watching?": signed in, no profile needed yet */}
        <Route
          path="/profiles"
          element={
            <ProtectedRoute requireProfile={false}>
              <ProfilesPage />
            </ProtectedRoute>
          }
        />

        {/* ✅ Home protégée: si pas connecté => /login */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <HomePage />
            </ProtectedRoute>
          }
        />

        {/* Search: every result, recent searches, popular */}
        <Route
          path="/search"
          element={
            <ProtectedRoute>
              <SearchPage />
            </ProtectedRoute>
          }
        />

        {/* Movies */}
        <Route path="/movies" element={<Movies />} />
        <Route path="/movies/:movieId" element={<MovieDetail />} />

        {/* TV */}
        <Route path="/tv" element={<TVShows />} />
        <Route path="/tv/:id" element={<TVShowDetail />} />

        {/* User/account */}
        <Route path="/account/:userId" element={<AccountManagement />} />
        <Route path="/list" element={<List />} />
        <Route path="/register" element={<Register />} />
        <Route path="/login" element={<Login />} />
        <Route path="/create-profile" element={<CreateProfile />} />
        {/* plans are set aside for now (ROADMAP 4.22): the page stays in the code for later */}
        <Route path="/choose-subscription" element={<Navigate to="/" replace />} />
        <Route path="/reset-password/:uid/:token" element={<ConfirmPasswordReset />} />
        <Route path="/confirm-email-change" element={<ConfirmEmailChange />} />
        <Route path="/confirm-email-change/:userId/:token" element={<ConfirmEmailChange />} />
        <Route path="/watch/:id" element={<WatchPage />} />
        <Route path="/actor/:tmdbId" element={<ActorDetail />} />

        {/* Admin-only */}
        <Route
          path="/admin/movies"
          element={
            <ProtectedStaffRoute>
              <AdminMovies />
            </ProtectedStaffRoute>
          }
        />
        <Route
          path="/admin/users"
          element={
            <ProtectedStaffRoute>
              <AdminUsers />
            </ProtectedStaffRoute>
          }
        />
        <Route path="/admin/*" element={<Navigate to="/" replace />} />

        {/* Living style guide (src/design), development only */}
        {process.env.NODE_ENV !== 'production' ? (
          <Route path="/design-system" element={<DesignSystemPage />} />
        ) : null}

        {/* unknown address: a real "not found" page (was a blank screen) */}
        <Route path="*" element={<NotFound />} />
      </Routes>
      </div>
    </>
  );
}

export default App;

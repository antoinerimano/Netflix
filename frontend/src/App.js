import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
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
import ChooseSubscription from './components/ChooseSubscription';
import ConfirmPasswordReset from './components/ConfirmPasswordReset';
import ConfirmEmailChange from './components/ConfirmEmailChange';
import AdminMovies from './components/AdminMovies';
import AdminUsers from './components/AdminUsers';
import WatchPage from './components/WatchPage';
import ActorDetail from './components/ActorDetails';
import ProtectedStaffRoute from './ProtectedStaffRoute';
import ProtectedRoute from './ProtectedRoute';

// ✅ add this
import AdManagerLoader from './components/AdManagerLoader';

function App() {
  return (
    <>
      {/* ✅ charge le script 1 seule fois pour toute l'app */}
      <AdManagerLoader />

      <Routes>
        {/* ✅ Home protégée: si pas connecté => /login */}
        <Route
          path="/"
          element={
            <ProtectedRoute>
              <HomePage />
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
        <Route path="/choose-subscription" element={<ChooseSubscription />} />
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

        {/* Optionnel: catch-all */}
        {/* <Route path="*" element={<Navigate to="/" replace />} /> */}
      </Routes>
    </>
  );
}

export default App;

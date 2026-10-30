import React, { useState, useEffect, useContext, useRef } from 'react';
import './Navbar.css';
import { useNavigate } from 'react-router-dom';
import { searchTitles } from '../api/titlesApi';
import { AuthContext } from './AuthContext';
import { fetchUserProfiles } from '../api/userApi';
import { logTitleClick } from '../api/analyticsApi';
import NotificationBell from './NotificationBell';
import { tmdbImage, tmdbSrcSet } from '../utils/tmdbImage';

const SITE_URL = 'https://tauruss.top/';

const Navbar = () => {
  const [profiles, setProfiles] = useState([]);
  const [profilePhoto, setProfilePhoto] = useState('/default-profile.png');
  const [selectedProfile, setCurrentProfile] = useState(null);
  const [isProfileDropdownOpen, setIsProfileDropdownOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]); // [{id,title,poster,description,kind:'movie'|'tv'}]
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [shareStatus, setShareStatus] = useState(''); // '', 'copied', 'shared'

  const searchRef = useRef(null);
  const navigate = useNavigate();
  const { isAuthenticated, logout } = useContext(AuthContext);

  const userId = localStorage.getItem('userId');
  const isStaff = localStorage.getItem('isStaff') === '1'; // ADMIN

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");

    const update = () => setIsMobile(mq.matches);
    update();

    // support vieux navigateurs
    if (mq.addEventListener) mq.addEventListener("change", update);
    else mq.addListener(update);

    return () => {
      if (mq.removeEventListener) mq.removeEventListener("change", update);
      else mq.removeListener(update);
    };
  }, []);

  // Load profiles & photo
  useEffect(() => {
    const loadProfilesAndPhoto = async () => {
      if (!userId) return;

      try {
        const raw = await fetchUserProfiles(userId);

        // ✅ normalize: accept array OR paginated object {results: [...]}
        const list = Array.isArray(raw) ? raw : (raw?.results ?? []);

        setProfiles(list);

        const savedProfileId = localStorage.getItem('activeProfileId');
        const active =
          list.find((p) => String(p.id) === String(savedProfileId)) || list[0] || null;

        setCurrentProfile(active);
        setProfilePhoto(active?.avatar_url || '/default-profile.png');
      } catch (e) {
        console.error('Failed to load profiles:', e);
        setProfiles([]);
        setCurrentProfile(null);
        setProfilePhoto('/default-profile.png');
      }
    };

    loadProfilesAndPhoto();
  }, [userId]);

  // Debounced cross-type search (Movies + TV)
  useEffect(() => {
    const t = setTimeout(async () => {
      const q = (query || '').trim();
      if (!q) {
        setResults([]);
        return;
      }

      try {
        const data = await searchTitles({ q, type: 'all', limit: 15 });

        const merged = (data || []).map((item) => ({
          id: item.id,
          title: item.title,
          poster: item.poster || item.landscape_image || '',
          description: item.description || item.overview || '',
          kind: item.type === 'tv' ? 'tv' : 'movie',
          match: item.match || '', // why it was found: "With Bryan Cranston", "Close match", ...
        }));

        setResults(merged);
      } catch (e) {
        console.error(e);
        setResults([]);
      }
    }, 250);

    return () => clearTimeout(t);
  }, [query]);

  // Close results when clicking outside the search box/results
  useEffect(() => {
    function handleClickOutside(e) {
      if (searchRef.current && !searchRef.current.contains(e.target)) {
        setResults([]);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleProfileChange = (profileId) => {
    const selected = profiles.find((p) => String(p.id) === String(profileId));
    if (!selected) return;

    setCurrentProfile(selected);
    setProfilePhoto(selected?.avatar_url || '/default-profile.png');
    setIsProfileDropdownOpen(false);
    localStorage.setItem('activeProfileId', selected.id);
    window.dispatchEvent(new Event("activeProfileChanged"));
    window.location.reload();
  };

  const handleInputChange = (e) => setQuery(e.target.value);

  const handleResultClick = (item, index) => {
    logTitleClick({
      title_id: item.id,
      surface: 'navbar_search',
      position: index,
      row_title: query ? `search:${query}` : 'search',
    });

    if (item.kind === 'tv') navigate(`/tv/${item.id}`);
    else navigate(`/movies/${item.id}`);

    setResults([]);
    setQuery('');
  };

  const handleShare = async () => {
    try {
      if (navigator.share) {
        await navigator.share({
          title: 'Taurus',
          text: 'Check out Taurus',
          url: SITE_URL,
        });
        setShareStatus('shared');
      } else {
        await navigator.clipboard.writeText(SITE_URL);
        setShareStatus('copied');
      }
    } catch (err) {
      // user cancelled the share sheet — ignore quietly
      if (err.name !== 'AbortError') console.error(err);
      return;
    }
    setTimeout(() => setShareStatus(''), 2000);
  };

  const handleNavigateHome = () => navigate('/');
  const handleNavigateAccount = () =>
    userId ? navigate(`/account/${userId}`) : navigate('/login');
  const handleNavigateMovies = () => navigate('/movies');
  const handleNavigateTV = () => navigate('/tv');
  const handleNavigateList = () => navigate('/list');
  const handleLogin = () => navigate('/login');
  const toggleProfileDropdown = () => setIsProfileDropdownOpen((v) => !v);
  const toggleMenu = () => setIsMenuOpen((v) => !v);
  const handleLogout = () => {
    logout();
    localStorage.removeItem('userId');
    localStorage.removeItem('activeProfileId');
    navigate('/login');
  };

  return (
    <nav className="navbar">
      <div className="logo" onClick={handleNavigateHome}>
        {isMobile ? (
          <img src="/logo/taurus_emblem.png" alt="Taurus" className="logo-img" />
        ) : (
          <img
            src="/logo/navbar-logo.svg"
            alt="Taurus"
            width="927"
            height="108"
            className="logo-svg"
          />
        )}
      </div>

      <button className="menu-toggle" onClick={toggleMenu}>☰</button>

      <ul className={`nav-links ${isMenuOpen ? 'open' : ''}`}>
        <li onClick={handleNavigateHome}>Home</li>
        <li onClick={handleNavigateMovies}>Movies</li>
        <li onClick={handleNavigateTV}>TV Shows</li>
        <li onClick={handleNavigateList}>My List</li>
        {isStaff && (
          <>
            <li onClick={() => navigate('/admin/users')}>Admin Users</li>
            <li onClick={() => navigate('/admin/movies')}>Admin Movies</li>
          </>
        )}
      </ul>

      {/* SHARE */}
      <button
        className="share-button"
        onClick={handleShare}
        title="Share tauruss.top (Ctrl+D to bookmark)"
        aria-label="Share site"
      >
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none"
             stroke="currentColor" strokeWidth="2"
             strokeLinecap="round" strokeLinejoin="round">
          <circle cx="18" cy="5" r="3"/>
          <circle cx="6" cy="12" r="3"/>
          <circle cx="18" cy="19" r="3"/>
          <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
          <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
        </svg>
        {shareStatus && (
          <span className="share-feedback">
            {shareStatus === 'copied' ? 'Link copied!' : 'Shared!'}
          </span>
        )}
      </button>

      {/* SEARCH */}
      <div className="search-profile" ref={searchRef}>
        <input
          type="text"
          placeholder="Search movies & TV"
          value={query}
          onChange={handleInputChange}
        />

        {results.length > 0 && (
          <div
            className="search-results"
            onMouseDown={(e) => e.preventDefault()}
          >
            <ul>
              {results.map((item, idx) => (
                <li
                  key={`${item.kind}-${item.id}`}
                  className="search-result-item"
                  onClick={() => handleResultClick(item, idx)}
                >
                  <img
                    src={tmdbImage(item.poster, "w92")}
                    srcSet={tmdbSrcSet(item.poster, [92, 185, 342])}
                    sizes="(min-width: 2500px) 300px, 60px"
                    alt={item.title}
                    className="search-result-image"
                    loading="lazy"
                  />
                  <div className="search-result-info">
                    <h3>
                      {item.title}{' '}
                      <span className={`badge badge--${item.kind}`}>
                        {item.kind === 'tv' ? 'TV' : 'Movie'}
                      </span>
                    </h3>
                    {item.match && <p className="search-result-match">{item.match}</p>}
                    <p className="search-result-desc">{item.description}</p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* NEW EPISODES */}
      {isAuthenticated && <NotificationBell />}

      {/* PROFILE */}
      {isAuthenticated ? (
        <div className="profile-container">
          <div className="profile-icon" onClick={toggleProfileDropdown}>
            <img
              src={profilePhoto || "default-profile.png"}
              alt="Profile"
              className="profile-avatar"
              onError={(e) => {
                e.currentTarget.onerror = null;
                e.currentTarget.src = "default-profile.png";
              }}
            />
          </div>
          {isProfileDropdownOpen && (
            <div className="profile-dropdown">
              {profiles.length > 0 ? (
                profiles.map((profile) => (
                  <div
                    key={profile.id}
                    className={`profile-option ${selectedProfile && selectedProfile.id === profile.id ? 'selected' : ''}`}
                    onClick={() => handleProfileChange(profile.id)}
                  >
                    <img
                      src={profile.avatar_url || '/default-profile.png'}
                      alt={profile.name}
                    />
                    <span>{profile.name}</span>
                  </div>
                ))
              ) : (
                <div className="profile-option">
                  <span>No profiles found</span>
                </div>
              )}
              <div className="dropdown-divider"></div>
              <div className="profile-option" onClick={handleNavigateAccount}>
                Account Settings
              </div>
              <div className="profile-option" onClick={handleLogout}>
                Logout
              </div>
            </div>
          )}
        </div>
      ) : (
        <button className="login-button" onClick={handleLogin}>Login</button>
      )}
    </nav>
  );
};

export default Navbar;
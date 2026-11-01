import React, { useState, useEffect, useContext, useRef } from 'react';
import './Navbar.css';
import { useNavigate, useLocation } from 'react-router-dom';
import { searchTitles } from '../api/titlesApi';
import { AuthContext } from './AuthContext';
import { fetchUserProfiles } from '../api/userApi';
import { logTitleClick } from '../api/analyticsApi';
import NotificationBell from './NotificationBell';
import { Avatar, BrandLogo } from '../design';
import { setActiveProfile } from '../utils/activeProfile';
import { useInstallApp } from '../pwa/installPrompt';
import { tmdbImage, tmdbSrcSet } from '../utils/tmdbImage';
import {
  HomeIcon, FilmIcon, TvIcon, BookmarkIcon, SearchIcon, ShareIcon, CheckIcon,
} from '../design/icons';

const SITE_URL = 'https://tauruss.top/';

const Navbar = () => {
  const [profiles, setProfiles] = useState([]);
  const [profilePhoto, setProfilePhoto] = useState('');
  const [selectedProfile, setCurrentProfile] = useState(null);
  const [isProfileDropdownOpen, setIsProfileDropdownOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]); // [{id,title,poster,description,kind:'movie'|'tv'}]
  const [shareStatus, setShareStatus] = useState(''); // '', 'copied', 'shared'
  const [showIosInstall, setShowIosInstall] = useState(false);
  const installApp = useInstallApp();

  const searchRef = useRef(null);
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const current = (path) => (path === '/' ? pathname === '/' : pathname.startsWith(path)) ? 'page' : undefined;

  // transparent over the page's artwork at the top, solid once the page scrolls under it
  const [scrolled, setScrolled] = useState(() => typeof window !== 'undefined' && window.scrollY > 8);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  const { isAuthenticated, logout } = useContext(AuthContext);

  const userId = localStorage.getItem('userId');
  const isStaff = localStorage.getItem('isStaff') === '1'; // ADMIN

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 900px)");

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
        setProfilePhoto(active?.avatar_url || '');
      } catch (e) {
        console.error('Failed to load profiles:', e);
        setProfiles([]);
        setCurrentProfile(null);
        setProfilePhoto('');
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
    setProfilePhoto(selected?.avatar_url || '');
    setIsProfileDropdownOpen(false);
    if (String(selected.id) === localStorage.getItem('activeProfileId')) return;
    // the app remounts its pages for the new profile (App.js): no full reload
    setActiveProfile(selected);
    navigate('/');
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

  // the profile menu closes when clicking / moving the focus elsewhere, or on another page
  // (it stayed open over the page, and the remote went on to the rows behind it)
  const profileRef = useRef(null);
  useEffect(() => {
    if (!isProfileDropdownOpen) return undefined;
    const onOutside = (e) => {
      if (profileRef.current && !profileRef.current.contains(e.target)) setIsProfileDropdownOpen(false);
    };
    document.addEventListener('mousedown', onOutside);
    document.addEventListener('focusin', onOutside);
    return () => {
      document.removeEventListener('mousedown', onOutside);
      document.removeEventListener('focusin', onOutside);
    };
  }, [isProfileDropdownOpen]);
  useEffect(() => setIsProfileDropdownOpen(false), [pathname]);
  // phones: the search page (full screen results); desktop: the field in the bar
  const openSearch = () => navigate('/search');
  const seeAllResults = () => {
    const q = query.trim();
    setResults([]);
    setQuery('');
    searchRef.current?.querySelector('input')?.blur();
    navigate(q ? `/search?q=${encodeURIComponent(q)}` : '/search');
  };
  const onSearchPage = pathname === '/search';
  const handleLogout = () => {
    logout();
    localStorage.removeItem('userId');
    localStorage.removeItem('activeProfileId');
    navigate('/login');
  };

  const links = [
    { path: '/', label: 'Home', icon: <HomeIcon />, onClick: handleNavigateHome },
    { path: '/movies', label: 'Movies', icon: <FilmIcon />, onClick: handleNavigateMovies },
    { path: '/tv', label: 'TV Shows', icon: <TvIcon />, onClick: handleNavigateTV },
    { path: '/list', label: 'My List', icon: <BookmarkIcon />, onClick: handleNavigateList },
  ];

  return (
    <>
    <nav className={`navbar${scrolled ? ' navbar--solid' : ''}`}>
      <div className="logo" tabIndex={0} role="button" aria-label="Home" onClick={handleNavigateHome}>
        <BrandLogo variant={isMobile ? 'mark' : 'full'} />
      </div>

      {/* desktop / TV: links in the bar (phones: the tab bar at the bottom) */}
      <ul className="nav-links">
        {links.map((l) => (
          <li key={l.path} tabIndex={0} role="button" aria-current={current(l.path)} onClick={l.onClick}>
            {l.label}
          </li>
        ))}
        {isStaff && (
          <>
            <li tabIndex={0} role="button" aria-current={current('/admin/users')} onClick={() => navigate('/admin/users')}>Admin Users</li>
            <li tabIndex={0} role="button" aria-current={current('/admin/movies')} onClick={() => navigate('/admin/movies')}>Admin Movies</li>
          </>
        )}
      </ul>

      <div className="navbar__actions">
        {/* SEARCH: a field on desktop (results below, "See all" -> the search page), an icon
            opening the search page on phones; hidden on the search page itself */}
        <button
          type="button"
          className="navbar__icon-btn navbar__search-toggle"
          aria-label="Search"
          aria-current={onSearchPage ? 'page' : undefined}
          onClick={openSearch}
        >
          <SearchIcon />
        </button>
        <div className={`search-profile${onSearchPage ? ' is-hidden' : ''}`} ref={searchRef}>
          <SearchIcon className="search-profile__icon" aria-hidden="true" />
          <input
            type="search"
            placeholder="Search movies & TV"
            aria-label="Search movies and TV shows"
            value={query}
            onChange={handleInputChange}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                seeAllResults(); // every result on the search page
              }
            }}
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
                    tabIndex={0}
                    role="button"
                    onClick={() => handleResultClick(item, idx)}
                  >
                    <img
                      src={tmdbImage(item.poster, "w92")}
                      srcSet={tmdbSrcSet(item.poster, [92, 185])}
                      sizes="46px"
                      alt=""
                      className="search-result-image"
                      loading="lazy"
                    />
                    <div className="search-result-info">
                      <h3>
                        <span className="search-result-title">{item.title}</span>
                        <span className={`badge badge--${item.kind}`}>
                          {item.kind === 'tv' ? 'Series' : 'Film'}
                        </span>
                      </h3>
                      {item.match && <p className="search-result-match">{item.match}</p>}
                      <p className="search-result-desc">{item.description}</p>
                    </div>
                  </li>
                ))}
              </ul>
              <button type="button" className="search-results__all" onClick={seeAllResults}>
                <SearchIcon aria-hidden="true" />
                See all results for “{query.trim()}”
              </button>
            </div>
          )}
        </div>

        {/* SHARE (phones: in the profile menu) */}
        <button
          type="button"
          className="navbar__icon-btn share-button"
          onClick={handleShare}
          title="Share tauruss.top (Ctrl+D to bookmark)"
          aria-label="Share site"
        >
          <ShareIcon />
          {shareStatus && (
            <span className="share-feedback">
              {shareStatus === 'copied' ? 'Link copied!' : 'Shared!'}
            </span>
          )}
        </button>

        {/* NEW EPISODES */}
        {isAuthenticated && <NotificationBell />}

        {/* PROFILE */}
        {isAuthenticated ? (
          <div className="profile-container" ref={profileRef}>
            <div className="profile-icon" tabIndex={0} role="button" aria-label="Profiles and account" aria-expanded={isProfileDropdownOpen} onClick={toggleProfileDropdown}>
              <Avatar src={profilePhoto} name={selectedProfile?.name || ''} size="100%" className="navbar__avatar" />
            </div>
            {isProfileDropdownOpen && (
              <div className="profile-dropdown" role="menu">
                <div className="profile-dropdown__label">Profiles</div>
                {profiles.length > 0 ? (
                  profiles.map((profile) => {
                    const isCurrent = selectedProfile && selectedProfile.id === profile.id;
                    return (
                      <div
                        key={profile.id}
                        className={`profile-option ${isCurrent ? 'selected' : ''}`}
                        tabIndex={0}
                        role="menuitemradio"
                        aria-checked={!!isCurrent}
                        onClick={() => handleProfileChange(profile.id)}
                      >
                        <Avatar src={profile.avatar_url} name={profile.name} size="2rem" radius="var(--radius-sm)" />
                        <span className="profile-option__name">{profile.name}</span>
                        {isCurrent ? <CheckIcon className="profile-option__check" aria-hidden="true" /> : null}
                      </div>
                    );
                  })
                ) : (
                  <div className="profile-option profile-option--hint">No profiles found</div>
                )}
                <div className="profile-option" tabIndex={0} role="menuitem" onClick={() => navigate('/profiles?manage')}>
                  Manage profiles
                </div>
                <div className="dropdown-divider"></div>
                {isStaff && (
                  <>
                    <div className="profile-option profile-option--phone" tabIndex={0} role="menuitem" onClick={() => navigate('/admin/users')}>Admin users</div>
                    <div className="profile-option profile-option--phone" tabIndex={0} role="menuitem" onClick={() => navigate('/admin/movies')}>Admin movies</div>
                  </>
                )}
                <div className="profile-option profile-option--phone" tabIndex={0} role="menuitem" onClick={handleShare}>
                  {shareStatus === 'copied' ? 'Link copied!' : 'Share Tauruss'}
                </div>
                {installApp.canInstall && (
                  <div className="profile-option" tabIndex={0} role="menuitem" onClick={() => installApp.install()}>
                    Install app
                  </div>
                )}
                {installApp.iosInstructions && (
                  <div className="profile-option" tabIndex={0} role="menuitem" onClick={() => setShowIosInstall((v) => !v)}>
                    Install app
                  </div>
                )}
                {showIosInstall && (
                  <div className="profile-option profile-option--hint">
                    Tap the Share button in Safari, then "Add to Home Screen".
                  </div>
                )}
                <div className="profile-option" tabIndex={0} role="menuitem" onClick={handleNavigateAccount}>
                  Account settings
                </div>
                <div className="profile-option" tabIndex={0} role="menuitem" onClick={handleLogout}>
                  Sign out
                </div>
              </div>
            )}
          </div>
        ) : (
          <button className="login-button" onClick={handleLogin}>Sign in</button>
        )}
      </div>
    </nav>

    {/* phones: app-style tab bar at the bottom (thumb reach), the top bar keeps search + profile */}
    {isMobile && isAuthenticated ? (
      <nav className="tabbar" aria-label="Main">
        {links.map((l) => (
          <button
            key={l.path}
            type="button"
            className="tabbar__item"
            aria-current={current(l.path)}
            onClick={l.onClick}
          >
            {l.icon}
            <span>{l.label}</span>
          </button>
        ))}
      </nav>
    ) : null}
    </>
  );
};

export default Navbar;
// Login.jsx
import React, { useState, useContext } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';   // ⟵ add useLocation
import { loginUser, fetchUserProfiles } from '../api/userApi';
import { AuthContext } from './AuthContext';
import './Login.css';

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const { setIsAuthenticated } = useContext(AuthContext);
  const navigate = useNavigate();
  const location = useLocation(); // ⟵ to know where we came from

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const data = await loginUser(email, password);
      // expect: data = { access, refresh, user: { id, email, is_staff, ... }, default_profile_id? }

      localStorage.setItem('access', data.access);
      localStorage.setItem('refresh', data.refresh);
      localStorage.setItem('userId', data.user.id);
      localStorage.setItem('isStaff', data.user.is_staff ? '1' : '0');
      localStorage.setItem('user', JSON.stringify(data.user));

      setIsAuthenticated(true);

      // ✅ 1) Prefer backend default_profile_id (fast, reliable)
      let profileId = data.default_profile_id ? String(data.default_profile_id) : null;

      // ✅ 2) Fallback: if backend doesn't send it yet, fetch profiles
      if (!profileId) {
        const resProfiles = await fetchUserProfiles(data.user.id);
        const profiles = Array.isArray(resProfiles) ? resProfiles : (resProfiles?.profiles || []);
        if (profiles.length) {
          profileId = String(profiles[0].id);
          localStorage.setItem('activeProfile', JSON.stringify(profiles[0])); // optionnel
        }
      }

      if (profileId) {
        localStorage.setItem('activeProfileId', profileId);
        window.dispatchEvent(new Event('activeProfileChanged'));
      } else {
        // rare case: user registered but left before creating a profile
        localStorage.removeItem('activeProfileId');
        localStorage.removeItem('activeProfile');

        // 👉 mets ici ta vraie route de création de profil
        navigate('/create-profile', { replace: true });
        return;
      }

      // Smart redirect (inchangé)
      const from = location.state?.from?.pathname;
      if (data.user.is_staff && from && from.startsWith('/admin/')) {
        navigate(from, { replace: true });
      } else {
        navigate('/', { replace: true });
      }
    } catch (err) {
      setError('Invalid email or password. Please try again.');
    }
  };


  return (
    <div className="login-page">
      <div className="login-container">
        <h2 className="login-title">Sign In</h2>
        {error && <p className="error-message">{error}</p>}
        <form onSubmit={handleSubmit} className="login-form">
          <input type="email" placeholder="Email" value={email} onChange={e => setEmail(e.target.value)} required className="login-input" />
          <input type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} required className="login-input" />
          <button type="submit" className="login-button">Sign In</button>
        </form>
        <p className="signup-prompt">New to Taurus? <a href="/register">Sign up now</a>.</p>
      </div>
    </div>
  );
};

export default Login;

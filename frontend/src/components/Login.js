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
  const [loading, setLoading] = useState(false);
  const { setIsAuthenticated } = useContext(AuthContext);
  const navigate = useNavigate();
  const location = useLocation(); // ⟵ to know where we came from

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;            // ✅ empêche double click / double submit
    setLoading(true);
    setError(null);

    try {
      const data = await loginUser(email, password);

      localStorage.setItem('access', data.access);
      localStorage.setItem('refresh', data.refresh);
      localStorage.setItem('userId', data.user.id);
      localStorage.setItem('isStaff', data.user.is_staff ? '1' : '0');
      localStorage.setItem('user', JSON.stringify(data.user));

      setIsAuthenticated(true);

      let profileId = data.default_profile_id ? String(data.default_profile_id) : null;

      if (!profileId) {
        const resProfiles = await fetchUserProfiles(data.user.id);
        const profiles = Array.isArray(resProfiles) ? resProfiles : (resProfiles?.profiles || []);
        if (profiles.length) {
          profileId = String(profiles[0].id);
          localStorage.setItem('activeProfile', JSON.stringify(profiles[0]));
        }
      }

      if (profileId) {
        localStorage.setItem('activeProfileId', profileId);
        window.dispatchEvent(new Event('activeProfileChanged'));
      } else {
        localStorage.removeItem('activeProfileId');
        localStorage.removeItem('activeProfile');
        navigate('/create-profile', { replace: true });
        return;
      }

      const from = location.state?.from?.pathname;
      if (data.user.is_staff && from && from.startsWith('/admin/')) {
        navigate(from, { replace: true });
      } else {
        navigate('/', { replace: true });
      }
    } catch (err) {
      setError('Invalid email or password. Please try again.');
    } finally {
      setLoading(false);
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
          <button
            type="submit"
            className={"login-button" + (loading ? " is-loading" : "")}
            disabled={loading}
            aria-busy={loading}
          >
            {loading ? "Signing in..." : "Sign In"}
          </button>
        </form>
        <p className="signup-prompt">New to Taurus? <a href="/register">Sign up now</a>.</p>
      </div>
    </div>
  );
};

export default Login;

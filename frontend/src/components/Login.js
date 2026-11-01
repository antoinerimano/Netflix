// src/components/Login.js
// Sign in (design system: components/auth). Then "Who's watching?" when the account has several
// profiles, "Create your profile" when it has none, else straight home (or the admin page the
// user was sent away from). "Forgot password?" sends the reset link without leaving the page.
import React, { useState, useContext } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { loginUser, fetchUserProfiles, requestPasswordReset } from '../api/userApi';
import { AuthContext } from './AuthContext';
import { Button, Field, Modal, friendlyError } from '../design';
import { MailIcon } from '../design/icons';
import { AuthAlert, AuthLayout, EMAIL_RE, PasswordField } from './auth/AuthLayout';

function signInError(err) {
  const status = err?.response?.status;
  if (status === 400 || status === 401) return "That email and password don't match. Check them and try again.";
  if (status === 429) return 'Too many attempts. Wait a minute, then try again.';
  return friendlyError(err);
}

function ForgotPassword({ open, onClose, initialEmail }) {
  const [email, setEmail] = useState(initialEmail);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [sentTo, setSentTo] = useState(null);

  // opened again: start from the sign-in email
  React.useEffect(() => {
    if (open) {
      setEmail(initialEmail);
      setError(null);
      setSentTo(null);
    }
  }, [open, initialEmail]);
  // "Send link" is gone once sent: the remote / keyboard focus goes to "Back to sign in"
  React.useEffect(() => {
    if (sentTo) document.querySelector('.ui-modal__footer .ui-btn')?.focus({ preventScroll: true });
  }, [sentTo]);

  const send = async (e) => {
    e?.preventDefault();
    const value = email.trim();
    if (!EMAIL_RE.test(value)) {
      setError('Enter the email you signed up with.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await requestPasswordReset(value);
      setSentTo(value);
    } catch (err) {
      setError(err?.response?.status === 429 ? 'Too many requests. Wait a few minutes, then try again.' : friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Reset your password"
      size="sm"
      scrollable={false}
      initialFocus={sentTo ? '.ui-modal__footer .ui-btn' : '#forgot-email'}
      footer={
        sentTo ? (
          <Button variant="primary" onClick={onClose}>
            Back to sign in
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} onClick={send}>
              Send link
            </Button>
          </>
        )
      }
    >
      {sentTo ? (
        <div className="auth__sent">
          <MailIcon />
          <p>
            If an account exists for <strong>{sentTo}</strong>, a link to choose a new password is on its way.
            Check your spam folder if it doesn't arrive in a few minutes.
          </p>
        </div>
      ) : (
        <form className="auth__form" onSubmit={send} noValidate>
          <p className="ui-field__hint" style={{ fontSize: 'var(--text-sm)' }}>
            We'll email you a link to choose a new password.
          </p>
          <Field label="Email" htmlFor="forgot-email" error={error}>
            <input
              id="forgot-email"
              className="ui-input"
              type="email"
              inputMode="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </Field>
        </form>
      )}
    </Modal>
  );
}

const Login = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [forgotOpen, setForgotOpen] = useState(false);
  const { setIsAuthenticated } = useContext(AuthContext);
  const navigate = useNavigate();
  const location = useLocation();

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return; // no double submit
    if (!EMAIL_RE.test(email.trim()) || !password) {
      setError(!password && EMAIL_RE.test(email.trim()) ? 'Enter your password.' : 'Enter your email and password.');
      return;
    }
    setLoading(true);
    setError(null);

    try {
      const data = await loginUser(email.trim(), password);

      localStorage.setItem('access', data.access);
      localStorage.setItem('refresh', data.refresh);
      localStorage.setItem('userId', data.user.id);
      localStorage.setItem('isStaff', data.user.is_staff ? '1' : '0');
      localStorage.setItem('user', JSON.stringify(data.user));

      setIsAuthenticated(true);

      // several profiles: "Who's watching?" (then where the user was going)
      const resProfiles = await fetchUserProfiles(data.user.id);
      const profiles = Array.isArray(resProfiles) ? resProfiles : (resProfiles?.results || resProfiles?.profiles || []);
      if (profiles.length > 1 && !(data.user.is_staff && location.state?.from?.pathname?.startsWith('/admin/'))) {
        localStorage.removeItem('activeProfileId');
        localStorage.removeItem('activeProfile');
        navigate('/profiles', { replace: true, state: { from: location.state?.from } });
        return;
      }

      let profileId = data.default_profile_id ? String(data.default_profile_id) : null;
      if (!profileId && profiles.length) {
        profileId = String(profiles[0].id);
        localStorage.setItem('activeProfile', JSON.stringify(profiles[0]));
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
      setError(signInError(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to keep watching."
      footer={
        <>
          New to Tauruss? <Link to="/register">Create an account</Link>
        </>
      }
    >
      <form className="auth__form" onSubmit={handleSubmit} noValidate>
        <AuthAlert>{error}</AuthAlert>
        <Field label="Email" htmlFor="login-email">
          <input
            id="login-email"
            className="ui-input"
            type="email"
            inputMode="email"
            autoComplete="username"
            autoCapitalize="off"
            spellCheck={false}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            data-tv-start=""
          />
        </Field>
        <PasswordField label="Password" value={password} onChange={setPassword} autoComplete="current-password" />
        <div className="auth__row">
          <button type="button" className="auth__link" onClick={() => setForgotOpen(true)}>
            Forgot password?
          </button>
        </div>
        <Button type="submit" variant="primary" size="lg" block loading={loading}>
          Sign in
        </Button>
      </form>
      <ForgotPassword open={forgotOpen} onClose={() => setForgotOpen(false)} initialEmail={email.trim()} />
    </AuthLayout>
  );
};

export default Login;

// src/components/Login.js
// Sign in (design system: components/auth). Then "Who's watching?" when the account has several
// profiles, "Create your profile" when it has none, else straight home (or the admin page the
// user was sent away from). "Forgot password?" sends the reset link without leaving the page.
import React, { useState, useContext } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import i18n from '../i18n';
import { loginUser, fetchUserProfiles, requestPasswordReset } from '../api/userApi';
import { AuthContext } from './AuthContext';
import { Button, Field, Modal, friendlyError } from '../design';
import { MailIcon } from '../design/icons';
import { AuthAlert, AuthLayout, EMAIL_RE, PasswordField } from './auth/AuthLayout';
import { setActiveProfile } from '../utils/activeProfile';

function signInError(err) {
  const status = err?.response?.status;
  if (status === 400 || status === 401) return i18n.t('auth:signIn.wrongCredentials');
  if (status === 429) return i18n.t('auth:signIn.tooManyAttempts');
  return friendlyError(err);
}

function ForgotPassword({ open, onClose, initialEmail }) {
  const { t } = useTranslation('auth');
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
      setError(t('forgot.enterEmail'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await requestPasswordReset(value);
      setSentTo(value);
    } catch (err) {
      setError(err?.response?.status === 429 ? t('tooManyRequests') : friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t('forgot.title')}
      size="sm"
      scrollable={false}
      initialFocus={sentTo ? '.ui-modal__footer .ui-btn' : '#forgot-email'}
      footer={
        sentTo ? (
          <Button variant="primary" onClick={onClose}>
            {t('forgot.backToSignIn')}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('actions.cancel')}
            </Button>
            <Button variant="primary" loading={busy} onClick={send}>
              {t('forgot.send')}
            </Button>
          </>
        )
      }
    >
      {sentTo ? (
        <div className="auth__sent">
          <MailIcon />
          <p>
            <Trans t={t} i18nKey="forgot.sent" values={{ email: sentTo }} components={{ strong: <strong /> }} />
          </p>
        </div>
      ) : (
        <form className="auth__form" onSubmit={send} noValidate>
          <p className="ui-field__hint" style={{ fontSize: 'var(--text-sm)' }}>
            {t('forgot.intro')}
          </p>
          <Field label={t('fields.email')} htmlFor="forgot-email" error={error}>
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
  const { t } = useTranslation('auth');
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
      setError(!password && EMAIL_RE.test(email.trim()) ? t('signIn.enterPassword') : t('signIn.enterBoth'));
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
        const chosen = profiles.find((p) => String(p.id) === profileId);
        if (chosen) setActiveProfile(chosen); // also switches to the profile's language
        else {
          localStorage.setItem('activeProfileId', profileId);
          window.dispatchEvent(new Event('activeProfileChanged'));
        }
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
      title={t('signIn.title')}
      subtitle={t('signIn.subtitle')}
      footer={<Trans t={t} i18nKey="signIn.footer" components={{ action: <Link to="/register" /> }} />}
    >
      <form className="auth__form" onSubmit={handleSubmit} noValidate>
        <AuthAlert>{error}</AuthAlert>
        <Field label={t('fields.email')} htmlFor="login-email">
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
        <PasswordField label={t('fields.password')} value={password} onChange={setPassword} autoComplete="current-password" />
        <div className="auth__row">
          <button type="button" className="auth__link" onClick={() => setForgotOpen(true)}>
            {t('signIn.forgot')}
          </button>
        </div>
        <Button type="submit" variant="primary" size="lg" block loading={loading}>
          {t('signIn.submit')}
        </Button>
      </form>
      <ForgotPassword open={forgotOpen} onClose={() => setForgotOpen(false)} initialEmail={email.trim()} />
    </AuthLayout>
  );
};

export default Login;

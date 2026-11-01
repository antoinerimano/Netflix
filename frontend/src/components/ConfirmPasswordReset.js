// src/components/ConfirmPasswordReset.js
// The page the reset email links to (/reset-password/:uid/:token): choose a new password.
// Same rules as sign up (the server's AUTH_PASSWORD_VALIDATORS decide); then back to sign in.
import React, { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { confirmPasswordReset } from '../api/userApi';
import { Button, friendlyError } from '../design';
import { AuthAlert, AuthLayout, PASSWORD_HINT, PasswordField, passwordProblem } from './auth/AuthLayout';

const ConfirmPasswordReset = () => {
  const { uid, token } = useParams();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [touched, setTouched] = useState({});
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const pwProblem = passwordProblem(password);
  const mismatch = confirm && confirm !== password;
  const confirmError =
    mismatch && (touched.confirm || confirm.length >= password.length)
      ? "Passwords don't match."
      : touched.confirm && !confirm
        ? 'Type your new password again.'
        : null;

  const submit = async (e) => {
    e.preventDefault();
    if (busy) return;
    setTouched({ password: true, confirm: true });
    if (pwProblem || !confirm || mismatch) return;
    setBusy(true);
    setError(null);
    try {
      await confirmPasswordReset(uid, token, password);
      setDone(true);
    } catch (err) {
      const reason = err?.response?.data?.error;
      if (/token|link/i.test(reason || '')) setError('This link has expired or was already used. Ask for a new one from the sign-in page.');
      else setError(err?.response?.status === 400 && reason ? reason : friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <AuthLayout title="Password changed" subtitle="You can now sign in with your new password.">
        <Button variant="primary" size="lg" block onClick={() => navigate('/login', { replace: true })} data-tv-start="">
          Sign in
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Choose a new password"
      footer={
        <>
          Remembered it? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form className="auth__form" onSubmit={submit} noValidate>
        <AuthAlert>{error}</AuthAlert>
        <PasswordField
          label="New password"
          value={password}
          onChange={setPassword}
          onBlur={() => setTouched((t) => ({ ...t, password: true }))}
          autoComplete="new-password"
          hint={PASSWORD_HINT}
          error={touched.password ? pwProblem : null}
          data-tv-start=""
        />
        <PasswordField
          label="Confirm new password"
          value={confirm}
          onChange={setConfirm}
          onBlur={() => setTouched((t) => ({ ...t, confirm: true }))}
          autoComplete="new-password"
          error={confirmError}
          ok={confirm && !mismatch && !pwProblem ? 'Passwords match.' : null}
        />
        <Button type="submit" variant="primary" size="lg" block loading={busy}>
          Save password
        </Button>
      </form>
    </AuthLayout>
  );
};

export default ConfirmPasswordReset;

// src/components/ConfirmPasswordReset.js
// The page the reset email links to (/reset-password/:uid/:token): choose a new password.
// Same rules as sign up (the server's AUTH_PASSWORD_VALIDATORS decide); then back to sign in.
import React, { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { confirmPasswordReset } from '../api/userApi';
import { Button, friendlyError } from '../design';
import { AuthAlert, AuthLayout, passwordHint, PasswordField, passwordProblem } from './auth/AuthLayout';

const ConfirmPasswordReset = () => {
  const { t } = useTranslation('auth');
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
      ? t('password.mismatch')
      : touched.confirm && !confirm
        ? t('password.typeNewAgain')
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
      const code = err?.response?.data?.code;
      if (code === 'invalid_link' || (!code && /token|link/i.test(reason || ''))) setError(t('reset.expired'));
      else setError(err?.response?.status === 400 && reason ? reason : friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <AuthLayout title={t('reset.doneTitle')} subtitle={t('reset.doneText')}>
        <Button variant="primary" size="lg" block onClick={() => navigate('/login', { replace: true })} data-tv-start="">
          {t('signIn.submit')}
        </Button>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title={t('reset.title')}
      footer={<Trans t={t} i18nKey="reset.footer" components={{ action: <Link to="/login" /> }} />}
    >
      <form className="auth__form" onSubmit={submit} noValidate>
        <AuthAlert>{error}</AuthAlert>
        <PasswordField
          label={t('fields.newPassword')}
          value={password}
          onChange={setPassword}
          onBlur={() => setTouched((prev) => ({ ...prev, password: true }))}
          autoComplete="new-password"
          hint={passwordHint()}
          error={touched.password ? pwProblem : null}
          data-tv-start=""
        />
        <PasswordField
          label={t('fields.confirmNewPassword')}
          value={confirm}
          onChange={setConfirm}
          onBlur={() => setTouched((prev) => ({ ...prev, confirm: true }))}
          autoComplete="new-password"
          error={confirmError}
          ok={confirm && !mismatch && !pwProblem ? t('password.match') : null}
        />
        <Button type="submit" variant="primary" size="lg" block loading={busy}>
          {t('reset.submit')}
        </Button>
      </form>
    </AuthLayout>
  );
};

export default ConfirmPasswordReset;

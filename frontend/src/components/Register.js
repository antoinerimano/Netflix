// src/components/Register.js
// Sign up, step 1 of 2 (then "Create your profile"). Fields say what's wrong as soon as it's
// known (after leaving a field, or while typing the confirmation), the server's reasons
// (email taken, password too common) show at the top of the card.
import React, { useState, useContext } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { loginUser, registerUser } from '../api/userApi';
import { AuthContext } from './AuthContext';
import { Button, Field } from '../design';
import { AuthAlert, AuthLayout, EMAIL_RE, passwordHint, PasswordField, passwordProblem } from './auth/AuthLayout';

const Register = () => {
  const { t } = useTranslation('auth');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [touched, setTouched] = useState({});
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const { setIsAuthenticated } = useContext(AuthContext);
  const navigate = useNavigate();

  const problems = {
    name: name.trim() ? null : t('signUp.enterName'),
    email: EMAIL_RE.test(email.trim()) ? null : t('signUp.invalidEmail'),
    password: passwordProblem(password),
    confirm: confirmPassword && confirmPassword !== password ? t('password.mismatch') : !confirmPassword ? t('password.typeAgain') : null,
  };
  const show = (field) => (touched[field] ? problems[field] : null);
  const touch = (field) => () => setTouched((prev) => ({ ...prev, [field]: true }));
  // the confirmation is checked live once something is typed in it
  // (as soon as it's as long as the password: no "don't match" while still typing it)
  const mismatch = confirmPassword && confirmPassword !== password;
  const confirmError = mismatch && (touched.confirm || confirmPassword.length >= password.length) ? problems.confirm : show('confirm');
  const confirmOk = confirmPassword && confirmPassword === password && !problems.password ? t('password.match') : null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;
    setTouched({ name: true, email: true, password: true, confirm: true });
    if (Object.values(problems).some(Boolean)) {
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await registerUser(name.trim(), email.trim(), password);
      // the sign-up answer carries the tokens; sign in only if it didn't
      const session = data?.access ? data : await loginUser(email.trim(), password);
      localStorage.setItem('access', session.access);
      localStorage.setItem('refresh', session.refresh);
      localStorage.setItem('userId', session.user.id);
      localStorage.setItem('isStaff', session.user.is_staff ? '1' : '0');
      localStorage.setItem('user', JSON.stringify(session.user));
      setIsAuthenticated(true);
      navigate('/create-profile', { state: { userId: session.user.id } });
    } catch (err) {
      if (err.code === 'email_taken') {
        setError(<Trans t={t} i18nKey="signUp.emailTaken" components={{ action: <Link to="/login" /> }} />);
      } else if (err.code === 'server_reason') {
        setError(err.message); // the server's reason, already in the user's language (password too common...)
      } else {
        setError(t('signUp.failed'));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      step={t('step', { current: 1, total: 2 })}
      title={t('signUp.title')}
      subtitle={t('signUp.subtitle')}
      footer={<Trans t={t} i18nKey="signUp.footer" components={{ action: <Link to="/login" /> }} />}
    >
      <form className="auth__form" onSubmit={handleSubmit} noValidate>
        <AuthAlert>{error}</AuthAlert>
        <Field label={t('fields.name')} htmlFor="register-name" error={show('name')}>
          <input
            id="register-name"
            className="ui-input"
            autoComplete="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={touch('name')}
            maxLength={60}
            data-tv-start=""
          />
        </Field>
        <Field label={t('fields.email')} htmlFor="register-email" error={show('email')}>
          <input
            id="register-email"
            className="ui-input"
            type="email"
            inputMode="email"
            autoComplete="email"
            autoCapitalize="off"
            spellCheck={false}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onBlur={touch('email')}
          />
        </Field>
        <PasswordField
          label={t('fields.password')}
          value={password}
          onChange={setPassword}
          onBlur={touch('password')}
          autoComplete="new-password"
          hint={passwordHint()}
          error={show('password')}
        />
        <PasswordField
          label={t('fields.confirmPassword')}
          value={confirmPassword}
          onChange={setConfirmPassword}
          onBlur={touch('confirm')}
          autoComplete="new-password"
          error={confirmError}
          ok={confirmOk}
        />
        <Button type="submit" variant="primary" size="lg" block loading={loading}>
          {t('actions.continue')}
        </Button>
      </form>
    </AuthLayout>
  );
};

export default Register;

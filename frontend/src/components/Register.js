// src/components/Register.js
// Sign up, step 1 of 2 (then "Create your profile"). Fields say what's wrong as soon as it's
// known (after leaving a field, or while typing the confirmation), the server's reasons
// (email taken, password too common) show at the top of the card.
import React, { useState, useContext } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { loginUser, registerUser } from '../api/userApi';
import { AuthContext } from './AuthContext';
import { Button, Field } from '../design';
import { AuthAlert, AuthLayout, EMAIL_RE, PASSWORD_HINT, PasswordField, passwordProblem } from './auth/AuthLayout';

const Register = () => {
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
    name: name.trim() ? null : 'Enter your name.',
    email: EMAIL_RE.test(email.trim()) ? null : 'Enter a valid email, like name@example.com.',
    password: passwordProblem(password),
    confirm: confirmPassword && confirmPassword !== password ? "Passwords don't match." : !confirmPassword ? 'Type your password again.' : null,
  };
  const show = (field) => (touched[field] ? problems[field] : null);
  const touch = (field) => () => setTouched((t) => ({ ...t, [field]: true }));
  // the confirmation is checked live once something is typed in it
  // (as soon as it's as long as the password: no "don't match" while still typing it)
  const mismatch = confirmPassword && confirmPassword !== password;
  const confirmError = mismatch && (touched.confirm || confirmPassword.length >= password.length) ? problems.confirm : show('confirm');
  const confirmOk = confirmPassword && confirmPassword === password && !problems.password ? 'Passwords match.' : null;

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
      if (err.message === 'This email is already registered') {
        setError(
          <>
            There's already an account with this email. <Link to="/login">Sign in</Link> instead?
          </>
        );
      } else if (err.message && err.message !== 'Failed to register user') {
        setError(err.message); // the server's reason (password too common...)
      } else {
        setError("We couldn't create your account. Please try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      step="Step 1 of 2"
      title="Create your account"
      subtitle="Then make your profile and start watching."
      footer={
        <>
          Already have an account? <Link to="/login">Sign in</Link>
        </>
      }
    >
      <form className="auth__form" onSubmit={handleSubmit} noValidate>
        <AuthAlert>{error}</AuthAlert>
        <Field label="Name" htmlFor="register-name" error={show('name')}>
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
        <Field label="Email" htmlFor="register-email" error={show('email')}>
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
          label="Password"
          value={password}
          onChange={setPassword}
          onBlur={touch('password')}
          autoComplete="new-password"
          hint={PASSWORD_HINT}
          error={show('password')}
        />
        <PasswordField
          label="Confirm password"
          value={confirmPassword}
          onChange={setConfirmPassword}
          onBlur={touch('confirm')}
          autoComplete="new-password"
          error={confirmError}
          ok={confirmOk}
        />
        <Button type="submit" variant="primary" size="lg" block loading={loading}>
          Continue
        </Button>
      </form>
    </AuthLayout>
  );
};

export default Register;

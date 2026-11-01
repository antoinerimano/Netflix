// src/components/auth/AuthLayout.js
// Sign in, sign up, new password, email confirmation: the same frame as "Create your profile"
// (logo, step, big title, one card), so the whole sign-up reads as one flow.
// PasswordField: a labeled password input with a show / hide button.
import React, { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';
import i18n from '../../i18n';
import { EyeIcon, EyeOffIcon } from '../../design/icons';
import LanguagePicker from '../LanguagePicker';
import '../profiles/profiles.css';
import './auth.css';

export function AuthLayout({ step, title, subtitle, children, footer }) {
  return (
    <div className="profile-gate auth">
      <header className="profiles__top auth__top">
        <img src="/logo/navbar-logo.svg" alt="Taurus" className="profiles__logo" width="927" height="108" />
        {/* signed out: no profile language yet, so the language can be picked here */}
        <LanguagePicker compact className="auth__language" />
      </header>
      <main className="profiles__main profiles__main--form auth__main">
        <div className="profiles__intro">
          {step ? <p className="profiles__step">{step}</p> : null}
          <h1 className="profiles__title">{title}</h1>
          {subtitle ? <p className="profiles__subtitle">{subtitle}</p> : null}
        </div>
        <div className="profiles__card auth__card">{children}</div>
        {footer ? <p className="auth__footer">{footer}</p> : null}
      </main>
    </div>
  );
}

/** A form-level message (wrong password, server down...) at the top of the card. */
export function AuthAlert({ tone = 'error', children }) {
  if (!children) return null;
  return (
    <p className={`auth__alert auth__alert--${tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      {children}
    </p>
  );
}

export function PasswordField({ label, value, onChange, autoComplete, hint, error, ok, ...rest }) {
  const { t } = useTranslation('auth');
  const id = useId();
  const [shown, setShown] = useState(false);
  return (
    <div className={`ui-field${error ? ' has-error' : ''}`}>
      <label className="ui-field__label" htmlFor={id}>
        {label}
      </label>
      <div className="auth__password">
        <input
          id={id}
          className="ui-input"
          type={shown ? 'text' : 'password'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          autoComplete={autoComplete}
          autoCapitalize="off"
          spellCheck={false}
          {...rest}
        />
        <button
          type="button"
          className="auth__reveal"
          onClick={() => setShown((s) => !s)}
          aria-label={shown ? t('password.hide') : t('password.show')}
          aria-pressed={shown}
        >
          {shown ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </div>
      {error ? (
        <p className="ui-field__error" role="alert">
          {error}
        </p>
      ) : ok ? (
        <p className="ui-field__hint auth__ok">{ok}</p>
      ) : hint ? (
        <p className="ui-field__hint">{hint}</p>
      ) : null}
    </div>
  );
}

// The server's rules (Django's AUTH_PASSWORD_VALIDATORS): checked here first so the user sees
// them while typing; the server still decides (too common / too close to the email).
export const passwordHint = () => i18n.t('auth:password.hint', { count: 8 });
export function passwordProblem(pw) {
  if (pw.length < 8) return i18n.t('auth:password.tooShort', { count: 8 });
  if (/^\d+$/.test(pw)) return i18n.t('auth:password.onlyNumbers');
  return null;
}

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

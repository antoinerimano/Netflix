// src/components/AccountManagement.js
// Account page: account (name, email, password), profiles, sign out. (Plan / payment history
// were removed: the subscription API stays for a possible return.)
// Settings-style rows with one action each; changes happen in dialogs (design Modal) and are
// confirmed with a toast. Profiles use the same editor as "Who's watching?".
import React, { useCallback, useContext, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Trans, useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES, normalizeLanguage } from '../i18n';
import { useFormat } from '../i18n/format';
import { fetchAccount, requestPasswordReset, requestEmailChange } from '../api/userApi';
import Navbar from './Navbar';
import Footer from './Footer';
import { AuthContext } from './AuthContext';
import { Avatar, Button, EmptyState, Field, Modal, SectionTitle, Skeleton, Toast, friendlyError } from '../design';
import { ChevronRightIcon, PlusIcon } from '../design/icons';
import ProfileEditor from './profiles/ProfileEditor';
import { ageSummary } from './profiles/ProfileForm';
import { MAX_PROFILES } from '../utils/activeProfile';
import './AccountManagement.css';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const asList = (x) => (Array.isArray(x) ? x : x?.results ?? []);
function Row({ label, value, children }) {
  return (
    <div className="account-row">
      <div className="account-row__text">
        <span className="account-row__label">{label}</span>
        <span className="account-row__value">{value}</span>
      </div>
      {children ? <div className="account-row__action">{children}</div> : null}
    </div>
  );
}

export default function AccountManagement() {
  const { t } = useTranslation('account');
  const { formatDate } = useFormat();
  const { userId } = useParams();
  const navigate = useNavigate();
  const { logout } = useContext(AuthContext);
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState({ message: '', tone: 'success' });
  const clearToast = useCallback(() => setToast({ message: '', tone: 'success' }), []);

  const [dialog, setDialog] = useState(null); // 'email' | 'password' | 'signout' | null
  const [newEmail, setNewEmail] = useState('');
  const [emailError, setEmailError] = useState('');
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(null); // profile | 'new' | null

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await fetchAccount(userId);
      setUser({ ...data, profiles: asList(data.profiles) });
    } catch (e) {
      setError(e);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    const storedUserId = localStorage.getItem('userId');
    if (!storedUserId) {
      navigate('/login');
      return;
    }
    if (storedUserId !== userId) {
      setError({ status: 403 });
      setLoading(false);
      return;
    }
    load();
  }, [userId, load, navigate]);

  // an email change refused on the confirmation page comes back here
  useEffect(() => {
    const stored = localStorage.getItem('emailChangeError');
    if (stored) {
      localStorage.removeItem('emailChangeError');
      setToast({ message: stored, tone: 'error' });
    }
  }, []);

  const openEmail = () => {
    setNewEmail('');
    setEmailError('');
    setDialog('email');
  };
  const sendEmailChange = async (e) => {
    e?.preventDefault();
    const email = newEmail.trim();
    if (!EMAIL_RE.test(email)) {
      setEmailError(t('email.invalid'));
      return;
    }
    if (email.toLowerCase() === String(user.email).toLowerCase()) {
      setEmailError(t('email.same'));
      return;
    }
    setBusy(true);
    const result = await requestEmailChange(userId, email);
    setBusy(false);
    if (result?.error) {
      setEmailError(result.error);
      return;
    }
    setDialog(null);
    setToast({ message: t('email.sent', { email }), tone: 'success' });
  };

  const sendPasswordReset = async () => {
    setBusy(true);
    try {
      await requestPasswordReset(user.email);
      setDialog(null);
      setToast({ message: t('password.sent', { email: user.email }), tone: 'success' });
    } catch {
      setToast({ message: t('password.failed'), tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const signOut = () => {
    logout();
    localStorage.removeItem('userId');
    localStorage.removeItem('activeProfileId');
    navigate('/login');
  };

  const onProfileEdited = async ({ type, profile }) => {
    setEditing(null);
    await load();
    setToast({ message: t(`profiles:toast.${type}`, { name: profile.name }), tone: 'success' });
  };

  let content;
  if (loading) {
    content = (
      <div className="account" aria-busy="true">
        <Skeleton variant="text" width="10rem" height="2.4rem" />
        {[0, 1].map((i) => (
          <div key={i} className="account-card">
            <Skeleton variant="text" width="8rem" />
            <Skeleton height="3rem" />
            <Skeleton height="3rem" />
          </div>
        ))}
      </div>
    );
  } else if (error || !user) {
    content = (
      <EmptyState
        page
        tone="error"
        title={error?.status === 403 ? t('notYours') : t('loadError')}
        actions={
          error?.status === 403 ? (
            <Button variant="primary" to="/">{t('actions.goHome')}</Button>
          ) : (
            <Button variant="primary" onClick={load}>{t('actions.tryAgain')}</Button>
          )
        }
      >
        {error?.status === 403 ? t('notYoursText') : friendlyError(error, 'account')}
      </EmptyState>
    );
  } else {
    const profiles = user.profiles;
    content = (
      <div className="account">
        <header className="account__head">
          <h1 className="account__title">{t('title')}</h1>
          {user.created_at ? <p className="account__since">{t('memberSince', { date: formatDate(user.created_at, { dateStyle: 'long' }) })}</p> : null}
        </header>

        <section className="account-card" aria-labelledby="account-details">
          <SectionTitle as="h2" id="account-details">{t('title')}</SectionTitle>
          <Row label={t('auth:fields.name')} value={user.name} />
          <Row label={t('auth:fields.email')} value={user.email}>
            <Button variant="glass" size="sm" onClick={openEmail}>
              {t('change')}
            </Button>
          </Row>
          <Row label={t('auth:fields.password')} value="••••••••">
            <Button variant="glass" size="sm" onClick={() => setDialog('password')}>
              {t('change')}
            </Button>
          </Row>
        </section>

        <section className="account-card" aria-labelledby="account-profiles">
          <div className="account-card__head">
            <SectionTitle as="h2" id="account-profiles">{t('profiles.title')}</SectionTitle>
            <span className="account-card__count">
              {t('profiles.count', { count: profiles.length, max: MAX_PROFILES })}
            </span>
          </div>
          <ul className="account-profiles">
            {profiles.map((p) => (
              <li key={p.id}>
                <button type="button" className="account-profile" onClick={() => setEditing(p)} aria-label={t('profiles:manage.edit', { name: p.name })}>
                  <Avatar src={p.avatar_url} name={p.name} size="3rem" />
                  <span className="account-profile__text">
                    <span className="account-profile__name">{p.name}</span>
                    <span className="account-profile__meta">
                      {ageSummary(p)} · {SUPPORTED_LANGUAGES[normalizeLanguage(p.language_preference) || 'en']}
                    </span>
                  </span>
                  <span className="account-profile__edit" aria-hidden="true">
                    {t('profiles.edit')}
                    <ChevronRightIcon />
                  </span>
                </button>
              </li>
            ))}
            {profiles.length < MAX_PROFILES ? (
              <li>
                <button type="button" className="account-profile account-profile--add" onClick={() => setEditing('new')}>
                  <span className="account-profile__plus" aria-hidden="true">
                    <PlusIcon />
                  </span>
                  <span className="account-profile__text">
                    <span className="account-profile__name">{t('profiles:add.submit')}</span>
                    <span className="account-profile__meta">{t('profiles.addHint', { count: MAX_PROFILES })}</span>
                  </span>
                </button>
              </li>
            ) : null}
          </ul>
        </section>

        <section className="account-card account-card--quiet">
          <Row label={t('signOut.label')} value={t('signOut.signedInAs', { email: user.email })}>
            <Button variant="danger" size="sm" onClick={() => setDialog('signout')}>
              {t('signOut.label')}
            </Button>
          </Row>
        </section>
      </div>
    );
  }

  return (
    <div className="account-page">
      <Navbar />
      <main>{content}</main>
      <Footer />

      <Modal
        open={dialog === 'email'}
        onClose={() => setDialog(null)}
        title={t('email.title')}
        size="sm"
        scrollable={false}
        initialFocus="#account-new-email"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>
              {t('actions.cancel')}
            </Button>
            <Button variant="primary" loading={busy} onClick={sendEmailChange}>
              {t('email.send')}
            </Button>
          </>
        }
      >
        <form className="account-dialog" onSubmit={sendEmailChange} noValidate>
          <p className="account-dialog__text">
            {t('email.intro')}
          </p>
          <Field label={t('email.current')}>
            <p className="account-dialog__current">{user?.email}</p>
          </Field>
          <Field label={t('email.new')} htmlFor="account-new-email" error={emailError}>
            <input
              id="account-new-email"
              className="ui-input"
              type="email"
              autoComplete="email"
              value={newEmail}
              placeholder={t('email.placeholder')}
              onChange={(e) => {
                setNewEmail(e.target.value);
                setEmailError('');
              }}
            />
          </Field>
        </form>
      </Modal>

      <Modal
        open={dialog === 'password'}
        onClose={() => setDialog(null)}
        title={t('password.title')}
        size="sm"
        scrollable={false}
        initialFocus=".ui-modal__footer .ui-btn--primary"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>
              {t('actions.cancel')}
            </Button>
            <Button variant="primary" loading={busy} onClick={sendPasswordReset}>
              {t('password.send')}
            </Button>
          </>
        }
      >
        <p className="account-dialog__text">
          <Trans t={t} i18nKey="password.intro" values={{ email: user?.email }} components={{ strong: <strong /> }} />
        </p>
      </Modal>

      <Modal
        open={dialog === 'signout'}
        onClose={() => setDialog(null)}
        title={t('signOut.title')}
        size="sm"
        scrollable={false}
        initialFocus=".ui-modal__footer .ui-btn--ghost"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)}>
              {t('signOut.stay')}
            </Button>
            <Button variant="danger" onClick={signOut}>
              {t('signOut.label')}
            </Button>
          </>
        }
      >
        <p className="account-dialog__text">{t('signOut.text')}</p>
      </Modal>

      <ProfileEditor
        editing={editing}
        canDelete={(user?.profiles?.length || 0) > 1}
        onClose={() => setEditing(null)}
        onDone={onProfileEdited}
      />

      <Toast message={toast.message} tone={toast.tone} onDone={clearToast} />
    </div>
  );
}

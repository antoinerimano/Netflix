// src/components/appearance/AppearancePage.jsx
// "Appearance" (/appearance, from the profile menu and the account page): the active profile
// picks its fonts, accent color and background (presets in design/theme.js). Every choice shows
// at once on the whole site (live preview), and is saved on the profile a moment later, so it
// follows the profile on every device. "Back to default" undoes it all.
// TV remote: each group is a row of buttons (Left / Right inside, Up / Down between groups),
// OK picks one; the focus stays on it.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { patchProfile } from '../../api/userApi';
import { Button, SectionTitle, Toast } from '../../design';
import { CheckIcon } from '../../design/icons';
import {
  ACCENTS,
  APPEARANCE_EVENT,
  BACKGROUNDS,
  DEFAULT_APPEARANCE,
  FONTS,
  fontStacks,
  loadFont,
  normalizeAppearance,
  setAppearance,
  storedAppearance,
  toProfileValue,
} from '../../design/theme';
import '../AccountManagement.css';
import './appearance.css';

function readProfile() {
  try {
    return JSON.parse(localStorage.getItem('activeProfile') || 'null');
  } catch {
    return null;
  }
}

const SAVE_DELAY = 600; // ms: several quick choices = one save

/** A row of choices: role radiogroup, each option a button (OK on a remote, a click, a tap). */
function Choices({ label, className, children }) {
  return (
    <div role="radiogroup" aria-label={label} className={`appearance-choices ${className || ''}`}>
      {children}
    </div>
  );
}

function Choice({ checked, onPick, label, className, style, children }) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={checked}
      aria-label={label}
      className={`appearance-choice ${className || ''}${checked ? ' is-checked' : ''}`}
      style={style}
      onClick={onPick}
    >
      {children}
      {checked ? <CheckIcon className="appearance-choice__check" aria-hidden="true" /> : null}
    </button>
  );
}

export default function AppearancePage() {
  const { t } = useTranslation('account');
  const navigate = useNavigate();
  const [profile] = useState(readProfile);
  const userId = localStorage.getItem('userId');
  // what is on screen (the profile's copy kept in this browser can be older: the look saved on
  // another device is applied when the app starts, and the page showed the default meanwhile)
  const [look, setLook] = useState(storedAppearance);
  useEffect(() => {
    const onChange = (e) => setLook(normalizeAppearance(e.detail));
    window.addEventListener(APPEARANCE_EVENT, onChange);
    return () => window.removeEventListener(APPEARANCE_EVENT, onChange);
  }, []);
  const [status, setStatus] = useState(''); // '' | 'saving' | 'saved'
  const [toast, setToast] = useState({ message: '', tone: 'success' });
  const clearToast = useCallback(() => setToast({ message: '', tone: 'success' }), []);
  const timer = useRef(null);
  const pending = useRef(null);

  useEffect(() => {
    if (!profile?.id) navigate('/profiles', { replace: true });
  }, [profile, navigate]);

  // every pair's fonts, so each choice is drawn in its own letters
  useEffect(() => {
    FONTS.forEach((f) => loadFont(f.id));
  }, []);

  const save = useCallback(async () => {
    const value = pending.current;
    pending.current = null;
    if (!value || !profile?.id || !userId) return;
    try {
      const updated = await patchProfile(userId, profile.id, { appearance: value });
      // the copy the app keeps of the profile (profile switch, next start)
      const current = readProfile();
      if (current && String(current.id) === String(profile.id)) {
        localStorage.setItem('activeProfile', JSON.stringify({ ...current, appearance: updated?.appearance ?? value }));
      }
      setStatus('saved');
    } catch {
      setStatus('');
      setToast({ message: t('appearance.saveFailed'), tone: 'error' });
    }
  }, [profile, userId, t]);

  // leaving the page saves what is waiting
  useEffect(
    () => () => {
      if (timer.current) {
        clearTimeout(timer.current);
        save();
      }
    },
    [save]
  );

  const commit = (wanted) => {
    const next = setAppearance(wanted); // live: the whole site changes now
    setLook(next);
    pending.current = toProfileValue(next);
    setStatus('saving');
    clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      timer.current = null;
      save();
    }, SAVE_DELAY);
  };
  const pick = (part, id) => commit({ ...look, [part]: id });
  const reset = () => commit(DEFAULT_APPEARANCE);

  const isDefault = Object.keys(DEFAULT_APPEARANCE).every((k) => look[k] === DEFAULT_APPEARANCE[k]);

  return (
    <div className="account-page">
      <Navbar />
      <main className="account appearance">
        <header className="account__head">
          <h1 className="account__title">{t('appearance.title')}</h1>
          <p className="account__since">{t('appearance.intro', { name: profile?.name || '' })}</p>
        </header>

        {/* live preview: drawn with the tokens, so it is always the current look */}
        <section className="appearance-preview" aria-label={t('appearance.preview')}>
          <div className="appearance-preview__art" aria-hidden="true" />
          <div className="appearance-preview__body">
            <span className="appearance-preview__eyebrow">{t('appearance.previewEyebrow')}</span>
            <h2 className="appearance-preview__title">{t('appearance.previewTitle')}</h2>
            <p className="appearance-preview__text">{t('appearance.previewText')}</p>
            <div className="appearance-preview__bar" aria-hidden="true">
              <span style={{ width: '62%' }} />
            </div>
            <div className="appearance-preview__actions" aria-hidden="true">
              <span className="appearance-preview__btn appearance-preview__btn--primary">▶ {t('appearance.previewPlay')}</span>
              <span className="appearance-preview__btn">+ {t('appearance.previewList')}</span>
            </div>
          </div>
        </section>

        <section className="account-card" aria-labelledby="appearance-fonts">
          <SectionTitle as="h2" id="appearance-fonts">{t('appearance.fonts')}</SectionTitle>
          <Choices label={t('appearance.fonts')} className="appearance-choices--fonts">
            {FONTS.map((f) => {
              const [display, text] = fontStacks(f.id);
              const name = t(`appearance.font.${f.id}`);
              const detail = f.text ? (f.text === f.display ? f.text : `${f.display} + ${f.text}`) : t('appearance.systemFont');
              return (
                <Choice
                  key={f.id}
                  checked={look.font === f.id}
                  onPick={() => pick('font', f.id)}
                  label={`${name}, ${detail}`}
                  className="appearance-font"
                >
                  <span className="appearance-font__sample" style={{ fontFamily: display }}>Aa</span>
                  <span className="appearance-font__name" style={{ fontFamily: display }}>{name}</span>
                  <span className="appearance-font__detail" style={{ fontFamily: text }}>{detail}</span>
                </Choice>
              );
            })}
          </Choices>
        </section>

        <section className="account-card" aria-labelledby="appearance-accent">
          <SectionTitle as="h2" id="appearance-accent">{t('appearance.accent')}</SectionTitle>
          <Choices label={t('appearance.accent')} className="appearance-choices--swatches">
            {ACCENTS.map((c) => (
              <Choice
                key={c.id}
                checked={look.accent === c.id}
                onPick={() => pick('accent', c.id)}
                label={t(`appearance.color.${c.id}`)}
                className="appearance-swatch"
              >
                <span className="appearance-swatch__dot" style={{ background: c.brand }} aria-hidden="true" />
                <span className="appearance-swatch__name">{t(`appearance.color.${c.id}`)}</span>
              </Choice>
            ))}
          </Choices>
        </section>

        <section className="account-card" aria-labelledby="appearance-background">
          <SectionTitle as="h2" id="appearance-background">{t('appearance.background')}</SectionTitle>
          <Choices label={t('appearance.background')} className="appearance-choices--swatches">
            {BACKGROUNDS.map((b) => (
              <Choice
                key={b.id}
                checked={look.background === b.id}
                onPick={() => pick('background', b.id)}
                label={t(`appearance.bg.${b.id}`)}
                className="appearance-swatch"
              >
                <span
                  className="appearance-swatch__dot appearance-swatch__dot--bg"
                  style={{ background: `linear-gradient(135deg, ${b.s2} 0 50%, ${b.bg} 50% 100%)` }}
                  aria-hidden="true"
                />
                <span className="appearance-swatch__name">{t(`appearance.bg.${b.id}`)}</span>
              </Choice>
            ))}
          </Choices>
        </section>

        <div className="appearance-footer">
          {/* never disabled: a remote would lose the focus when it turns off under it */}
          <Button variant="glass" onClick={reset} aria-disabled={isDefault || undefined}>
            {t('appearance.reset')}
          </Button>
          <span className="appearance-status" role="status" aria-live="polite">
            {status === 'saving' ? t('appearance.saving') : status === 'saved' ? t('appearance.saved') : ''}
          </span>
        </div>
      </main>
      <Footer />
      <Toast message={toast.message} tone={toast.tone} onDone={clearToast} />
    </div>
  );
}

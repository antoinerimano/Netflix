// src/components/profiles/ProfileForm.js
// Create / edit a profile: preview + name, picture (your own avatar, a letter in a color, or a
// photo), Kids switch, age limit, language. Used by "Who's watching?", the sign-up step and the
// account page. Backend rules for the age limit: users/maturity.py (Kids never above PG).
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import i18n, { currentLanguage, normalizeLanguage, SUPPORTED_LANGUAGES } from '../../i18n';
import { Avatar, Button, Chip, Field, Switch } from '../../design';
import AvatarBuilder from './AvatarBuilder';
import { isBuiltAvatar } from '../../design/avatarArt';
import { WandIcon, CheckIcon } from '../../design/icons';
import './profiles.css';

const PHOTOS = ['/avatars/male.webp', '/avatars/female.webp', '/avatars/kid.webp'];
const LETTER_COLORS = ['#e50914', '#f5a524', '#2bb673', '#1f8bff', '#8b5cf6', '#ec4899', '#14b8a6', '#3a3a44'];
const isLetter = (src) => typeof src === 'string' && src.startsWith('color:');

// labels: profiles:age.<key> (translated when shown)
const AGE_LIMITS = [
  { value: 'G', key: 'all', hint: 'G' },
  { value: 'PG', key: '7', hint: 'PG' },
  { value: 'PG-13', key: '13', hint: 'PG-13' },
  { value: 'R', key: '16', hint: 'R' },
  { value: 'NC-17', key: 'none', hint: null },
];
const KIDS_LIMITS = ['G', 'PG'];
const ageLabel = (a) => i18n.t(`profiles:age.${a.key}`);

export const EMPTY_PROFILE = {
  name: '',
  avatar_url: `color:${LETTER_COLORS[0]}`,
  is_kids: false,
  age_restriction: 'NC-17',
  language_preference: '', // '' = the language the app is in when the form opens
};

/** "Kids · All ages", "13+", "No limit": a profile's limit in a few words */
export function ageSummary(profile) {
  const opt = AGE_LIMITS.find((a) => a.value === profile?.age_restriction) || AGE_LIMITS[AGE_LIMITS.length - 1];
  const label = profile?.is_kids && !KIDS_LIMITS.includes(opt.value) ? ageLabel(AGE_LIMITS[0]) : ageLabel(opt);
  return profile?.is_kids ? i18n.t('profiles:age.kidsSummary', { limit: label }) : label;
}

/**
 * initial: profile to edit (or EMPTY_PROFILE); onSubmit(values) -> Promise; onCancel optional;
 * extraActions: node shown left of the buttons (e.g. Delete).
 */
export default function ProfileForm({ initial = EMPTY_PROFILE, submitLabel, onSubmit, onCancel, extraActions }) {
  const { t } = useTranslation('profiles');
  const [values, setValues] = useState(() => {
    const v = { ...EMPTY_PROFILE, ...initial };
    // old codes ("jp") and empty -> a supported language
    return { ...v, language_preference: normalizeLanguage(v.language_preference) || currentLanguage() };
  });
  const [error, setError] = useState('');
  const [nameError, setNameError] = useState('');
  const [saving, setSaving] = useState(false);
  const [builderOpen, setBuilderOpen] = useState(false);
  // the last avatar / letter color used in this form: switching to a photo and back keeps them
  const [ownAvatar, setOwnAvatar] = useState(isBuiltAvatar(initial?.avatar_url) ? initial.avatar_url : '');
  const [letterColor, setLetterColor] = useState(isLetter(initial?.avatar_url) ? initial.avatar_url : `color:${LETTER_COLORS[0]}`);

  const set = (patch) => setValues((v) => ({ ...v, ...patch }));
  const pic = values.avatar_url || '';
  const limits = values.is_kids ? AGE_LIMITS.filter((a) => KIDS_LIMITS.includes(a.value)) : AGE_LIMITS;
  const age = values.is_kids && !KIDS_LIMITS.includes(values.age_restriction) ? 'G' : values.age_restriction;

  const submit = async (e) => {
    e.preventDefault();
    const name = values.name.trim();
    if (!name) {
      setNameError(t('form.nameRequired'));
      document.getElementById('profile-name')?.focus();
      return;
    }
    setNameError('');
    setError('');
    setSaving(true);
    try {
      await onSubmit({ ...values, name, age_restriction: age });
    } catch (err) {
      setError(err?.response?.data?.error || err?.message || t('form.saveFailed'));
    }
    setSaving(false);
  };

  return (
    <form className="profile-form" onSubmit={submit} noValidate>
      <div className="profile-form__identity">
        <div className="profile-form__preview" aria-hidden="true">
          <Avatar src={pic} name={values.name} size="100%" />
        </div>
        <Field label={t('form.name')} htmlFor="profile-name" error={nameError} className="profile-form__name">
          <input
            id="profile-name"
            className="ui-input"
            data-tv-start=""
            value={values.name}
            maxLength={30}
            autoComplete="off"
            placeholder={t('form.namePlaceholder')}
            onChange={(e) => set({ name: e.target.value })}
          />
        </Field>
      </div>

      <Field label={t('form.picture')}>
        <div className="profile-form__pictures" role="radiogroup" aria-label={t('form.pictureGroup')}>
          {/* your own character: create it, or edit the one you made */}
          {ownAvatar ? (
            <button
              type="button"
              role="radio"
              aria-checked={pic === ownAvatar}
              aria-label={pic === ownAvatar ? t('form.ownAvatarEdit') : t('form.ownAvatar')}
              className={`profile-form__pic profile-form__pic--own${pic === ownAvatar ? ' is-selected' : ''}`}
              onClick={() => (pic === ownAvatar ? setBuilderOpen(true) : set({ avatar_url: ownAvatar }))}
            >
              <Avatar src={ownAvatar} name={values.name} size="100%" />
              <span className="profile-form__pic-badge" aria-hidden="true">
                <WandIcon />
              </span>
            </button>
          ) : (
            <button
              type="button"
              className="profile-form__pic profile-form__pic--create"
              aria-label={t('form.createAvatar')}
              onClick={() => setBuilderOpen(true)}
            >
              <WandIcon />
              <span>{t('form.create')}</span>
            </button>
          )}

          {/* a letter: one tile, its colors below when chosen */}
          <button
            type="button"
            role="radio"
            aria-checked={isLetter(pic)}
            aria-label={t('form.letter')}
            className={`profile-form__pic${isLetter(pic) ? ' is-selected' : ''}`}
            onClick={() => set({ avatar_url: letterColor })}
          >
            <Avatar src={isLetter(pic) ? pic : letterColor} name={values.name || 'A'} size="100%" />
          </button>

          {PHOTOS.map((src, i) => (
            <button
              key={src}
              type="button"
              role="radio"
              aria-checked={pic === src}
              aria-label={t('form.photo', { number: i + 1 })}
              className={`profile-form__pic${pic === src ? ' is-selected' : ''}`}
              onClick={() => set({ avatar_url: src })}
            >
              <Avatar src={src} name={values.name} size="100%" />
            </button>
          ))}
        </div>

        {isLetter(pic) ? (
          <div className="ui-scroller profile-form__letter-colors" role="radiogroup" aria-label={t('form.letterColor')}>
            {LETTER_COLORS.map((c) => {
              const code = `color:${c}`;
              const selected = pic === code;
              return (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  aria-label={t('form.color', { color: c })}
                  className={`profile-form__color${selected ? ' is-selected' : ''}`}
                  style={{ background: c }}
                  onClick={() => {
                    setLetterColor(code);
                    set({ avatar_url: code });
                  }}
                >
                  {selected ? <CheckIcon aria-hidden="true" /> : null}
                </button>
              );
            })}
          </div>
        ) : null}
      </Field>

      <AvatarBuilder
        open={builderOpen}
        initial={ownAvatar}
        onCancel={() => setBuilderOpen(false)}
        onDone={(code) => {
          setOwnAvatar(code);
          set({ avatar_url: code });
          setBuilderOpen(false);
          // the "Create" tile became "your avatar": keep the focus there (TV remote / keyboard)
          setTimeout(() => document.querySelector('.profile-form__pic--own')?.focus({ preventScroll: true }), 60);
        }}
      />

      <Switch
        checked={!!values.is_kids}
        label={t('form.kids')}
        description={t('form.kidsHint')}
        onChange={(on) =>
          set({ is_kids: on, age_restriction: on && !KIDS_LIMITS.includes(values.age_restriction) ? 'G' : values.age_restriction })
        }
      />

      <Field label={t('form.ageLimit')} hint={values.is_kids ? t('form.ageLimitKidsHint') : t('form.ageLimitHint')}>
        <div className="profile-form__chips" role="radiogroup" aria-label={t('form.ageLimit')}>
          {limits.map((a) => (
            <Chip key={a.value} role="radio" aria-checked={age === a.value} selected={age === a.value} onClick={() => set({ age_restriction: a.value })} title={a.hint || t('age.everything')}>
              {ageLabel(a)}
            </Chip>
          ))}
        </div>
      </Field>

      <Field label={t('form.language')} htmlFor="profile-language" hint={t('form.languageHint')}>
        <select
          id="profile-language"
          className="ui-select"
          value={values.language_preference}
          onChange={(e) => set({ language_preference: e.target.value })}
        >
          {Object.entries(SUPPORTED_LANGUAGES).map(([code, name]) => (
            <option key={code} value={code} lang={code}>
              {name}
            </option>
          ))}
        </select>
      </Field>

      {error ? (
        <p className="profile-form__error" role="alert">
          {error}
        </p>
      ) : null}

      <div className="profile-form__actions">
        {extraActions ? <div className="profile-form__extra">{extraActions}</div> : null}
        {onCancel ? (
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            {t('actions.cancel')}
          </Button>
        ) : null}
        <Button variant="primary" type="submit" loading={saving}>
          {submitLabel || t('actions.save')}
        </Button>
      </div>
    </form>
  );
}

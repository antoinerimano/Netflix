// src/components/profiles/ProfileForm.js
// Create / edit a profile: preview + name, picture (your own avatar, a letter in a color, or a
// photo), Kids switch, age limit, language. Used by "Who's watching?", the sign-up step and the
// account page. Backend rules for the age limit: users/maturity.py (Kids never above PG).
import React, { useState } from 'react';
import { Avatar, Button, Chip, Field, Switch } from '../../design';
import AvatarBuilder from './AvatarBuilder';
import { isBuiltAvatar } from '../../design/avatarArt';
import { WandIcon, CheckIcon } from '../../design/icons';
import './profiles.css';

const PHOTOS = ['/avatars/male.webp', '/avatars/female.webp', '/avatars/kid.webp'];
const LETTER_COLORS = ['#e50914', '#f5a524', '#2bb673', '#1f8bff', '#8b5cf6', '#ec4899', '#14b8a6', '#3a3a44'];
const isLetter = (src) => typeof src === 'string' && src.startsWith('color:');

const AGE_LIMITS = [
  { value: 'G', label: 'All ages', hint: 'G' },
  { value: 'PG', label: '7+', hint: 'PG' },
  { value: 'PG-13', label: '13+', hint: 'PG-13' },
  { value: 'R', label: '16+', hint: 'R' },
  { value: 'NC-17', label: 'No limit', hint: 'Everything' },
];
const KIDS_LIMITS = ['G', 'PG'];
const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'fr', label: 'Français' },
  { value: 'es', label: 'Español' },
  { value: 'de', label: 'Deutsch' },
  { value: 'zh', label: '中文' },
];

export const EMPTY_PROFILE = {
  name: '',
  avatar_url: `color:${LETTER_COLORS[0]}`,
  is_kids: false,
  age_restriction: 'NC-17',
  language_preference: 'en',
};

/** "Kids · All ages", "13+", "No limit": a profile's limit in a few words */
export function ageSummary(profile) {
  const opt = AGE_LIMITS.find((a) => a.value === profile?.age_restriction) || AGE_LIMITS[AGE_LIMITS.length - 1];
  const label = profile?.is_kids && !KIDS_LIMITS.includes(opt.value) ? 'All ages' : opt.label;
  return profile?.is_kids ? `Kids · ${label}` : label;
}

/**
 * initial: profile to edit (or EMPTY_PROFILE); onSubmit(values) -> Promise; onCancel optional;
 * extraActions: node shown left of the buttons (e.g. Delete).
 */
export default function ProfileForm({ initial = EMPTY_PROFILE, submitLabel = 'Save', onSubmit, onCancel, extraActions }) {
  const [values, setValues] = useState({ ...EMPTY_PROFILE, ...initial });
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
      setNameError('Give the profile a name.');
      document.getElementById('profile-name')?.focus();
      return;
    }
    setNameError('');
    setError('');
    setSaving(true);
    try {
      await onSubmit({ ...values, name, age_restriction: age });
    } catch (err) {
      setError(err?.message || 'Could not save the profile. Please try again.');
    }
    setSaving(false);
  };

  return (
    <form className="profile-form" onSubmit={submit} noValidate>
      <div className="profile-form__identity">
        <div className="profile-form__preview" aria-hidden="true">
          <Avatar src={pic} name={values.name} size="100%" />
        </div>
        <Field label="Name" htmlFor="profile-name" error={nameError} className="profile-form__name">
          <input
            id="profile-name"
            className="ui-input"
            data-tv-start=""
            value={values.name}
            maxLength={30}
            autoComplete="off"
            placeholder="e.g. Sam"
            onChange={(e) => set({ name: e.target.value })}
          />
        </Field>
      </div>

      <Field label="Picture">
        <div className="profile-form__pictures" role="radiogroup" aria-label="Profile picture">
          {/* your own character: create it, or edit the one you made */}
          {ownAvatar ? (
            <button
              type="button"
              role="radio"
              aria-checked={pic === ownAvatar}
              aria-label={pic === ownAvatar ? 'Your avatar: edit it' : 'Your avatar'}
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
              aria-label="Create your own avatar"
              onClick={() => setBuilderOpen(true)}
            >
              <WandIcon />
              <span>Create</span>
            </button>
          )}

          {/* a letter: one tile, its colors below when chosen */}
          <button
            type="button"
            role="radio"
            aria-checked={isLetter(pic)}
            aria-label="Letter"
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
              aria-label={`Picture ${i + 1}`}
              className={`profile-form__pic${pic === src ? ' is-selected' : ''}`}
              onClick={() => set({ avatar_url: src })}
            >
              <Avatar src={src} name={values.name} size="100%" />
            </button>
          ))}
        </div>

        {isLetter(pic) ? (
          <div className="ui-scroller profile-form__letter-colors" role="radiogroup" aria-label="Letter color">
            {LETTER_COLORS.map((c) => {
              const code = `color:${c}`;
              const selected = pic === code;
              return (
                <button
                  key={c}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  aria-label={`Color ${c}`}
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
        label="Kids profile"
        description="Only titles rated for children, a simpler home page."
        onChange={(on) =>
          set({ is_kids: on, age_restriction: on && !KIDS_LIMITS.includes(values.age_restriction) ? 'G' : values.age_restriction })
        }
      />

      <Field label="Age limit" hint={values.is_kids ? 'Kids profiles go up to 7+ (PG).' : 'Titles rated above this are hidden.'}>
        <div className="profile-form__chips" role="radiogroup" aria-label="Age limit">
          {limits.map((a) => (
            <Chip key={a.value} role="radio" aria-checked={age === a.value} selected={age === a.value} onClick={() => set({ age_restriction: a.value })} title={a.hint}>
              {a.label}
            </Chip>
          ))}
        </div>
      </Field>

      <Field label="Language" htmlFor="profile-language">
        <select
          id="profile-language"
          className="ui-select"
          value={values.language_preference || 'en'}
          onChange={(e) => set({ language_preference: e.target.value })}
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
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
            Cancel
          </Button>
        ) : null}
        <Button variant="primary" type="submit" loading={saving}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

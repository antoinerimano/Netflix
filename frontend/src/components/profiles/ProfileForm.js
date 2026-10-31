// src/components/profiles/ProfileForm.js
// Create / edit a profile: name, picture (photos or a colored initial), Kids switch, age limit,
// language. Used by the "Who's watching?" page, the sign-up flow and the account page.
// Backend rules for the age limit: users/maturity.py (a Kids profile never goes above PG).
import React, { useState } from 'react';
import { Avatar, Button, Chip, Field, Switch } from '../../design';
import AvatarBuilder from './AvatarBuilder';
import { isBuiltAvatar } from '../../design/avatarArt';
import { WandIcon } from '../../design/icons';
import './profiles.css';

export const AVATARS = [
  '/avatars/male.webp',
  '/avatars/female.webp',
  '/avatars/kid.webp',
  'color:#e50914',
  'color:#f5a524',
  'color:#2bb673',
  'color:#1f8bff',
  'color:#8b5cf6',
  'color:#ec4899',
  'color:#14b8a6',
];
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
  avatar_url: AVATARS[3],
  is_kids: false,
  age_restriction: 'NC-17',
  language_preference: 'en',
};

/**
 * initial: profile to edit (or EMPTY_PROFILE); onSubmit(values) -> Promise; onCancel optional;
 * extraActions: node shown left of the buttons (e.g. Delete).
 */
export default function ProfileForm({ initial = EMPTY_PROFILE, submitLabel = 'Save', onSubmit, onCancel, extraActions, autoFocusName = true }) {
  const [values, setValues] = useState({ ...EMPTY_PROFILE, ...initial });
  const [error, setError] = useState('');
  const [nameError, setNameError] = useState('');
  const [saving, setSaving] = useState(false);
  const [builderOpen, setBuilderOpen] = useState(false);
  const builtAvatar = isBuiltAvatar(values.avatar_url) ? values.avatar_url : '';

  const set = (patch) => setValues((v) => ({ ...v, ...patch }));
  const limits = values.is_kids ? AGE_LIMITS.filter((a) => KIDS_LIMITS.includes(a.value)) : AGE_LIMITS;
  const age = values.is_kids && !KIDS_LIMITS.includes(values.age_restriction) ? 'G' : values.age_restriction;

  const submit = async (e) => {
    e.preventDefault();
    const name = values.name.trim();
    if (!name) {
      setNameError('Give the profile a name.');
      return;
    }
    setNameError('');
    setError('');
    setSaving(true);
    try {
      await onSubmit({ ...values, name, age_restriction: age });
    } catch (err) {
      setError(err?.message || 'Could not save the profile. Please try again.');
      setSaving(false);
      return;
    }
    setSaving(false);
  };

  return (
    <form className="profile-form" onSubmit={submit} noValidate>
      <div className="profile-form__preview" aria-hidden="true">
        <Avatar src={values.avatar_url} name={values.name} size="5.5rem" />
      </div>

      <Field label="Name" htmlFor="profile-name" error={nameError}>
        <input
          id="profile-name"
          className="ui-input"
          value={values.name}
          maxLength={30}
          autoComplete="off"
          autoFocus={autoFocusName}
          placeholder="e.g. Sam"
          onChange={(e) => set({ name: e.target.value })}
        />
      </Field>

      <Field label="Picture" hint="Pick one, or create your own character.">
        <div className="profile-form__avatars" role="radiogroup" aria-label="Profile picture">
          {/* your own avatar: create it, or edit the one you made */}
          {builtAvatar ? (
            <button
              type="button"
              role="radio"
              aria-checked
              aria-label="Your avatar: edit it"
              title="Edit your avatar"
              className="profile-form__avatar is-selected profile-form__avatar--own"
              onClick={() => setBuilderOpen(true)}
            >
              <Avatar src={builtAvatar} name={values.name} size="100%" />
              <span className="profile-form__avatar-edit" aria-hidden="true">
                <WandIcon />
              </span>
            </button>
          ) : (
            <button
              type="button"
              className="profile-form__avatar profile-form__avatar--create"
              aria-label="Create your own avatar"
              title="Create your own"
              onClick={() => setBuilderOpen(true)}
            >
              <WandIcon />
              <span>Create</span>
            </button>
          )}
          {AVATARS.map((a, i) => (
            <button
              key={a}
              type="button"
              role="radio"
              aria-checked={values.avatar_url === a}
              aria-label={`Picture ${i + 1}`}
              className={`profile-form__avatar${values.avatar_url === a ? ' is-selected' : ''}`}
              onClick={() => set({ avatar_url: a })}
            >
              <Avatar src={a} name={values.name} size="100%" />
            </button>
          ))}
        </div>
      </Field>

      <AvatarBuilder
        open={builderOpen}
        initial={builtAvatar}
        onCancel={() => setBuilderOpen(false)}
        onDone={(code) => {
          set({ avatar_url: code });
          setBuilderOpen(false);
          // the "Create" tile became "your avatar": keep the focus there (TV remote / keyboard)
          setTimeout(() => document.querySelector('.profile-form__avatar--own')?.focus({ preventScroll: true }), 60);
        }}
      />

      <Switch
        checked={!!values.is_kids}
        label="Kids profile"
        description="Only titles rated for children, a simpler home page."
        onChange={(on) => set({ is_kids: on, age_restriction: on && !KIDS_LIMITS.includes(values.age_restriction) ? 'G' : values.age_restriction })}
      />

      <Field label="Age limit" hint={values.is_kids ? 'Kids profiles go up to 7+ (PG).' : 'Titles above this rating are hidden.'}>
        <div className="profile-form__chips" role="group" aria-label="Age limit">
          {limits.map((a) => (
            <Chip key={a.value} selected={age === a.value} onClick={() => set({ age_restriction: a.value })} title={a.hint}>
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

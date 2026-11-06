// src/components/LanguagePicker.js
// The app's language on this device (footer, sign-in pages). Signed-in profiles carry their own
// language (profile form): picking a profile switches to it. A native <select>: phones open
// their own picker, TV remotes and screen readers know how to use it.
import React from 'react';
import { useTranslation } from 'react-i18next';
import { SUPPORTED_LANGUAGES, currentLanguage, setLanguage } from '../i18n';
import { GlobeIcon } from '../design/icons';

export default function LanguagePicker({ className = '', compact = false }) {
  const { t, i18n } = useTranslation();
  const value = currentLanguage();
  return (
    <label className={`language-picker${compact ? ' language-picker--compact' : ''} ${className}`.trim()}>
      <GlobeIcon className="language-picker__icon" aria-hidden="true" />
      <span className="sr-only">{t('language.label')}</span>
      <select
        className="language-picker__select"
        value={value}
        // re-render with the new language (i18n.language) once it's loaded
        data-lang={i18n.resolvedLanguage}
        onChange={(e) => setLanguage(e.target.value)}
      >
        {Object.entries(SUPPORTED_LANGUAGES).map(([code, name]) => (
          <option key={code} value={code} lang={code}>
            {name}
          </option>
        ))}
      </select>
    </label>
  );
}

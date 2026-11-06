// src/components/CreateProfile.js
// Sign-up step 2 of 2: the first profile, then "What do you like to watch?" (/taste), then home (the plan step is set aside for now). Same form as "Who's watching?" -> Add.
// The profile is saved before moving on (the old page left before the request finished, so a
// failed save went unnoticed) and becomes the active profile.
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { createProfile } from '../api/userApi';
import ProfileForm, { EMPTY_PROFILE } from './profiles/ProfileForm';
import { setActiveProfile } from '../utils/activeProfile';
import './profiles/profiles.css';

const CreateProfile = () => {
  const navigate = useNavigate();
  const { t } = useTranslation('profiles');
  const userId = localStorage.getItem('userId');

  const save = async (values) => {
    const created = await createProfile(userId, { ...values, user: userId });
    if (created?.id) setActiveProfile(created);
    navigate(created?.id ? '/taste' : '/', { replace: true });
  };

  return (
    <div className="profile-gate">
      <header className="profiles__top">
        <img src="/logo/navbar-logo.svg" alt="Taurus" className="profiles__logo" width="927" height="108" />
      </header>
      <main className="profiles__main profiles__main--form">
        <div className="profiles__intro">
          <p className="profiles__step">{t('auth:step', { current: 2, total: 2 })}</p>
          <h1 className="profiles__title">{t('create.title')}</h1>
          <p className="profiles__subtitle">{t('create.subtitle', { count: 4 })}</p>
        </div>
        <div className="profiles__card">
          <ProfileForm initial={{ ...EMPTY_PROFILE, user: userId }} submitLabel={t('actions.continue')} onSubmit={save} />
        </div>
      </main>
    </div>
  );
};

export default CreateProfile;

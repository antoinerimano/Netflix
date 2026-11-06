// src/components/ConfirmEmailChange.js
// The page the "confirm your new email" link opens: confirms it, then offers to sign in.
// Link formats: /confirm-email-change/:userId/:token or ?u=...&t=...
import React, { useEffect, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { confirmEmailChange } from '../api/userApi';
import { BrandLoader, Button } from '../design';
import { AuthAlert, AuthLayout } from './auth/AuthLayout';

export default function ConfirmEmailChange() {
  const navigate = useNavigate();
  const { t } = useTranslation('auth');
  const { userId: userIdFromPath, token: tokenFromPath } = useParams();
  const [searchParams] = useSearchParams();
  const userId = userIdFromPath || searchParams.get('u') || searchParams.get('userId');
  const token = tokenFromPath || searchParams.get('t') || searchParams.get('token');

  const [state, setState] = useState({ status: 'working', message: null });

  useEffect(() => {
    let alive = true;
    if (!userId || !token) {
      setState({ status: 'error', message: t('emailChange.incomplete') });
      return undefined;
    }
    confirmEmailChange(userId, token)
      .then(() => alive && setState({ status: 'done', message: null }))
      .catch((e) => {
        if (!alive) return;
        const reason = e?.response?.data?.error;
        setState({ status: 'error', message: reason ? String(reason) : t('emailChange.failed') });
      });
    return () => {
      alive = false;
    };
  }, [userId, token]); // eslint-disable-line react-hooks/exhaustive-deps -- t: messages are picked once

  if (state.status === 'working') {
    return (
      <AuthLayout title={t('emailChange.working')}>
        <div style={{ display: 'grid', placeItems: 'center', padding: 'var(--space-6) 0' }}>
          <BrandLoader size="3.5rem" label={t('emailChange.working')} />
        </div>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title={state.status === 'done' ? t('emailChange.doneTitle') : t('emailChange.errorTitle')}
      subtitle={state.status === 'done' ? t('emailChange.doneText') : null}
    >
      <div className="auth__form">
        {state.status === 'error' ? <AuthAlert>{state.message}</AuthAlert> : null}
        <Button variant="primary" size="lg" block onClick={() => navigate('/login', { replace: true })} data-tv-start="">
          {t('emailChange.goToSignIn')}
        </Button>
      </div>
    </AuthLayout>
  );
}

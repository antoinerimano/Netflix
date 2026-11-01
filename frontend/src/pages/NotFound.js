// src/pages/NotFound.js
// Unknown address: the app's frame (navbar) and a way back, instead of a blank black page.
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../components/Navbar';
import { Button, EmptyState } from '../design';
import { SearchIcon } from '../design/icons';

export default function NotFound() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  return (
    <div className="homepage">
      <Navbar />
      <EmptyState
        page
        icon={<SearchIcon />}
        title={t('notFound.title')}
        actions={
          <>
            <Button variant="primary" to="/">{t('actions.goHome')}</Button>
            <Button variant="ghost" onClick={() => navigate(-1)}>{t('actions.goBack')}</Button>
          </>
        }
      >
        {t('notFound.text')}
      </EmptyState>
    </div>
  );
}

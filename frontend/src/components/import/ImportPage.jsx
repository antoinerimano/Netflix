// src/components/import/ImportPage.jsx
// "Import your history" (/import): ratings, watched titles and watchlist from Letterboxd or IMDb
// export files into the active profile (backend reco/imports.py); the home page is rebuilt from
// them. A TV can't pick files: the page says to open it on a phone or computer.
// TV remote: the sources are a group (lands on the selected one), Down goes to "Choose files",
// the result's "Go to your home page" is where the focus lands.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { importFiles } from '../../api/importApi';
import { Avatar, Button, friendlyError } from '../../design';
import { useFormat } from '../../i18n/format';
import '../AccountManagement.css';
import './import.css';

const SOURCES = ['letterboxd', 'imdb'];
const ACCEPT = { letterboxd: '.zip,.csv', imdb: '.csv' };

function activeProfile() {
  try {
    return JSON.parse(localStorage.getItem('activeProfile') || 'null');
  } catch {
    return null;
  }
}

/** The summary after an import: what was added, and the titles that couldn't be found. */
function Result({ result, onAgain }) {
  const { t } = useTranslation('account');
  const { formatNumber } = useFormat();
  const navigate = useNavigate();
  const [showMissing, setShowMissing] = useState(false);
  const homeRef = useRef(null);
  useEffect(() => homeRef.current?.focus(), []); // the remote lands on the next step

  const added = result.liked + result.disliked + result.watched + result.listed;
  const stats = [
    ['liked', result.liked],
    ['disliked', result.disliked],
    ['watched', result.watched],
    ['listed', result.listed],
    ['notFound', result.not_found],
  ].filter(([, n]) => n > 0);

  return (
    <section className="account-card import-result" aria-labelledby="import-done" aria-live="polite">
      <h2 id="import-done" className="import-result__title">{added ? t('import.done.title') : t('import.done.nothingNew')}</h2>
      {stats.length ? (
        <dl className="import-result__stats">
          {stats.map(([key, n]) => (
            <div key={key} className={`import-stat import-stat--${key}`}>
              <dt>{t(`import.done.${key}`)}</dt>
              <dd>{formatNumber(n)}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {showMissing && result.not_found_examples?.length ? (
        <ul className="import-result__missing">
          {result.not_found_examples.map((name) => (
            <li key={name}>{name}</li>
          ))}
        </ul>
      ) : null}
      <div className="import-result__actions" data-tv-group>
        <Button ref={homeRef} variant="primary" onClick={() => navigate('/')} data-tv-current>
          {t('import.done.home')}
        </Button>
        {result.not_found_examples?.length ? (
          <Button variant="glass" onClick={() => setShowMissing((v) => !v)} aria-expanded={showMissing}>
            {showMissing ? t('import.done.hideMissing') : t('import.done.showMissing')}
          </Button>
        ) : null}
        <Button variant="ghost" onClick={onAgain}>{t('import.done.again')}</Button>
      </div>
    </section>
  );
}

/** Letterboxd / IMDb: how to get the export, then the file picker. */
function FilesPanel({ source, profileId, onDone }) {
  const { t } = useTranslation('account');
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const steps = source === 'imdb' ? ['step1', 'step2', 'step3'] : ['step1', 'step2'];
  const here = `${window.location.host}/import`;

  const upload = async (e) => {
    const files = [...(e.target.files || [])];
    e.target.value = ''; // the same file can be chosen again after an error
    if (!files.length) return;
    setBusy(true);
    setError('');
    try {
      onDone(await importFiles(profileId, files));
    } catch (err) {
      const code = err?.response?.data?.code;
      setError(code === 'unknown_format' || code === 'too_big' ? t(`import.errors.${code}`) : friendlyError(err));
      setBusy(false);
    }
  };

  return (
    <div className="import-panel">
      <ol className="import-steps">
        {steps.map((s) => (
          <li key={s}>{t(`import.${source}.${s}`)}</li>
        ))}
      </ol>
      {error ? <p className="import-error" role="alert">{error}</p> : null}
      <div className="import-panel__actions">
        <input ref={input} type="file" accept={ACCEPT[source]} multiple hidden onChange={upload} tabIndex={-1} />
        <Button variant="primary" loading={busy} onClick={() => input.current?.click()}>
          {busy ? t('import.importing') : t('import.choose')}
        </Button>
      </div>
      <p className="import-tv-hint">{t('import.tvHint', { url: here })}</p>
    </div>
  );
}

export default function ImportPage() {
  const { t } = useTranslation('account');
  const profile = activeProfile();
  const profileId = localStorage.getItem('activeProfileId');
  const [source, setSource] = useState('letterboxd');
  const [result, setResult] = useState(null);
  const onDone = useCallback((res) => setResult(res), []);

  return (
    <div className="account-page">
      <Navbar />
      <main className="account import">
        <header className="account__head">
          <h1 className="account__title">{t('import.title')}</h1>
          <p className="import__subtitle">
            {profile ? <Avatar src={profile.avatar_url} name={profile.name} size="1.75rem" /> : null}
            <span>{t('import.subtitle', { name: profile?.name || '' })}</span>
          </p>
        </header>

        {result ? (
          <Result result={result} onAgain={() => setResult(null)} />
        ) : (
          <section className="account-card" aria-label={t('import.sourcesLabel')}>
            <div className="import-sources" role="group" aria-label={t('import.sourcesLabel')} data-tv-group>
              {SOURCES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`import-source${s === source ? ' is-selected' : ''}`}
                  aria-pressed={s === source}
                  onClick={() => setSource(s)}
                  data-tv-start={s === source ? '' : undefined}
                >
                  <span className="import-source__name">{t(`import.${s}.name`)}</span>
                  <span className="import-source__what">{t(`import.${s}.what`)}</span>
                </button>
              ))}
            </div>
            <FilesPanel key={source} source={source} profileId={profileId} onDone={onDone} />
          </section>
        )}
      </main>
      <Footer />
    </div>
  );
}

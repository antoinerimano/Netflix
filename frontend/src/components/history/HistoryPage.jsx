// src/components/history/HistoryPage.jsx
// "Watch history" (/history, from the profile menu): what the active profile watched here, day by
// day, newest first (backend reco/history.py). Each entry can be removed (the title's last entry
// also clears its Continue watching and what it fed the recommendations), the whole history can
// be cleared (confirmed in a dialog), paused (nothing about watching is saved), or downloaded (CSV).
// TV remote: entries are rows (Down / Up), Right reaches the row's remove button, Down from it
// goes to the next remove button. After a removal the focus moves to the next entry.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { clearHistory, downloadHistory, fetchHistory, removeHistoryItem, setHistoryPaused } from '../../api/historyApi';
import { Avatar, Button, EmptyState, Modal, Skeleton, Switch, Toast, friendlyError } from '../../design';
import { CloseIcon, EyeOffIcon } from '../../design/icons';
import { formatRelativeDay, useFormat } from '../../i18n/format';
import { tmdbImage } from '../../utils/tmdbImage';
import '../AccountManagement.css';
import './history.css';

function activeProfile() {
  try {
    return JSON.parse(localStorage.getItem('activeProfile') || 'null');
  } catch {
    return null;
  }
}

const dayKey = (iso) => {
  const d = new Date(iso);
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
};

/** [{key, date, items}] in the order the entries come (newest first) */
function byDay(items) {
  const days = [];
  for (const it of items) {
    const key = dayKey(it.watched_at);
    const last = days[days.length - 1];
    if (last?.key === key) last.items.push(it);
    else days.push({ key, date: it.watched_at, items: [it] });
  }
  return days;
}

export default function HistoryPage() {
  const { t } = useTranslation('account');
  const { formatDate, lng } = useFormat();
  const navigate = useNavigate();
  const profile = activeProfile();
  const profileId = localStorage.getItem('activeProfileId');
  const [items, setItems] = useState(null); // null: loading
  const [next, setNext] = useState(null);
  const [paused, setPaused] = useState(false);
  const [error, setError] = useState(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState({ message: '', tone: 'success' });
  const clearToast = useCallback(() => setToast({ message: '', tone: 'success' }), []);
  const focusAfter = useRef(null); // entry id to focus once the list re-rendered

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await fetchHistory(profileId, 1);
      setItems(data.items);
      setNext(data.next);
      setPaused(!!data.paused);
    } catch (e) {
      setError(e);
    }
  }, [profileId]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (focusAfter.current == null) return;
    const el = document.querySelector(`[data-history-remove="${focusAfter.current}"]`) || document.querySelector('.history-toolbar .ui-switch');
    focusAfter.current = null;
    el?.focus({ preventScroll: false });
  }, [items]);

  const more = async () => {
    setLoadingMore(true);
    try {
      const data = await fetchHistory(profileId, next);
      setItems((cur) => [...cur, ...data.items]);
      setNext(data.next);
    } finally {
      setLoadingMore(false);
    }
  };

  const remove = async (item) => {
    const i = items.findIndex((x) => x.id === item.id);
    const neighbour = items[i + 1] || items[i - 1];
    try {
      await removeHistoryItem(profileId, item.id);
      focusAfter.current = neighbour ? neighbour.id : -1; // -1: the list is empty, back to the toolbar
      setItems((cur) => cur.filter((x) => x.id !== item.id));
      setToast({ message: t('history.removed', { title: item.title.title }), tone: 'success' });
    } catch (e) {
      setToast({ message: friendlyError(e), tone: 'error' });
    }
  };

  const togglePause = async (value) => {
    setPaused(value);
    try {
      setPaused(await setHistoryPaused(profileId, value));
    } catch (e) {
      setPaused(!value);
      setToast({ message: friendlyError(e), tone: 'error' });
    }
  };

  const clearAll = async () => {
    setBusy(true);
    try {
      await clearHistory(profileId);
      setItems([]);
      setNext(null);
      setConfirmClear(false);
      setToast({ message: t('history.cleared'), tone: 'success' });
    } catch (e) {
      setToast({ message: friendlyError(e), tone: 'error' });
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    try {
      await downloadHistory(profileId);
    } catch (e) {
      setToast({ message: friendlyError(e), tone: 'error' });
    }
  };

  const dayTitle = (iso) => {
    const today = new Date();
    const d = new Date(iso);
    const days = Math.round((new Date(today.getFullYear(), today.getMonth(), today.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
    if (days <= 1) return formatRelativeDay(days, lng); // Today / Yesterday
    const text = formatDate(iso, { weekday: 'long', day: 'numeric', month: 'long', ...(days > 300 ? { year: 'numeric' } : {}) });
    return text.charAt(0).toLocaleUpperCase(lng) + text.slice(1);
  };

  let list;
  if (error) {
    list = (
      <EmptyState tone="error" title={t('history.loadError')} actions={<Button variant="primary" onClick={load}>{t('actions.tryAgain')}</Button>}>
        {friendlyError(error)}
      </EmptyState>
    );
  } else if (items === null) {
    list = (
      <div className="history-days" aria-busy="true" aria-label={t('common:loading')}>
        {[0, 1, 2, 3].map((i) => <Skeleton key={i} height="4.5rem" />)}
      </div>
    );
  } else if (!items.length) {
    list = (
      <EmptyState icon={paused ? <EyeOffIcon /> : null} title={paused ? t('history.pausedTitle') : t('history.emptyTitle')}>
        {paused ? t('history.pausedText') : t('history.emptyText')}
      </EmptyState>
    );
  } else {
    list = (
      <div className="history-days">
        {byDay(items).map((day) => (
          <section key={day.key} className="history-day" aria-labelledby={`hd-${day.key}`}>
            <h2 id={`hd-${day.key}`} className="history-day__title">{dayTitle(day.date)}</h2>
            <ul className="history-list">
              {day.items.map((it) => {
                const tv = it.title.type === 'tv';
                const image = it.title.landscape_image || it.title.poster;
                const sub = tv && it.episode
                  ? [t('catalog:episodeShort', { season: it.season, episode: it.episode }), it.episode_info?.name].filter(Boolean).join(' · ')
                  : t(tv ? 'common:kind.tv' : 'common:kind.movie');
                return (
                  <li key={it.id} className="history-row">
                    <button type="button" className="history-item" onClick={() => navigate(tv ? `/tv/${it.title.id}` : `/movies/${it.title.id}`)}>
                      <span className="history-item__art">
                        {image ? <img src={tmdbImage(image, 'w300')} alt="" loading="lazy" decoding="async" /> : null}
                      </span>
                      <span className="history-item__text">
                        <span className="history-item__title">{it.title.title}</span>
                        <span className="history-item__sub">
                          {sub}
                          <span className="history-item__time"> · {formatDate(it.watched_at, { hour: 'numeric', minute: '2-digit' })}</span>
                        </span>
                      </span>
                    </button>
                    <Button
                      variant="ghost"
                      icon={<CloseIcon />}
                      label={t('history.remove', { title: it.title.title })}
                      className="history-row__remove"
                      data-history-remove={it.id}
                      onClick={() => remove(it)}
                    />
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
        {next ? (
          <div className="history-more">
            <Button variant="glass" loading={loadingMore} onClick={more}>{t('history.more')}</Button>
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="account-page">
      <Navbar />
      <main className="account history">
        <header className="account__head">
          <h1 className="account__title">{t('history.title')}</h1>
          <p className="history__subtitle">
            {profile ? <Avatar src={profile.avatar_url} name={profile.name} size="1.75rem" /> : null}
            <span>{t('history.subtitle', { name: profile?.name || '' })}</span>
          </p>
        </header>

        <section className="account-card history-toolbar" aria-label={t('history.settings')}>
          <Switch checked={paused} onChange={togglePause} label={t('history.pause')} description={t('history.pauseHint')} />
          <div className="history-toolbar__actions">
            <Button variant="glass" size="sm" onClick={download} disabled={!items?.length}>{t('history.download')}</Button>
            <Button variant="danger" size="sm" onClick={() => setConfirmClear(true)} disabled={!items?.length}>{t('history.clear')}</Button>
          </div>
        </section>

        {list}
      </main>
      <Footer />

      <Modal
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        title={t('history.clearTitle')}
        size="sm"
        scrollable={false}
        initialFocus=".ui-modal__footer .ui-btn--ghost"
        footer={
          <>
            <Button variant="ghost" onClick={() => setConfirmClear(false)} disabled={busy}>{t('actions.cancel')}</Button>
            <Button variant="danger" loading={busy} onClick={clearAll}>{t('history.clear')}</Button>
          </>
        }
      >
        <p className="account-dialog__text">{t('history.clearText', { name: profile?.name || '' })}</p>
      </Modal>

      <Toast message={toast.message} tone={toast.tone} onDone={clearToast} />
    </div>
  );
}

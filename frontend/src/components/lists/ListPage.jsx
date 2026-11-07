// src/components/lists/ListPage.jsx
// One of the profile's lists (/lists/:id): its titles (a row each: OK opens it, Right reaches its
// remove button), Share (a switch: anyone with the link can see it, with the profile name as
// author; then the short address in big letters to type on a phone, Copy / the share sheet),
// Edit (name, description) and Delete (confirmed). Backend reco/lists.py.
// TV remote: Share, then Edit / Delete, then the titles; dialogs keep the focus, Back closes them.
import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { deleteList, fetchList, setInList, shareUrl, updateList } from '../../api/listsApi';
import { Button, EmptyState, Field, Modal, Skeleton, Switch, Toast, friendlyError } from '../../design';
import { CloseIcon, LinkIcon, ShareIcon } from '../../design/icons';
import { tmdbImage } from '../../utils/tmdbImage';
import { usePageTitle } from '../../utils/pageTitle';
import { ListCover } from './YourLists';
import '../AccountManagement.css';
import '../history/history.css';
import './lists.css';

function ownerName() {
  try {
    return JSON.parse(localStorage.getItem('activeProfile') || 'null')?.name || '';
  } catch {
    return '';
  }
}

export default function ListPage() {
  const { t } = useTranslation('catalog');
  const { id } = useParams();
  const navigate = useNavigate();
  const profileId = localStorage.getItem('activeProfileId');
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [dialog, setDialog] = useState(null); // 'edit' | 'delete' | null
  const [form, setForm] = useState({ name: '', description: '' });
  const [formError, setFormError] = useState('');
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState({ message: '', tone: 'success' });
  const clearToast = useCallback(() => setToast({ message: '', tone: 'success' }), []);
  usePageTitle(data?.name);

  const load = useCallback(async () => {
    setError(null);
    try {
      setData(await fetchList(profileId, id));
    } catch (e) {
      setError(e);
    }
  }, [profileId, id]);

  useEffect(() => {
    load();
  }, [load]);

  const fail = (e) => setToast({ message: friendlyError(e), tone: 'error' });

  const setShared = async (value) => {
    setData((d) => ({ ...d, is_public: value }));
    try {
      await updateList(profileId, id, { is_public: value });
    } catch (e) {
      setData((d) => ({ ...d, is_public: !value }));
      fail(e);
    }
  };

  const shareLink = async () => {
    const url = shareUrl(data.share_id);
    try {
      if (navigator.share) {
        await navigator.share({ title: data.name, url });
        return;
      }
      await navigator.clipboard.writeText(url);
      setToast({ message: t('lists.copied'), tone: 'success' });
    } catch (e) {
      if (e?.name !== 'AbortError') setToast({ message: url, tone: 'success' }); // no clipboard: show it
    }
  };

  const save = async (e) => {
    e?.preventDefault();
    if (!form.name.trim()) {
      setFormError(t('lists.nameRequired'));
      return;
    }
    setBusy(true);
    try {
      const updated = await updateList(profileId, id, { name: form.name.trim(), description: form.description });
      setData((d) => ({ ...d, name: updated.name, description: updated.description }));
      setDialog(null);
    } catch (err) {
      setFormError(friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await deleteList(profileId, id);
      navigate('/list', { replace: true });
    } catch (e) {
      setBusy(false);
      fail(e);
    }
  };

  const removeItem = async (item) => {
    const i = data.items.findIndex((x) => x.title.id === item.title.id);
    const neighbour = data.items[i + 1] || data.items[i - 1];
    try {
      await setInList(profileId, id, item.title.id, false);
      setData((d) => ({ ...d, items: d.items.filter((x) => x.title.id !== item.title.id), count: d.count - 1 }));
      setToast({ message: t('lists.removedFrom', { name: data.name }), tone: 'success' });
      setTimeout(() => {
        const el = neighbour && document.querySelector(`[data-list-remove="${neighbour.title.id}"]`);
        (el || document.querySelector('.list-head .ui-switch'))?.focus();
      }, 0);
    } catch (e) {
      fail(e);
    }
  };

  let body;
  if (error) {
    const missing = error?.response?.status === 404;
    body = (
      <EmptyState
        page
        tone={missing ? 'empty' : 'error'}
        title={missing ? t('lists.notFound') : t('lists.loadError')}
        actions={<Button variant="primary" to="/list">{t('common:nav.myList')}</Button>}
      >
        {missing ? null : friendlyError(error)}
      </EmptyState>
    );
  } else if (!data) {
    body = (
      <div className="account" aria-busy="true" aria-label={t('common:loading')}>
        <Skeleton width="min(24rem, 80%)" height="2.5rem" />
        <Skeleton height="6rem" />
      </div>
    );
  } else {
    const link = shareUrl(data.share_id);
    body = (
      <div className="account list-page">
        <header className="list-head">
          <ListCover covers={data.covers} />
          <div className="list-head__text">
            <h1 className="account__title">{data.name}</h1>
            <p className="list-head__meta">{t('lists.count', { count: data.count })}</p>
            {data.description ? <p className="list-head__desc">{data.description}</p> : null}
          </div>
        </header>

        <section className="account-card list-share" aria-label={t('lists.share')}>
          <Switch
            checked={data.is_public}
            onChange={setShared}
            label={t('lists.share')}
            description={t('lists.shareHint', { name: ownerName() })}
          />
          {data.is_public ? (
            <div className="list-share__link">
              <p className="list-share__url" aria-label={t('lists.link')}>{link.replace(/^https?:\/\//, '')}</p>
              <p className="list-share__tv">{t('lists.tvHint')}</p>
              <div className="list-share__actions">
                <Button variant="glass" size="sm" icon={navigator.share ? <ShareIcon /> : <LinkIcon />} onClick={shareLink}>
                  {navigator.share ? t('lists.shareVia') : t('lists.copy')}
                </Button>
                <Button variant="glass" size="sm" to={`/l/${data.share_id}`}>{t('lists.preview')}</Button>
              </div>
            </div>
          ) : null}
          <div className="list-share__actions">
            <Button
              variant="glass"
              size="sm"
              onClick={() => {
                setForm({ name: data.name, description: data.description });
                setFormError('');
                setDialog('edit');
              }}
            >
              {t('lists.edit')}
            </Button>
            <Button variant="danger" size="sm" onClick={() => setDialog('delete')}>{t('lists.delete')}</Button>
          </div>
        </section>

        {data.items.length ? (
          <ul className="history-list">
            {data.items.map((it) => {
              const tv = it.title.type === 'tv';
              const image = it.title.landscape_image || it.title.poster;
              return (
                <li key={it.title.id} className="history-row">
                  <button type="button" className="history-item" onClick={() => navigate(tv ? `/tv/${it.title.id}` : `/movies/${it.title.id}`)}>
                    <span className="history-item__art">
                      {image ? <img src={tmdbImage(image, 'w300')} alt="" loading="lazy" decoding="async" /> : null}
                    </span>
                    <span className="history-item__text">
                      <span className="history-item__title">{it.title.title}</span>
                      <span className="history-item__sub">
                        {[t(tv ? 'common:kind.tv' : 'common:kind.movie'), it.title.release_year].filter(Boolean).join(' · ')}
                      </span>
                    </span>
                  </button>
                  <Button
                    variant="ghost"
                    icon={<CloseIcon />}
                    label={t('lists.remove', { title: it.title.title })}
                    className="history-row__remove"
                    data-list-remove={it.title.id}
                    onClick={() => removeItem(it)}
                  />
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState title={t('lists.empty')}>{t('lists.emptyText')}</EmptyState>
        )}
      </div>
    );
  }

  return (
    <div className="account-page">
      <Navbar />
      <main>{body}</main>
      <Footer />

      <Modal
        open={dialog === 'edit'}
        onClose={() => setDialog(null)}
        title={t('lists.editTitle')}
        size="sm"
        scrollable={false}
        initialFocus="#list-edit-name"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>{t('common:actions.cancel')}</Button>
            <Button variant="primary" loading={busy} onClick={save}>{t('common:actions.save')}</Button>
          </>
        }
      >
        <form className="account-dialog" onSubmit={save} noValidate>
          <Field label={t('lists.name')} htmlFor="list-edit-name" error={formError}>
            <input
              id="list-edit-name"
              className="ui-input"
              value={form.name}
              maxLength={80}
              onChange={(e) => {
                setForm((f) => ({ ...f, name: e.target.value }));
                setFormError('');
              }}
            />
          </Field>
          <Field label={t('lists.description')} htmlFor="list-edit-description">
            <textarea
              id="list-edit-description"
              className="ui-input list-edit__desc"
              value={form.description}
              maxLength={300}
              rows={3}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            />
          </Field>
        </form>
      </Modal>

      <Modal
        open={dialog === 'delete'}
        onClose={() => setDialog(null)}
        title={t('lists.deleteTitle', { name: data?.name || '' })}
        size="sm"
        scrollable={false}
        initialFocus=".ui-modal__footer .ui-btn--ghost"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDialog(null)} disabled={busy}>{t('common:actions.cancel')}</Button>
            <Button variant="danger" loading={busy} onClick={remove}>{t('lists.delete')}</Button>
          </>
        }
      >
        <p className="account-dialog__text">{t('lists.deleteText')}</p>
      </Modal>

      <Toast message={toast.message} tone={toast.tone} onDone={clearToast} />
    </div>
  );
}

// src/components/lists/YourLists.jsx
// "Your lists" at the top of My List (/list): a row of the profile's lists (a mosaic of their
// posters, name, count, "Shared") and a "New list" tile (a name, then its page).
// TV remote: the row is a group (Right / Left along it); OK opens a list; the New list dialog
// starts on its name field.
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { createList, fetchLists } from '../../api/listsApi';
import { Button, Field, Modal, SectionTitle, friendlyError } from '../../design';
import { PlusIcon } from '../../design/icons';
import { IMG, tmdbImage } from '../../utils/tmdbImage';
import './lists.css';

export function ListCover({ covers }) {
  return (
    <span className={`list-cover list-cover--${Math.min(covers.length, 4)}`} aria-hidden="true">
      {covers.slice(0, 4).map((c) => <img key={c} src={tmdbImage(c, IMG.poster)} alt="" loading="lazy" decoding="async" />)}
    </span>
  );
}

export default function YourLists() {
  const { t } = useTranslation('catalog');
  const navigate = useNavigate();
  const profileId = localStorage.getItem('activeProfileId');
  const [lists, setLists] = useState(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!profileId) return undefined;
    let alive = true;
    fetchLists(profileId)
      .then((d) => alive && setLists(d.lists))
      .catch(() => alive && setLists([]));
    return () => {
      alive = false;
    };
  }, [profileId]);

  const create = async (e) => {
    e?.preventDefault();
    if (!name.trim()) {
      setError(t('lists.nameRequired'));
      return;
    }
    setBusy(true);
    try {
      const made = await createList(profileId, { name: name.trim() });
      navigate(`/lists/${made.id}`);
    } catch (err) {
      setError(err?.response?.data?.code === 'too_many' ? t('lists.tooMany') : friendlyError(err));
      setBusy(false);
    }
  };

  if (lists === null) return null;

  return (
    <section className="your-lists" aria-labelledby="your-lists-title">
      <SectionTitle id="your-lists-title">{t('lists.yourLists')}</SectionTitle>
      <ul className="ui-scroller your-lists__row" data-tv-group>
        {lists.map((l, i) => (
          <li key={l.id}>
            {/* the remote starts here: the top of the page (not My List's "Browse movies" below) */}
            <button type="button" className="list-card" data-tv-start={i === 0 ? '' : undefined} onClick={() => navigate(`/lists/${l.id}`)}>
              <ListCover covers={l.covers} />
              <span className="list-card__name">{l.name}</span>
              <span className="list-card__meta">
                {t('lists.count', { count: l.count })}
                {l.is_public ? ` · ${t('lists.shared')}` : ''}
              </span>
            </button>
          </li>
        ))}
        <li>
          <button
            type="button"
            className="list-card list-card--new"
            data-tv-start={lists.length ? undefined : ''}
            onClick={() => {
              setName('');
              setError('');
              setCreating(true);
            }}
          >
            <span className="list-cover list-cover--new" aria-hidden="true"><PlusIcon /></span>
            <span className="list-card__name">{t('lists.newList')}</span>
            <span className="list-card__meta">{t('lists.newListHint')}</span>
          </button>
        </li>
      </ul>

      <Modal
        open={creating}
        onClose={() => setCreating(false)}
        title={t('lists.newList')}
        size="sm"
        scrollable={false}
        initialFocus="#list-create-name"
        footer={
          <>
            <Button variant="ghost" onClick={() => setCreating(false)} disabled={busy}>{t('common:actions.cancel')}</Button>
            <Button variant="primary" loading={busy} onClick={create}>{t('lists.create')}</Button>
          </>
        }
      >
        <form onSubmit={create} noValidate>
          <Field label={t('lists.name')} htmlFor="list-create-name" error={error}>
            <input
              id="list-create-name"
              className="ui-input"
              value={name}
              maxLength={80}
              placeholder={t('lists.namePlaceholder')}
              onChange={(e) => {
                setName(e.target.value);
                setError('');
              }}
            />
          </Field>
        </form>
      </Modal>
    </section>
  );
}

// src/components/lists/ListPicker.jsx
// "Add to a list": a dialog with the profile's lists (OK adds / removes the title, a check shows
// where it is) and "New list" (a name, then Create: the list starts with this title).
// TV remote: the dialog keeps the focus; it opens on the first list (or the name field when there
// are none); Back closes it.
import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { createList, fetchLists, setInList } from '../../api/listsApi';
import { Button, Modal, Toast, friendlyError } from '../../design';
import { CheckIcon, PlusIcon } from '../../design/icons';
import './lists.css';

export default function ListPicker({ title, open, onClose }) {
  const { t } = useTranslation('catalog');
  const profileId = localStorage.getItem('activeProfileId');
  const [lists, setLists] = useState(null); // null: loading
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');

  useEffect(() => {
    if (!open || !title?.id) return undefined;
    let alive = true;
    setLists(null);
    setName('');
    setError('');
    fetchLists(profileId, title.id)
      .then((d) => alive && setLists(d.lists))
      .catch((e) => alive && (setLists([]), setError(friendlyError(e))));
    return () => {
      alive = false;
    };
  }, [open, title?.id, profileId]);

  // the dialog opens before the lists arrive (focus in the name field): once they're here, the
  // remote starts on the first one, unless a name is being typed
  useEffect(() => {
    if (!open || !lists?.length) return;
    const field = document.getElementById('list-new-name');
    if (document.activeElement === field && !field.value) document.querySelector('.list-picker .list-pick')?.focus();
  }, [open, lists === null]); // eslint-disable-line react-hooks/exhaustive-deps -- only when they arrive

  const toggle = async (list) => {
    const next = !list.contains;
    setLists((ls) => ls.map((l) => (l.id === list.id ? { ...l, contains: next, count: l.count + (next ? 1 : -1) } : l)));
    try {
      await setInList(profileId, list.id, title.id, next);
      setToast(next ? t('lists.added', { name: list.name }) : t('lists.removedFrom', { name: list.name }));
    } catch (e) {
      setLists((ls) => ls.map((l) => (l.id === list.id ? { ...l, contains: !next, count: l.count + (next ? -1 : 1) } : l)));
      setError(friendlyError(e));
    }
  };

  const create = async (e) => {
    e?.preventDefault();
    if (!name.trim()) {
      setError(t('lists.nameRequired'));
      return;
    }
    setBusy(true);
    setError('');
    try {
      const made = await createList(profileId, { name: name.trim(), titleId: title.id });
      setLists((ls) => [{ ...made, contains: true, count: 1 }, ...(ls || [])]);
      setName('');
      setToast(t('lists.added', { name: made.name }));
    } catch (err) {
      setError(err?.response?.data?.code === 'too_many' ? t('lists.tooMany') : friendlyError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={t('lists.pickerTitle', { title: title?.title || '' })}
        size="sm"
        initialFocus={lists?.length ? '.list-pick' : '#list-new-name'}
        className="list-picker"
      >
        {lists === null ? <p className="list-picker__hint">{t('common:loading')}</p> : null}
        {lists?.length ? (
          <ul className="list-picker__lists">
            {lists.map((l) => (
              <li key={l.id}>
                <button type="button" className={`list-pick${l.contains ? ' is-on' : ''}`} aria-pressed={!!l.contains} onClick={() => toggle(l)}>
                  <span className="list-pick__box" aria-hidden="true">{l.contains ? <CheckIcon /> : null}</span>
                  <span className="list-pick__name">{l.name}</span>
                  <span className="list-pick__count">{t('lists.count', { count: l.count })}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <form className="list-picker__new" onSubmit={create}>
          <label htmlFor="list-new-name" className="list-picker__label">{t('lists.newList')}</label>
          <div className="list-picker__row">
            <input
              id="list-new-name"
              className="ui-input"
              value={name}
              maxLength={80}
              placeholder={t('lists.namePlaceholder')}
              onChange={(e) => {
                setName(e.target.value);
                setError('');
              }}
            />
            <Button type="submit" variant="primary" icon={<PlusIcon />} loading={busy}>{t('lists.create')}</Button>
          </div>
          {error ? <p className="list-picker__error" role="alert">{error}</p> : null}
        </form>
      </Modal>
      <Toast message={toast} onDone={() => setToast('')} />
    </>
  );
}

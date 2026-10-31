// src/components/profiles/ProfilesPage.js
// "Who's watching?" (/profiles): pick a profile after signing in or from the profile menu,
// add one (up to MAX_PROFILES), or "Manage profiles" to edit / delete them. Picking a profile
// switches without reloading the app (utils/activeProfile.js).
import React, { useCallback, useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { fetchUserProfiles, createProfile, updateProfile, deleteProfile } from '../../api/userApi';
import { Avatar, Button, EmptyState, Modal, Skeleton, friendlyError } from '../../design';
import { PlusIcon } from '../../design/icons';
import ProfileForm, { EMPTY_PROFILE, ageSummary } from './ProfileForm';
import { CheckIcon } from '../../design/icons';
import { MAX_PROFILES, getActiveProfileId, setActiveProfile, clearActiveProfile } from '../../utils/activeProfile';
import './profiles.css';

const PencilIcon = () => (
  <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4Z" />
    <path d="m13.5 6.5 4 4" />
  </svg>
);

export default function ProfilesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const userId = localStorage.getItem('userId');
  const [profiles, setProfiles] = useState(null); // null: loading
  const [error, setError] = useState(null);
  const [manage, setManage] = useState(() => new URLSearchParams(location.search).has('manage'));
  const [editing, setEditing] = useState(null); // profile | 'new' | null
  const [confirmDelete, setConfirmDelete] = useState(false);
  const activeId = getActiveProfileId();

  const load = useCallback(async () => {
    setError(null);
    try {
      const raw = await fetchUserProfiles(userId);
      setProfiles(Array.isArray(raw) ? raw : raw?.results ?? raw?.profiles ?? []);
    } catch (e) {
      setError(e);
      setProfiles([]);
    }
  }, [userId]);

  useEffect(() => {
    if (!userId) {
      navigate('/login', { replace: true });
      return;
    }
    load();
  }, [userId, load, navigate]);

  const choose = (p) => {
    setActiveProfile(p);
    const from = location.state?.from;
    const target = from?.pathname && from.pathname !== '/profiles' ? `${from.pathname}${from.search || ''}` : '/';
    navigate(target, { replace: true });
  };

  // short confirmation after a change ("Sam added")
  const [toast, setToast] = useState('');
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(''), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const save = async (values) => {
    if (editing === 'new') {
      const created = await createProfile(userId, { ...values, user: userId });
      setEditing(null);
      await load();
      setToast(`${values.name} added`);
      if (!manage && created?.id) choose(created); // a new profile from "Who's watching?": start watching
      return;
    }
    const updated = await updateProfile(userId, editing.id, { ...editing, ...values });
    if (String(editing.id) === activeId) setActiveProfile({ ...editing, ...values, ...(updated || {}) });
    setEditing(null);
    await load();
    setToast(`${values.name} saved`);
  };

  const remove = async () => {
    const p = editing;
    await deleteProfile(userId, p.id);
    localStorage.removeItem(`userList_${p.id}`);
    if (String(p.id) === activeId) clearActiveProfile();
    setConfirmDelete(false);
    setEditing(null);
    await load();
    setToast(`${p.name} deleted`);
  };

  const canAdd = profiles && profiles.length < MAX_PROFILES;
  const title = manage ? 'Manage profiles' : "Who's watching?";

  let body;
  if (profiles === null) {
    body = (
      <ul className="profiles__grid" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <li key={i} className="profiles__item">
            <Skeleton className="profiles__avatar" />
            <Skeleton variant="text" width="60%" />
          </li>
        ))}
      </ul>
    );
  } else if (error) {
    body = (
      <EmptyState tone="error" title="Couldn't load your profiles" actions={<Button variant="primary" onClick={load}>Try again</Button>}>
        {friendlyError(error, 'your profiles')}
      </EmptyState>
    );
  } else {
    body = (
      <ul className="profiles__grid">
        {profiles.map((p) => {
          const isActive = String(p.id) === activeId;
          return (
            <li key={p.id} className="profiles__item">
              <button
                type="button"
                className={`profile-tile${manage ? ' is-managing' : ''}${isActive ? ' is-active' : ''}`}
                onClick={() => (manage ? setEditing(p) : choose(p))}
                aria-label={manage ? `Edit ${p.name}` : `Watch as ${p.name}`}
              >
                <span className="profile-tile__art">
                  <Avatar src={p.avatar_url} name={p.name} size="100%" className="profiles__avatar" />
                  {manage ? (
                    <span className="profile-tile__edit" aria-hidden="true">
                      <PencilIcon />
                    </span>
                  ) : null}
                </span>
                <span className="profile-tile__name">{p.name}</span>
                {manage ? (
                  <span className="profile-tile__meta">{ageSummary(p)}</span>
                ) : p.is_kids ? (
                  <span className="profile-tile__badge">Kids</span>
                ) : null}
              </button>
            </li>
          );
        })}
        {canAdd ? (
          <li className="profiles__item">
            <button type="button" className="profile-tile profile-tile--add" onClick={() => setEditing('new')} aria-label="Add a profile">
              <span className="profile-tile__art">
                <span className="profiles__avatar profile-tile__plus">
                  <PlusIcon />
                </span>
              </span>
              <span className="profile-tile__name">Add profile</span>
            </button>
          </li>
        ) : null}
      </ul>
    );
  }

  return (
    <div className="profile-gate">
      <header className="profiles__top">
        <img src="/logo/navbar-logo.svg" alt="Taurus" className="profiles__logo" width="927" height="108" />
      </header>

      <main className="profiles__main">
        <h1 className="profiles__title">{title}</h1>
        {manage ? <p className="profiles__subtitle">Choose a profile to edit it.</p> : null}
        {body}
        {profiles?.length ? (
          <div className="profiles__actions">
            {manage ? (
              <Button variant="secondary" size="lg" onClick={() => setManage(false)}>
                Done
              </Button>
            ) : (
              <Button variant="glass" onClick={() => setManage(true)}>
                Manage profiles
              </Button>
            )}
          </div>
        ) : null}
      </main>

      {toast ? (
        <div className="profiles__toast" role="status">
          <CheckIcon aria-hidden="true" />
          {toast}
        </div>
      ) : null}

      <Modal
        open={!!editing}
        onClose={() => {
          setEditing(null);
          setConfirmDelete(false);
        }}
        title={editing === 'new' ? 'Add a profile' : 'Edit profile'}
        size="md"
        scrollable={false}
        initialFocus="#profile-name"
      >
        {editing ? (
          <ProfileForm
            key={editing === 'new' ? 'new' : editing.id}
            initial={editing === 'new' ? EMPTY_PROFILE : editing}
            submitLabel={editing === 'new' ? 'Add profile' : 'Save'}
            onSubmit={save}
            onCancel={() => setEditing(null)}
            extraActions={
              editing !== 'new' && profiles.length > 1 ? (
                confirmDelete ? (
                  <span className="profiles__confirm">
                    Delete {editing.name}?{' '}
                    <Button variant="danger" size="sm" onClick={remove}>
                      Delete
                    </Button>{' '}
                    <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
                      Keep
                    </Button>
                  </span>
                ) : (
                  <Button variant="danger" size="sm" onClick={() => setConfirmDelete(true)}>
                    Delete profile
                  </Button>
                )
              ) : null
            }
          />
        ) : null}
      </Modal>
    </div>
  );
}

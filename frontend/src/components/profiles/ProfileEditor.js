// src/components/profiles/ProfileEditor.js
// The add / edit profile dialog (ProfileForm in a Modal) with its saving, deleting (two steps)
// and the active-profile bookkeeping. Used by "Who's watching?" and the account page.
import React, { useState } from 'react';
import { createProfile, updateProfile, deleteProfile } from '../../api/userApi';
import { Button, Modal } from '../../design';
import ProfileForm, { EMPTY_PROFILE } from './ProfileForm';
import { getActiveProfileId, setActiveProfile, clearActiveProfile } from '../../utils/activeProfile';
import './profiles.css';

/**
 * editing: a profile, 'new' or null (closed). canDelete: false for the last profile.
 * onDone({ type: 'added' | 'saved' | 'deleted', profile }) after the server confirmed.
 */
export default function ProfileEditor({ editing, onClose, onDone, canDelete = true }) {
  const userId = localStorage.getItem('userId');
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const isNew = editing === 'new';

  const close = () => {
    setConfirmDelete(false);
    onClose();
  };

  const save = async (values) => {
    if (isNew) {
      const created = await createProfile(userId, { ...values, user: userId });
      setConfirmDelete(false);
      onDone({ type: 'added', profile: { ...values, ...(created || {}) } });
      return;
    }
    const updated = await updateProfile(userId, editing.id, { ...editing, ...values });
    const profile = { ...editing, ...values, ...(updated || {}) };
    if (String(editing.id) === getActiveProfileId()) setActiveProfile(profile);
    setConfirmDelete(false);
    onDone({ type: 'saved', profile });
  };

  const remove = async () => {
    setDeleting(true);
    try {
      await deleteProfile(userId, editing.id);
      localStorage.removeItem(`userList_${editing.id}`);
      if (String(editing.id) === getActiveProfileId()) clearActiveProfile();
      setConfirmDelete(false);
      onDone({ type: 'deleted', profile: editing });
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Modal open={!!editing} onClose={close} title={isNew ? 'Add a profile' : 'Edit profile'} size="md" scrollable={false} initialFocus="#profile-name">
      {editing ? (
        <ProfileForm
          key={isNew ? 'new' : editing.id}
          initial={isNew ? EMPTY_PROFILE : editing}
          submitLabel={isNew ? 'Add profile' : 'Save'}
          onSubmit={save}
          onCancel={close}
          extraActions={
            !isNew && canDelete ? (
              confirmDelete ? (
                <span className="profiles__confirm" role="alert">
                  Delete {editing.name}?{' '}
                  <Button variant="danger" size="sm" loading={deleting} onClick={remove}>
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
  );
}

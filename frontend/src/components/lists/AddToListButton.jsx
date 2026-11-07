// src/components/lists/AddToListButton.jsx
// "Add to a list" on a movie / show page: an icon button next to My List that opens the list
// picker (signed in with a profile only).
import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '../../design';
import { ListPlusIcon } from '../../design/icons';
import ListPicker from './ListPicker';

export default function AddToListButton({ title }) {
  const { t } = useTranslation('catalog');
  const [open, setOpen] = useState(false);
  if (!localStorage.getItem('activeProfileId') || !title?.id) return null;
  return (
    <>
      <Button variant="glass" icon={<ListPlusIcon />} label={t('lists.addToList')} onClick={() => setOpen(true)} />
      <ListPicker title={title} open={open} onClose={() => setOpen(false)} />
    </>
  );
}

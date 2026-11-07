// src/components/TitleOptions.js
// Options for one title, in a sheet (design Modal): Play / Resume, More info, My List, Add to a
// list (the list picker), like / dislike, then the card's own actions (remove from Continue watching, not interested).
// Opened by holding OK on a TV remote, the remote's menu key, a right click, a long press on
// touch screens or the card's "⋯" button (see Row.js, tv/spatialNavigation.js).
import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Modal, Rating } from '../design';
import {
  PlayIcon, InfoIcon, PlusIcon, CheckIcon, ThumbUpIcon, ThumbDownIcon, BanIcon, CloseIcon, ListPlusIcon,
} from '../design/icons';
import ListPicker from './lists/ListPicker';
import { fetchMyList, setInMyList } from '../api/myListApi';
import { fetchRating, setRating } from '../api/recoApi';
import { logActionBeacon } from '../api/analyticsApi';
import { tmdbImage, IMG } from '../utils/tmdbImage';
import './TitleOptions.css';

function MenuItem({ icon, label, onClick, active, tone, autoFocus }) {
  return (
    <li>
      <button
        type="button"
        className={`ui-menu-item${tone ? ` is-${tone}` : ''}`}
        aria-pressed={active === undefined ? undefined : !!active}
        data-autofocus={autoFocus ? '' : undefined}
        onClick={onClick}
      >
        <span className="ui-menu-item__icon">{icon}</span>
        <span className="ui-menu-item__label">{label}</span>
        {active ? <CheckIcon className="ui-menu-item__state" aria-hidden="true" /> : null}
      </button>
    </li>
  );
}

/**
 * title: { id, type, title, landscape_image, poster, release_year, rating, resume }
 * onPlay / onInfo: navigation done by the caller (it knows the analytics surface).
 * onRemoveResume / onNotInterested: optional, shown only when given.
 */
export default function TitleOptions({
  title, open, onClose, onPlay, onInfo, onRemoveResume, onNotInterested, onRemoveFromList, surface = 'options',
}) {
  const { t } = useTranslation('catalog');
  const profileId = localStorage.getItem('activeProfileId');
  const [inList, setInList] = useState(null); // null: not known yet
  const [rating, setRatingState] = useState(null);
  // the "Add to a list" dialog, opened as this sheet closes: it keeps its own copy of the title
  // (a home row forgets the title when the sheet closes)
  const [pickTitle, setPickTitle] = useState(null);
  const picker = <ListPicker title={pickTitle} open={!!pickTitle} onClose={() => setPickTitle(null)} />;
  const touched = useRef({ list: false, rating: false }); // clicked before the server answered

  useEffect(() => {
    if (!open || !title?.id || !profileId) return undefined;
    let alive = true;
    touched.current = { list: false, rating: false };
    fetchMyList(profileId)
      // a click made before this answer arrived wins (the answer predates it)
      .then((items) => alive && !touched.current.list && setInList(items.some((i) => i.id === title.id)))
      .catch(() => alive && !touched.current.list && setInList(false));
    fetchRating({ profileId, titleId: title.id })
      .then((r) => alive && !touched.current.rating && setRatingState(r))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [open, title?.id, profileId]);

  if (!title) return picker;

  const toggleList = () => {
    const next = !inList;
    touched.current.list = true;
    setInList(next); // instant feedback, undone if the server refuses
    logActionBeacon({ title_id: title.id, action: 'add_to_list', surface, provider: next ? 'add' : 'remove' });
    setInMyList(profileId, title.id, next).catch(() => setInList(!next));
  };
  const rate = (value) => {
    const previous = rating;
    const next = rating === value ? null : value;
    touched.current.rating = true;
    setRatingState(next);
    setRating({ profileId, titleId: title.id, rating: next }).catch(() => setRatingState(previous));
  };
  const then = (fn) => () => {
    onClose();
    fn?.();
  };

  const isTv = String(title.type || '').toLowerCase() === 'tv';
  const resume = title.resume;
  const art = title.landscape_image || title.poster;
  const year = title.release_year || String(title.release_date || title.first_air_date || '').slice(0, 4);

  return (
    <>
    <Modal
      open={open}
      onClose={onClose}
      size="sm"
      scrollable={false}
      initialFocus="[data-autofocus]"
      className="title-options"
      title={
        <span className="title-options__head">
          {art ? <img src={tmdbImage(art, IMG.poster)} alt="" className="title-options__art" /> : null}
          <span className="title-options__text">
            <span className="title-options__name">{title.title}</span>
            <span className="title-options__meta">
              {isTv ? t('common:kind.tv') : t('common:kind.movie')}
              {year ? ` · ${year}` : ''}
              {Number(title.rating) > 0 ? <Rating value={title.rating} /> : null}
            </span>
          </span>
        </span>
      }
    >
      <ul className="ui-menu" aria-label={t('options.for', { title: title.title })}>
        <MenuItem
          autoFocus
          tone="primary"
          icon={<PlayIcon />}
          label={resume ? (resume.season ? t('options.resumeEpisode', { season: resume.season, episode: resume.episode }) : t('options.resume')) : t('options.play')}
          onClick={then(onPlay)}
        />
        <MenuItem icon={<InfoIcon />} label={isTv ? t('options.episodesInfo') : t('options.moreInfo')} onClick={then(onInfo)} />
        {profileId ? (
          <>
            {onRemoveFromList ? null : (
              <MenuItem
                icon={inList ? <CheckIcon /> : <PlusIcon />}
                label={inList ? t('options.inList') : t('options.addToList')}
                active={!!inList}
                onClick={toggleList}
              />
            )}
            <MenuItem icon={<ListPlusIcon />} label={t('lists.addToList')} onClick={then(() => setPickTitle(title))} />
            <MenuItem icon={<ThumbUpIcon />} label={t('rate.like')} active={rating === 'like'} onClick={() => rate('like')} />
            <MenuItem icon={<ThumbDownIcon />} label={t('rate.dislike')} active={rating === 'dislike'} onClick={() => rate('dislike')} />
          </>
        ) : null}
        {onRemoveResume || onNotInterested || onRemoveFromList ? <li className="ui-menu__sep" role="separator" /> : null}
        {onRemoveFromList ? (
          <MenuItem icon={<CloseIcon />} label={t('options.removeFromList')} onClick={then(onRemoveFromList)} />
        ) : null}
        {onRemoveResume ? (
          <MenuItem icon={<CloseIcon />} label={t('options.removeResume')} onClick={then(onRemoveResume)} />
        ) : null}
        {onNotInterested ? (
          <MenuItem tone="danger" icon={<BanIcon />} label={t('options.notInterested')} onClick={then(onNotInterested)} />
        ) : null}
      </ul>
    </Modal>
    {picker}
    </>
  );
}

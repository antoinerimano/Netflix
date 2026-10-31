// src/components/TitleOptions.js
// Options for one title, in a sheet (design Modal): Play / Resume, More info, My List, like /
// dislike, then the card's own actions (remove from Continue watching, not interested).
// Opened by holding OK on a TV remote, the remote's menu key, a right click, a long press on
// touch screens or the card's "⋯" button (see Row.js, tv/spatialNavigation.js).
import React, { useEffect, useState } from 'react';
import { Modal, Rating } from '../design';
import {
  PlayIcon, InfoIcon, PlusIcon, CheckIcon, ThumbUpIcon, ThumbDownIcon, BanIcon, CloseIcon,
} from '../design/icons';
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
export default function TitleOptions({ title, open, onClose, onPlay, onInfo, onRemoveResume, onNotInterested, surface = 'options' }) {
  const profileId = localStorage.getItem('activeProfileId');
  const [inList, setInList] = useState(null); // null: not known yet
  const [rating, setRatingState] = useState(null);

  useEffect(() => {
    if (!open || !title?.id || !profileId) return undefined;
    let alive = true;
    fetchMyList(profileId)
      .then((items) => alive && setInList(items.some((i) => i.id === title.id)))
      .catch(() => alive && setInList(false));
    fetchRating({ profileId, titleId: title.id })
      .then((r) => alive && setRatingState(r))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [open, title?.id, profileId]);

  if (!title) return null;

  const toggleList = () => {
    const next = !inList;
    setInList(next); // instant feedback, undone if the server refuses
    logActionBeacon({ title_id: title.id, action: 'add_to_list', surface, provider: next ? 'add' : 'remove' });
    setInMyList(profileId, title.id, next).catch(() => setInList(!next));
  };
  const rate = (value) => {
    const previous = rating;
    const next = rating === value ? null : value;
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
              {isTv ? 'Series' : 'Film'}
              {year ? ` · ${year}` : ''}
              {Number(title.rating) > 0 ? <Rating value={title.rating} /> : null}
            </span>
          </span>
        </span>
      }
    >
      <ul className="ui-menu" aria-label={`Options for ${title.title}`}>
        <MenuItem
          autoFocus
          tone="primary"
          icon={<PlayIcon />}
          label={resume ? (resume.season ? `Resume S${resume.season} · E${resume.episode}` : 'Resume') : 'Play'}
          onClick={then(onPlay)}
        />
        <MenuItem icon={<InfoIcon />} label={isTv ? 'Episodes & info' : 'More info'} onClick={then(onInfo)} />
        {profileId ? (
          <>
            <MenuItem
              icon={inList ? <CheckIcon /> : <PlusIcon />}
              label={inList ? 'In My List' : 'Add to My List'}
              active={!!inList}
              onClick={toggleList}
            />
            <MenuItem icon={<ThumbUpIcon />} label="I like this" active={rating === 'like'} onClick={() => rate('like')} />
            <MenuItem icon={<ThumbDownIcon />} label="Not for me" active={rating === 'dislike'} onClick={() => rate('dislike')} />
          </>
        ) : null}
        {onRemoveResume || onNotInterested ? <li className="ui-menu__sep" role="separator" /> : null}
        {onRemoveResume ? (
          <MenuItem icon={<CloseIcon />} label="Remove from Continue watching" onClick={then(onRemoveResume)} />
        ) : null}
        {onNotInterested ? (
          <MenuItem tone="danger" icon={<BanIcon />} label="Not interested" onClick={then(onNotInterested)} />
        ) : null}
      </ul>
    </Modal>
  );
}

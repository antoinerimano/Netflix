// src/components/collection/PartCard.jsx
// One movie of a franchise: its poster with its number in the watch order, a check once watched,
// "Coming soon" when it isn't out. Used by the collection page and the movie page's section.
import React from 'react';
import { useTranslation } from 'react-i18next';
import { CheckIcon } from '../../design/icons';
import { IMG, tmdbImage } from '../../utils/tmdbImage';

export default function PartCard({ part, current = false, onOpen }) {
  const { t } = useTranslation('catalog');
  const { title, position, watched, upcoming } = part;
  const state = current ? t('collection.thisOne') : watched ? t('collection.watched') : upcoming ? t('collection.comingSoon') : '';
  return (
    <button
      type="button"
      className={`coll-part${watched ? ' is-watched' : ''}${current ? ' is-current' : ''}`}
      aria-current={current ? 'page' : undefined}
      aria-label={[t('collection.part', { position }), title.title, title.release_year, state].filter(Boolean).join(', ')}
      onClick={() => onOpen(title)}
    >
      <span className="coll-part__art">
        {title.poster ? <img src={tmdbImage(title.poster, IMG.poster)} alt="" loading="lazy" decoding="async" /> : null}
        <span className="coll-part__num" aria-hidden="true">{position}</span>
        {watched ? (
          <span className="coll-part__check" aria-hidden="true"><CheckIcon /></span>
        ) : null}
      </span>
      <span className="coll-part__name">{title.title}</span>
      <span className="coll-part__meta">{[title.release_year, state].filter(Boolean).join(' · ')}</span>
    </button>
  );
}

// src/components/collection/CollectionSection.jsx
// "Part of The Godfather Collection" on a movie page: the franchise's movies in watch order (this
// one marked), watched ones checked, and a link to the collection page. Hidden for a movie alone.
// TV remote: one row (a group that starts on this movie); "Watch order" is its last tile, reached
// with Right from the last movie (a link above the row was out of reach from the other movies).
import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { fetchCollection } from '../../api/recoApi';
import { SectionTitle } from '../../design';
import { ChevronRightIcon } from '../../design/icons';
import PartCard from './PartCard';
import './collection.css';

export default function CollectionSection({ collectionId, titleId }) {
  const { t } = useTranslation('catalog');
  const navigate = useNavigate();
  const profileId = localStorage.getItem('activeProfileId');
  const [data, setData] = useState(null);

  useEffect(() => {
    if (!collectionId || !profileId) return undefined;
    let alive = true;
    setData(null);
    fetchCollection(profileId, collectionId)
      .then((d) => alive && setData(d))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [collectionId, profileId]);

  if (!data || data.parts.length < 2) return null;

  return (
    <section className="detail-section coll-section" aria-labelledby="coll-section-title">
      <SectionTitle id="coll-section-title">{t('collection.partOf', { name: data.name })}</SectionTitle>
      <p className="coll-section__progress">
        {t('collection.progress', { watched: data.watched, total: data.total })}
      </p>
      <ul className="ui-scroller coll-section__row" data-tv-group>
        {data.parts.map((p) => (
          <li key={p.title.id}>
            <PartCard part={p} current={p.title.id === Number(titleId)} onOpen={(title) => navigate(`/movies/${title.id}`)} />
          </li>
        ))}
        <li>
          <button type="button" className="coll-more" onClick={() => navigate(`/collection/${data.id}`)}>
            <span className="coll-more__tile" aria-hidden="true"><ChevronRightIcon /></span>
            <span className="coll-part__name">{t('collection.order')}</span>
          </button>
        </li>
      </ul>
    </section>
  );
}

// src/components/detail/MoreLikeThis.js
// "More like this" on movie / show pages: a scrolling row of poster cards (same cards and
// options sheet as the grids). Hidden when there is nothing similar.
import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchSimilarTitles } from '../../api/titlesApi';
import { SectionTitle, Skeleton } from '../../design';
import MovieCard from '../MovieCard';
import '../PosterCard.css';

export default function MoreLikeThis({ titleId }) {
  const { t } = useTranslation('catalog');
  const [items, setItems] = useState(null); // null: loading

  useEffect(() => {
    if (!titleId) return undefined;
    let alive = true;
    setItems(null);
    fetchSimilarTitles(titleId)
      .then((list) => alive && setItems(list))
      .catch(() => alive && setItems([]));
    return () => {
      alive = false;
    };
  }, [titleId]);

  if (items && !items.length) return null;

  return (
    <section className="detail-section" aria-label={t('detail.moreLikeThis')}>
      <SectionTitle>{t('detail.moreLikeThis')}</SectionTitle>
      <ul className="ui-scroller detail-similar">
        {items
          ? items.map((t, idx) => (
              <li key={t.id}>
                <MovieCard movie={t} analytics={{ surface: 'more_like_this', position: idx, row_title: 'More like this' }} />
              </li>
            ))
          : Array.from({ length: 7 }, (_, i) => (
              <li key={i}>
                <Skeleton style={{ aspectRatio: '2 / 3' }} />
              </li>
            ))}
      </ul>
    </section>
  );
}

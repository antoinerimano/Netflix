// src/components/detail/MoreLikeThis.js
// "More like this" on movie / show pages: a scrolling row of poster cards (same cards and
// options sheet as the grids). Hidden when there is nothing similar.
// Measured (roadmap 8.7, backend reco/ai_report.py): once the row comes on screen, each card is
// logged as shown with where it came from ("more_like_this:tmdb" / "more_like_this:embeddings");
// clicks are logged by the cards (surface "more_like_this").
import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchSimilarTitles } from '../../api/titlesApi';
import { logImpressions } from '../../api/analyticsApi';
import { SectionTitle, Skeleton } from '../../design';
import MovieCard from '../MovieCard';
import '../PosterCard.css';

export default function MoreLikeThis({ titleId }) {
  const { t } = useTranslation('catalog');
  const [items, setItems] = useState(null); // null: loading
  const sectionRef = useRef(null);

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

  // shown: logged once per title page, when the row comes on screen (no browser support: at once)
  useEffect(() => {
    const node = sectionRef.current;
    if (!items?.length || !node) return undefined;
    const log = () =>
      logImpressions({
        items: items.map((it, position) => ({
          title_id: it.id,
          position,
          row_type: `more_like_this:${it.source === 'tmdb' ? 'tmdb' : 'embeddings'}`,
        })),
      }).catch(() => {});
    if (typeof IntersectionObserver === 'undefined') {
      log();
      return undefined;
    }
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        observer.disconnect();
        log();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [items]);

  if (items && !items.length) return null;

  return (
    <section ref={sectionRef} className="detail-section" aria-label={t('detail.moreLikeThis')}>
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

// The trailer preview inside a home row card (previewStore.js decides when). Rendered only while
// the card is the one being previewed: other cards have no <video> at all.
import React, { useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import { previewStore, usePreviewMuted, usePreviewPhase } from './previewStore';
import { VolumeOnIcon, VolumeOffIcon } from '../../design/icons';

export default function CardPreview({ previewKey, src, poster }) {
  const { t } = useTranslation('catalog');
  const phase = usePreviewPhase(previewKey);
  const muted = usePreviewMuted();
  const ref = useRef(null);
  const showing = phase === 'showing';

  useEffect(() => {
    if (ref.current) ref.current.muted = muted;
  }, [muted, phase]);

  useEffect(() => {
    const v = ref.current;
    if (!v || !showing) return;
    v.play()?.catch((err) => {
      // sound without a click is refused by browsers: play it muted instead
      if (err?.name === 'NotAllowedError' && !v.muted) {
        v.muted = true;
        v.play()?.catch(() => previewStore.fail(previewKey, src));
      } else if (err?.name !== 'AbortError') {
        previewStore.fail(previewKey, src);
      }
    });
  }, [showing, previewKey, src]);

  if (phase === 'idle' || phase === 'arming') return null;

  return (
    <>
      <video
        ref={ref}
        className={`row-preview${showing ? ' is-showing' : ''}`}
        src={src}
        poster={poster}
        muted={muted}
        loop
        playsInline
        preload="auto"
        aria-hidden="true"
        tabIndex={-1}
        onCanPlay={() => previewStore.ready(previewKey)}
        onError={() => previewStore.fail(previewKey, src)}
      />
      {showing ? (
        // mouse only: the remote's focus order stays card to card
        <button
          type="button"
          tabIndex={-1}
          className="row-unmute-btn row-card-btn"
          onClick={(e) => {
            e.stopPropagation();
            previewStore.setMuted(!muted);
          }}
          aria-label={muted ? t('trailer.unmuteLabel') : t('trailer.muteLabel')}
          title={muted ? t('trailer.unmute') : t('trailer.mute')}
        >
          {muted ? <VolumeOffIcon /> : <VolumeOnIcon />}
        </button>
      ) : null}
    </>
  );
}

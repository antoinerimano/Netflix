// src/components/detail/RecapButton.jsx
// "Catch me up" on a show page (backend reco/recap.py): shown only when the profile is somewhere
// past the first episode. Opens a dialog with an AI-written recap of everything before the
// episode it resumes at (no spoilers), and "Resume S2 E4" to carry on. The recap is written
// the first time it's asked for (a few seconds: the brand loader meanwhile), then kept.
// Remote: the button sits in the hero's action row; in the dialog the focus starts on Resume,
// Up reaches the text (scrolls with the arrows), Back closes it and returns to the button.
import React, { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { fetchRecap } from '../../api/recoApi';
import { Button, Modal, Spinner, friendlyError } from '../../design';
import { PlayIcon, WandIcon } from '../../design/icons';

export default function RecapButton({ titleId, profileId, onResume }) {
  const { t, i18n } = useTranslation('catalog');
  const lng = i18n.resolvedLanguage;
  const [point, setPoint] = useState(null); // {season, episode} when there is something to recap
  const [open, setOpen] = useState(false);
  const [recap, setRecap] = useState({ loading: false, text: '', error: '' });

  useEffect(() => {
    let alive = true;
    setPoint(null);
    if (!titleId || !profileId) return undefined;
    fetchRecap(profileId, titleId, { peek: true })
      .then((r) => alive && setPoint(r?.available ? { season: r.season, episode: r.episode } : null))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [titleId, profileId]);

  const load = useCallback(() => {
    setRecap({ loading: true, text: '', error: '' });
    fetchRecap(profileId, titleId)
      .then((r) => setRecap({ loading: false, text: r?.text || '', error: r?.text ? '' : t('recap.error') }))
      .catch((e) => {
        const status = e?.response?.status;
        const error = status === 503 || status === 429 ? t('recap.error') : friendlyError(e, 'show');
        setRecap({ loading: false, text: '', error });
      });
  }, [profileId, titleId, t]);

  // a recap in another language is another recap
  useEffect(() => setRecap({ loading: false, text: '', error: '' }), [lng, titleId, profileId]);

  if (!point) return null;

  const openDialog = () => {
    setOpen(true);
    if (!recap.text && !recap.loading) load();
  };
  const where = { season: point.season, episode: point.episode };

  return (
    <>
      <Button variant="glass" icon={<WandIcon />} onClick={openDialog}>
        {t('recap.button')}
      </Button>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={t('recap.title')}
        className="recap-dialog"
        initialFocus={recap.error ? '.recap-retry' : '.recap-resume'}
        footer={
          <>
            {recap.error ? (
              <Button variant="ghost" className="recap-retry" onClick={load}>
                {t('recap.retry')}
              </Button>
            ) : null}
            <Button
              variant="primary"
              icon={<PlayIcon />}
              className="recap-resume"
              onClick={() => onResume?.(point.season, point.episode)}
            >
              {t('recap.resume', where)}
            </Button>
          </>
        }
      >
        <p className="recap-dialog__scope">{t('recap.scope', where)}</p>
        {recap.loading ? (
          <div className="recap-dialog__loading" role="status">
            <Spinner size={48} />
            <span>{t('recap.loading')}</span>
          </div>
        ) : recap.error ? (
          <p className="recap-dialog__error" role="alert">
            {recap.error}
          </p>
        ) : (
          <div className="recap-dialog__text">
            {recap.text
              .split(/\n\s*\n/)
              .filter((p) => p.trim())
              .map((p, i) => (
                <p key={i}>{p.trim()}</p>
              ))}
            <p className="recap-dialog__note">{t('recap.note')}</p>
          </div>
        )}
      </Modal>
    </>
  );
}

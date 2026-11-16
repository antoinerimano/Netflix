// src/components/ask/AskPage.jsx
// "Ask Taurus" (/ask, backend reco/ask.py): say what you feel like watching, get 4-6 titles from
// the catalog and 3 follow-ups to tap. No typing needed on a TV: starters before the first
// question, then the follow-ups (chips) of the last answer; the field is there for a keyboard.
// Remote: Down from the top reaches the starters (the row lands on the first); after an answer the
// focus goes to the first title, Down reaches the follow-ups, then the field and "Start over".
// Caps (backend reco/ai_budget.py): a reached cap says "come back tomorrow", nothing else breaks.
// Measured like 8.7: suggestions logged as shown ("ask") and clicked (surface "ask").
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { askTaurus } from '../../api/recoApi';
import { logImpressions, logTitleClick } from '../../api/analyticsApi';
import { Button, Chip, Spinner, friendlyError } from '../../design';
import { formatRuntime } from '../../i18n/format';
import { IMG, tmdbImage } from '../../utils/tmdbImage';
import '../PosterCard.css';
import '../pick/pick.css';
import './ask.css';

const STARTERS = ['funny', 'scary', 'series', 'feelgood'];
const MAX_MESSAGE = 300;

export default function AskPage() {
  const { t, i18n } = useTranslation('catalog');
  const navigate = useNavigate();
  const profileId = localStorage.getItem('activeProfileId');
  const [turns, setTurns] = useState([]); // [{message, reply, items, chips}]
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null); // {limit: bool, text}
  const focusAnswer = useRef(false);

  const ask = useCallback(
    async (message) => {
      const text = String(message || '').trim().slice(0, MAX_MESSAGE);
      if (!text || loading) return;
      setLoading(true);
      setError(null);
      try {
        const history = turns.map(({ message: m, reply }) => ({ message: m, reply }));
        const data = await askTaurus(profileId, text, history);
        const items = data.items || [];
        logImpressions({ items: items.map((it, position) => ({ title_id: it.id, position })), row_type: 'ask' }).catch(() => {});
        focusAnswer.current = true;
        setTurns((prev) => [...prev, { message: text, reply: data.reply || '', items, chips: data.chips || [] }]);
        setDraft('');
      } catch (e) {
        const limit = e?.response?.data?.code === 'ai_budget';
        let errorText = friendlyError(e, 'page');
        if (limit) errorText = t('ask.limit');
        else if (e?.response?.status === 503) errorText = t('ask.error');
        setError({ limit, text: errorText });
      } finally {
        setLoading(false);
      }
    },
    [loading, turns, profileId, t]
  );

  // the remote follows the answer: the first title, else the first follow-up
  useEffect(() => {
    if (!focusAnswer.current || !turns.length) return;
    focusAnswer.current = false;
    document.querySelector('.ask-turn:last-of-type .pick-card, .ask-turn:last-of-type .ask-chips button')?.focus();
  }, [turns]);

  const open = (item, position) => {
    logTitleClick({ title_id: item.id, surface: 'ask', position });
    navigate(item.type === 'tv' ? `/tv/${item.id}` : `/movies/${item.id}`);
  };
  const minutes = (item) => (item.minutes ? formatRuntime(item.minutes, i18n.resolvedLanguage) : '');
  const last = turns[turns.length - 1];
  const chips = last ? last.chips : STARTERS.map((k) => t(`ask.starters.${k}`));

  return (
    <div className="pick-page">
      <Navbar />
      <main className="pick ask">
        <header className="pick__head">
          <h1 className="pick__title">{t('ask.title')}</h1>
          <p className="pick__subtitle">{t('ask.subtitle')}</p>
        </header>

        {turns.map((turn, i) => (
          <section key={i} className="ask-turn" aria-label={turn.message}>
            <p className="ask-turn__question">{turn.message}</p>
            {turn.reply ? <p className="ask-turn__reply">{turn.reply}</p> : null}
            {turn.items.length ? (
              <ul className="pick-results" data-tv-group>
                {turn.items.map((item, position) => (
                  <li key={item.id}>
                    <button type="button" className="pick-card" onClick={() => open(item, position)}>
                      <span className="pick-card__art">
                        <span className="poster-card__fallback">{item.title}</span>
                        {item.poster ? <img src={tmdbImage(item.poster, IMG.poster)} alt="" loading="lazy" decoding="async" /> : null}
                        {minutes(item) ? <span className="pick-card__time">{minutes(item)}</span> : null}
                      </span>
                      <span className="pick-card__name">{item.title}</span>
                      <span className="pick-card__meta">
                        {[t(item.type === 'tv' ? 'common:kind.tv' : 'common:kind.movie'), item.release_year].filter(Boolean).join(' · ')}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>
        ))}

        {loading ? (
          <div className="ask-loading" role="status">
            <Spinner size={48} />
            <span>{t('ask.thinking')}</span>
          </div>
        ) : null}
        {error ? <p className="ask-error" role="alert">{error.text}</p> : null}

        {!error?.limit ? (
          <>
            {chips.length ? (
              <div className="pick-choices__row ask-chips" role="group" aria-label={t(last ? 'ask.followUps' : 'ask.startersLabel')} data-tv-group>
                {chips.map((c, i) => (
                  <Chip key={c} onClick={() => ask(c)} disabled={loading} data-tv-current={!last && i === 0 ? true : undefined}>
                    {c}
                  </Chip>
                ))}
              </div>
            ) : null}
            <form
              className="ask-form"
              onSubmit={(e) => {
                e.preventDefault();
                ask(draft);
              }}
            >
              <input
                className="ui-input ask-form__input"
                type="text"
                value={draft}
                maxLength={MAX_MESSAGE}
                placeholder={t('ask.placeholder')}
                aria-label={t('ask.inputLabel')}
                onChange={(e) => setDraft(e.target.value)}
              />
              <Button type="submit" variant="primary" loading={loading} disabled={!draft.trim()}>
                {t('ask.send')}
              </Button>
              {turns.length ? (
                <Button variant="ghost" onClick={() => { setTurns([]); setError(null); }}>
                  {t('ask.startOver')}
                </Button>
              ) : null}
            </form>
          </>
        ) : null}
        <p className="ask-note">{t('ask.note')}</p>
      </main>
      <Footer />
    </div>
  );
}

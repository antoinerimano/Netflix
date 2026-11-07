// src/components/pick/PickPage.jsx
// "What to watch?" (/pick, "Surprise me" on the home banner): choose the time you have and a mood,
// then "Show me" (6 titles that fit, a new set each time) or "Surprise me" (one, big, with Play /
// More info / Another one). Backend reco/pick.py. /pick?surprise=1 opens straight on a surprise.
// TV remote: two rows of choices (groups that land on the selected one), then the two buttons,
// then the results; after "Show me" / "Another one" the focus moves to what came out.
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { fetchPicks } from '../../api/recoApi';
import { Button, Chip, EmptyState, Skeleton, friendlyError } from '../../design';
import { DiceIcon, InfoIcon, PlayIcon } from '../../design/icons';
import { formatRuntime } from '../../i18n/format';
import { IMG, tmdbBackground, tmdbImage } from '../../utils/tmdbImage';
import '../PosterCard.css';
import './pick.css';

const TIMES = ['90', '120', 'episode', 'any'];
const MOODS = ['any', 'funny', 'exciting', 'scary', 'feelgood', 'thoughtful', 'romantic'];

function ChoiceRow({ id, label, options, value, onChange, text }) {
  return (
    <div className="pick-choices">
      <p id={id} className="pick-choices__label">{label}</p>
      <div className="pick-choices__row" role="group" aria-labelledby={id} data-tv-group>
        {options.map((o) => (
          <Chip key={o} selected={o === value} onClick={() => onChange(o)}>{text(o)}</Chip>
        ))}
      </div>
    </div>
  );
}

export default function PickPage() {
  const { t, i18n } = useTranslation('catalog');
  const navigate = useNavigate();
  const location = useLocation();
  const profileId = localStorage.getItem('activeProfileId');
  const [time, setTime] = useState('90');
  const [mood, setMood] = useState('any');
  const [result, setResult] = useState(null); // { mode: 'list' | 'surprise', items, candidates }
  const [loading, setLoading] = useState(null); // 'list' | 'surprise' | null
  const [error, setError] = useState(null);
  const shown = useRef(new Set()); // titles already shown: "Show me" again gives new ones
  const focusResult = useRef(false);

  // choices: given when they were just set (the state isn't updated yet in the same click)
  const go = useCallback(
    async (mode, choices = {}) => {
      setLoading(mode);
      setError(null);
      try {
        const data = await fetchPicks(profileId, {
          time: choices.time || time,
          mood: choices.mood || mood,
          count: mode === 'surprise' ? 1 : 6,
          exclude: [...shown.current],
        });
        data.items.forEach((i) => shown.current.add(i.id));
        // the remote follows what came out, unless the press came from the surprise itself
        // ("Another one" again and again stays on "Another one")
        focusResult.current = !document.activeElement?.closest?.('.pick-surprise');
        setResult({ mode, ...data });
      } catch (e) {
        setError(e);
      } finally {
        setLoading(null);
      }
    },
    [profileId, time, mood]
  );

  // a new choice starts over (what was shown for other choices may fit these)
  useEffect(() => {
    shown.current = new Set();
  }, [time, mood]);

  // /pick?surprise=1 (the home banner's "Surprise me"): straight to one title
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current) return;
    opened.current = true;
    if (new URLSearchParams(location.search).get('surprise')) {
      setTime('any');
      go('surprise', { time: 'any' });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps -- once, on arrival

  // the remote follows what came out
  useEffect(() => {
    if (!focusResult.current || !result) return;
    focusResult.current = false;
    document.querySelector('.pick-surprise .ui-btn--primary, .pick-results .pick-card')?.focus();
  }, [result]);

  const open = (item) => navigate(item.type === 'tv' ? `/tv/${item.id}` : `/movies/${item.id}`);
  const minutes = (item) => (item.type === 'tv'
    ? t('pick.perEpisode', { time: formatRuntime(item.minutes, i18n.resolvedLanguage) })
    : formatRuntime(item.minutes, i18n.resolvedLanguage));

  let body = null;
  if (error) {
    body = <EmptyState tone="error" title={t('pick.loadError')}>{friendlyError(error)}</EmptyState>;
  } else if (loading && !result) {
    body = <div className="pick-results">{[0, 1, 2, 3, 4, 5].map((i) => <Skeleton key={i} style={{ aspectRatio: '2 / 3' }} />)}</div>;
  } else if (result && !result.items.length) {
    body = (
      <EmptyState title={t('pick.noneTitle')}>
        {result.candidates === 0 ? t('pick.noneText') : t('pick.allShownText')}
      </EmptyState>
    );
  } else if (result?.mode === 'surprise') {
    const item = result.items[0];
    body = (
      <section className="pick-surprise" aria-live="polite" aria-labelledby="pick-surprise-title"
        style={{ backgroundImage: tmdbBackground(item.landscape_image || item.poster, IMG.backdropHero) }}>
        <div className="pick-surprise__shade" />
        <div className="pick-surprise__content">
          <p className="pick-surprise__kicker">{t('pick.yourPick')}</p>
          <h2 id="pick-surprise-title" className="pick-surprise__title">{item.title}</h2>
          <p className="pick-surprise__meta">
            {[t(item.type === 'tv' ? 'common:kind.tv' : 'common:kind.movie'), item.release_year, minutes(item)].filter(Boolean).join(' · ')}
          </p>
          {item.description ? <p className="pick-surprise__desc">{item.description}</p> : null}
          <div className="pick-surprise__actions" data-tv-group>
            <Button variant="primary" size="lg" icon={<PlayIcon />} onClick={() => navigate(`/watch/${item.id}`)} data-tv-current>{t('detail.watch')}</Button>
            <Button variant="glass" size="lg" icon={<InfoIcon />} onClick={() => open(item)}>{t('pick.moreInfo')}</Button>
            <Button variant="glass" size="lg" icon={<DiceIcon />} loading={loading === 'surprise'} onClick={() => go('surprise')}>{t('pick.another')}</Button>
          </div>
        </div>
      </section>
    );
  } else if (result) {
    body = (
      <ul className="pick-results" data-tv-group aria-live="polite">
        {result.items.map((item) => (
          <li key={item.id}>
            <button type="button" className="pick-card" onClick={() => open(item)}>
              <span className="pick-card__art">
                <span className="poster-card__fallback">{item.title}</span>
                {item.poster ? <img src={tmdbImage(item.poster, IMG.poster)} alt="" loading="lazy" decoding="async" /> : null}
                <span className="pick-card__time">{minutes(item)}</span>
              </span>
              <span className="pick-card__name">{item.title}</span>
              <span className="pick-card__meta">{[t(item.type === 'tv' ? 'common:kind.tv' : 'common:kind.movie'), item.release_year].filter(Boolean).join(' · ')}</span>
            </button>
          </li>
        ))}
      </ul>
    );
  }

  return (
    <div className="pick-page">
      <Navbar />
      <main className="pick">
        <header className="pick__head">
          <h1 className="pick__title">{t('pick.title')}</h1>
          <p className="pick__subtitle">{t('pick.subtitle')}</p>
        </header>
        <ChoiceRow id="pick-time" label={t('pick.time')} options={TIMES} value={time} onChange={setTime} text={(o) => t(`pick.times.${o}`)} />
        <ChoiceRow id="pick-mood" label={t('pick.mood')} options={MOODS} value={mood} onChange={setMood} text={(o) => t(`pick.moods.${o}`)} />
        <div className="pick__actions">
          <Button variant="primary" loading={loading === 'list'} onClick={() => go('list')}>
            {result?.mode === 'list' ? t('pick.showMore') : t('pick.show')}
          </Button>
          <Button variant="glass" icon={<DiceIcon />} loading={loading === 'surprise' && result?.mode !== 'surprise'} onClick={() => go('surprise')}>
            {t('pick.surprise')}
          </Button>
        </div>
        {body}
      </main>
      <Footer />
    </div>
  );
}

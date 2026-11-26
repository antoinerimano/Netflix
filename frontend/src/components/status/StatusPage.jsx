// src/components/status/StatusPage.jsx
// /status (ROADMAP 9.8), public: is Taurus up, and each source's last checks (the health check
// every 15 min, the provider scout's nightly playback test, how the viewers' plays went and the
// problems reported in the last 24 h; backend reco/problems.py). "Test from my connection" tries
// every source's site from this browser: up for everyone but not reachable from here = your
// network or a blocker, not the source.
// TV remote: the test button, then each source is a stop (Down scrolls through them).
import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import Navbar from '../Navbar';
import Footer from '../Footer';
import { Button, Skeleton } from '../../design';
import { formatDate, formatNumber, formatRelative } from '../../i18n/format';
import { fetchStatus, reachable, whoIsAffected } from '../../api/problemsApi';
import './status.css';

function SourceRow({ s, affected, t, lng }) {
  const lines = [];
  lines.push(s.checked_at ? t('status.checked', { when: formatRelative(s.checked_at, lng) }) : t('status.neverChecked'));
  if (s.scout) {
    const date = formatDate(s.scout.date, { dateStyle: 'medium' }, lng);
    lines.push(
      s.scout.tested
        ? t('status.scout', { played: s.scout.played, tested: s.scout.tested, date })
        : t('status.scoutNoVerdict', { date })
    );
  }
  if (s.played_share_24h != null) {
    lines.push(t('status.viewers', { share: formatNumber(s.played_share_24h, { style: 'percent' }, lng) }));
  }
  if (s.reports_24h) lines.push(t('status.reports', { reports: formatNumber(s.reports_24h, undefined, lng) }));

  const state = t(`status.states.${s.state}`);
  return (
    <li className={`status-source status-source--${s.state}`} tabIndex={0} aria-label={`${s.label}: ${state}`}>
      <div className="status-source__head">
        <span className="status-source__dot" aria-hidden="true" />
        <strong className="status-source__name">{s.label}</strong>
        <span className="status-source__state">{state}</span>
      </div>
      <ul className="status-source__lines">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      {affected ? (
        <p className={`status-source__you status-source__you--${affected}`}>{t(`status.affected.${affected}`)}</p>
      ) : null}
    </li>
  );
}

export default function StatusPage() {
  const { t, i18n } = useTranslation('watch');
  const lng = i18n.resolvedLanguage;
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [reach, setReach] = useState(null); // { key: true | false } once tested from here
  const [testing, setTesting] = useState(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    fetchStatus()
      .then((d) => alive.current && setData(d))
      .catch(() => alive.current && setFailed(true));
    return () => {
      alive.current = false;
    };
  }, []);

  const testHere = useCallback(async () => {
    if (!data || testing) return;
    setTesting(true);
    const results = await Promise.all(data.sources.map(async (s) => [s.key, await reachable(s.domain)]));
    if (!alive.current) return;
    setReach(Object.fromEntries(results));
    setTesting(false);
  }, [data, testing]);

  const sources = data?.sources || [];
  const blockedHere = reach ? sources.filter((s) => whoIsAffected(s, reach) === 'you').length : 0;
  const working = sources.filter((s) => s.state !== 'down').length; // not checked yet isn't down

  let summary = null;
  if (failed) summary = { tone: 'down', title: t('status.siteDown'), text: t('status.siteDownText') };
  else if (data) {
    summary = {
      tone: working ? 'up' : 'problems',
      title: t('status.siteUp'),
      text: working ? t('status.sourcesWorking', { working, total: sources.length }) : t('status.noSourceWorking'),
    };
  }

  return (
    <div className="status-page">
      <Navbar />
      <main className="status">
        <header className="status__head">
          <h1 className="status__title">{t('status.title')}</h1>
          <p className="status__subtitle">{t('status.subtitle')}</p>
        </header>

        {summary ? (
          <section className={`status__summary status__summary--${summary.tone}`} role="status">
            <span className="status-source__dot" aria-hidden="true" />
            <div>
              <h2 className="status__summaryTitle">{summary.title}</h2>
              <p className="status__summaryText">{summary.text}</p>
              {data?.generated_at ? (
                <p className="status__updated">{t('status.updated', { when: formatRelative(data.generated_at, lng) })}</p>
              ) : null}
            </div>
          </section>
        ) : (
          <Skeleton className="status__summary" height="6rem" />
        )}

        {data ? (
          <>
            <section className="status__test">
              <p className="status__testText">{t('status.testText')}</p>
              <Button variant="primary" onClick={testHere} aria-busy={testing ? 'true' : undefined} className="status__testBtn">
                {testing ? t('status.testing') : reach ? t('status.testAgain') : t('status.test')}
              </Button>
              {reach ? (
                <p className="status__testResult" role="status">
                  {blockedHere ? t('status.blockedHere', { blocked: blockedHere }) : t('status.allReachable')}
                </p>
              ) : null}
            </section>

            <section aria-labelledby="status-sources">
              <h2 id="status-sources" className="status__sectionTitle">{t('status.sources')}</h2>
              {sources.length ? (
                <ul className="status__sources">
                  {sources.map((s) => (
                    <SourceRow key={s.key} s={s} affected={whoIsAffected(s, reach)} t={t} lng={lng} />
                  ))}
                </ul>
              ) : (
                <p className="status__subtitle">{t('status.noSources')}</p>
              )}
              <p className="status__note">{t('status.note')}</p>
            </section>
          </>
        ) : null}
      </main>
      <Footer />
    </div>
  );
}

// src/components/Footer.js
// Site footer + the DMCA notice (design system Modal: scrolls inside, closes with ×, Escape,
// a click outside or the TV remote's Back).
import React, { useState } from 'react';
import { Trans, useTranslation } from 'react-i18next';
import { Button, Modal } from '../design';
import LanguagePicker from './LanguagePicker';
import './Footer.css';

const CONTACT = 'taurusadmin@proton.me';

function DmcaNotice() {
  const { t } = useTranslation('legal');
  const items = t('dmca.noticeItems', { returnObjects: true });
  return (
    <div className="ui-prose">
      <p>{t('dmca.intro')}</p>
      <p>{t('dmca.liability')}</p>

      <h3>{t('dmca.filingTitle')}</h3>
      <p>{t('dmca.filingText')}</p>
      <ol>
        {(Array.isArray(items) ? items : []).map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ol>

      <h3>{t('dmca.contactTitle')}</h3>
      <p>
        <Trans t={t} i18nKey="dmca.contactText" values={{ email: CONTACT }} components={{ mail: <a href={`mailto:${CONTACT}`}>{CONTACT}</a> }} />
      </p>
    </div>
  );
}

export default function Footer() {
  const { t } = useTranslation();
  const [dmcaOpen, setDmcaOpen] = useState(false);

  return (
    <footer className="site-footer">
      <div className="site-footer__links">
        <button type="button" className="site-footer__link" onClick={() => setDmcaOpen(true)}>
          {t('footer.dmca')}
        </button>
        <a className="site-footer__link" href={`mailto:${CONTACT}`}>
          {t('footer.contact')}
        </a>
        <LanguagePicker compact className="site-footer__language" />
      </div>
      <p className="site-footer__copy">{t('footer.copyright', { year: new Date().getFullYear() })}</p>

      <Modal
        open={dmcaOpen}
        onClose={() => setDmcaOpen(false)}
        title={t('footer.dmca')}
        size="lg"
        footer={
          <Button variant="secondary" onClick={() => setDmcaOpen(false)}>
            {t('actions.close')}
          </Button>
        }
      >
        <DmcaNotice />
      </Modal>
    </footer>
  );
}

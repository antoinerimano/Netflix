// src/components/Footer.js
// Site footer + the DMCA notice (design system Modal: scrolls inside, closes with ×, Escape,
// a click outside or the TV remote's Back).
import React, { useState } from 'react';
import { Button, Modal } from '../design';
import './Footer.css';

const CONTACT = 'taurusadmin@proton.me';

function DmcaNotice() {
  return (
    <div className="ui-prose">
      <p>
        In accordance with the Digital Millennium Copyright Act of 1998, Tauruss will respond
        expeditiously to claims of copyright infringement that are reported to its designated
        copyright agent identified below.
      </p>
      <p>
        Under Section 512(f), any person who knowingly materially misrepresents that material or
        activity is infringing may be subject to liability. Tauruss reserves the right, at its sole
        discretion, to remove content and terminate the accounts of users who infringe, or appear to
        infringe, the intellectual property or other rights of third parties.
      </p>

      <h3>Filing a notice</h3>
      <p>If you believe your copyrighted work has been copied in a way that constitutes infringement, please send our copyright agent:</p>
      <ol>
        <li>A physical or electronic signature of a person authorized to act on behalf of the owner of the exclusive right allegedly infringed.</li>
        <li>Identification of the copyrighted work claimed to have been infringed (or a representative list if several works are covered by one notice).</li>
        <li>Identification of the material claimed to be infringing, with information reasonably sufficient for us to locate it.</li>
        <li>Your contact information: name, address, telephone number and, if available, an email address.</li>
        <li>A statement that you have a good-faith belief that the use is not authorized by the copyright owner, its agent or the law.</li>
        <li>A statement that the information in the notice is accurate and, under penalty of perjury, that you are authorized to act on behalf of the owner of the exclusive right.</li>
      </ol>

      <h3>Copyright contact</h3>
      <p>
        Email <a href={`mailto:${CONTACT}`}>{CONTACT}</a>. We apologize for any misuse of our service
        and will do our best to find and remove infringing files.
      </p>
    </div>
  );
}

export default function Footer() {
  const [dmcaOpen, setDmcaOpen] = useState(false);

  return (
    <footer className="site-footer">
      <div className="site-footer__links">
        <button type="button" className="site-footer__link" onClick={() => setDmcaOpen(true)}>
          DMCA notice
        </button>
        <a className="site-footer__link" href={`mailto:${CONTACT}`}>
          Contact
        </a>
      </div>
      <p className="site-footer__copy">© {new Date().getFullYear()} Tauruss. All rights reserved.</p>

      <Modal
        open={dmcaOpen}
        onClose={() => setDmcaOpen(false)}
        title="DMCA notice"
        size="lg"
        footer={
          <Button variant="secondary" onClick={() => setDmcaOpen(false)}>
            Close
          </Button>
        }
      >
        <DmcaNotice />
      </Modal>
    </footer>
  );
}

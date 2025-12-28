// src/pages/HomePage.jsx
import React, { useEffect, useMemo, useState } from "react";
import Navbar from "../components/Navbar";
import Hero from "../components/Hero";
import Row from "../components/Row";
import { fetchHomeRecoRows } from "../api/recoApi";


const FAKE_STEPS = [
  { pct: 3, label: "Loading ranker..." },
  { pct: 10, label: "Building profile vector..." },
  { pct: 18, label: "Fetching recent actions..." },
  { pct: 26, label: "Computing seen titles..." },
  { pct: 40, label: "Planning rows (genres, studios, actors)..." },
  { pct: 55, label: "Collecting candidates..." },
  { pct: 68, label: "Fetching titles..." },
  { pct: 78, label: "Fetching embeddings..." },
  { pct: 88, label: "Ranking rows..." },
  { pct: 95, label: "Finalizing payload..." },
  { pct: 100, label: "Done" },
];

const ROW_SIZE = 18;

const HomePage = () => {
  const [loading, setLoading] = useState(true);
  const [msgOpen, setMsgOpen] = useState(false);

  const openMsg = () => setMsgOpen(true);
  const closeMsg = () => setMsgOpen(false);

  const [heroPick, setHeroPick] = useState(null);
  const [progress, setProgress] = useState(0);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [loadingStep, setLoadingStep] = useState("Starting...");

  const [loadingLabel, setLoadingLabel] = useState("Getting recommended content...");
  const [stepIndex, setStepIndex] = useState(0);

  // rows backend
  const [homeRows, setHomeRows] = useState([]); // [{row_type,title,items:[...]}, ...]
  const [profileId, setProfileId] = useState(() => localStorage.getItem("activeProfileId"));

  useEffect(() => {
    if (!loading) return;

    const step =
      FAKE_STEPS.slice().reverse().find((s) => progress >= s.pct)?.label ||
      "Starting...";

    setLoadingStep(step);
  }, [progress, loading]);



  useEffect(() => {
    const onChange = () => setProfileId(localStorage.getItem("activeProfileId"));
    window.addEventListener("activeProfileChanged", onChange);
    return () => window.removeEventListener("activeProfileChanged", onChange);
  }, []);

  // --- Fetch backend reco rows ---
  useEffect(() => {

    let alive = true;
    const pid = localStorage.getItem("activeProfileId");

    // helper: fake progress calibré ~15s
    let timer = null;
    let startedAt = 0;

    const startFakeProgress15s = (durationMs = 15000, cap = 95) => {
      const safeDurationMs = Number(durationMs);
      const safeCap = Number(cap);

      const D = Number.isFinite(safeDurationMs) && safeDurationMs > 0 ? safeDurationMs : 15000;
      const C = Number.isFinite(safeCap) && safeCap > 0 ? safeCap : 95;

      startedAt = Date.now();
      setProgress(0);
      setElapsedSec(Math.ceil(D / 1000));
      setStepIndex(0);
      setLoadingLabel(FAKE_STEPS[0].label);

      let logged = false;

      timer = setInterval(() => {
        const elapsed = Date.now() - startedAt;
        const remaining = Math.max(0, Math.ceil((durationMs - elapsed) / 1000));

        if (!logged) {
          logged = true;
          console.log("[fake-progress]", {
            durationMs,
            typeofDuration: typeof durationMs,
            startedAt,
            elapsed,
            remaining,
          });
        }

        setElapsedSec(remaining);


        const t = Math.min(1, elapsed / D);

        const eased = 1 - Math.pow(1 - t, 3);
        const nextProgress = Math.min(C, Math.round(eased * C));
        setProgress((p) => (p >= C ? p : Math.max(p, nextProgress)));

        let idx = 0;
        for (let i = 0; i < FAKE_STEPS.length; i++) {
          if (nextProgress >= FAKE_STEPS[i].pct) idx = i;
        }
        setStepIndex(idx);
        setLoadingLabel(FAKE_STEPS[idx].label);
      }, 120);
    };



    const stopFakeProgress = () => {
      if (timer) clearInterval(timer);
      timer = null;
    };

    if (!pid) {
      setHomeRows([]);
      setHeroPick(null);
      setLoading(false);
      setProgress(0);
      return () => { alive = false; };
    }

    setLoading(true);
    startFakeProgress15s(12000, 95);

    fetchHomeRecoRows(pid)
      .then((data) => {
        if (!alive) return;

        stopFakeProgress();
        setProgress(100);

        // set rows
        const rows = Array.isArray(data) ? data : (data?.rows || []);
        const arr = Array.isArray(rows) ? rows : [];
        setHomeRows(arr);

        // keep your hero-pick logic as-is...
        const priority = [
          "for_you",
          "personal_movies",
          "personal_tv",
          "similar",
          "because_watched",
          "because_my_list",
          "genre",
          "trending",
          "new_week",
        ];

        const hasTrailer = (it) =>
          typeof it?.trailer_clip_url === "string" && it.trailer_clip_url.trim().length > 0;
        const hasBg = (it) => !!(it?.landscape_image || it?.landscape_url);

        const candidates = [];
        for (const t of priority) {
          const r = arr.find((x) => x?.row_type === t);
          if (r?.items?.length) candidates.push(...r.items);
        }
        if (candidates.length === 0) {
          for (const r of arr) if (r?.items?.length) candidates.push(...r.items);
        }

        let pick = candidates.find((it) => hasTrailer(it) && hasBg(it)) || null;
        pick = pick || candidates.find((it) => hasTrailer(it)) || null;
        pick = pick || candidates[0] || null;

        setHeroPick(pick);

        // small delay makes 100% feel “real”
        setTimeout(() => {
          if (!alive) return;
          setLoading(false);
        }, 250);
      })
      .catch(() => {
        if (!alive) return;
        stopFakeProgress();
        setProgress(0);
        setElapsedSec(0);
        setHomeRows([]);
        setLoading(false);
      });

    return () => {
      alive = false;
      stopFakeProgress();
    };
  }, [profileId]);


  // --- Dedup global: un titre apparait une seule fois sur TOUTE la page ---
  const dedupedRows = useMemo(() => {
    const used = new Set();

    const out = [];
    for (const row of homeRows || []) {
      const items = Array.isArray(row?.items) ? row.items : [];
      const filtered = [];

      for (const it of items) {
        const id = it?.id;
        if (id == null) continue;
        const n = Number(id);
        if (used.has(n)) continue;
        used.add(n);
        filtered.push(it);
        if (filtered.length >= ROW_SIZE) break;
      }

      if (filtered.length > 0) {
        out.push({
          ...row,
          items: filtered,
        });
      }
    }

    return out;
  }, [homeRows]);

  if (loading) {
    return (
      <div className="loading-container">
        <div className="loading-card">
          <div className="loading-head">
            <div className="loading-spinner" />
          </div>

          <p className="loading-text">{loadingLabel}</p>
          <p className="loading-subtext">Preparing your home feed…</p>

          <div className="progress-wrap">
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${progress}%` }} />
            </div>

            <div className="progress-meta">
              <span>{progress}%</span>
              <span>{elapsedSec}s</span>
            </div>
          </div>

          <div className="loading-steps">
            {FAKE_STEPS.map((s, i) => (
              <div
                key={s.label}
                className={
                  "loading-step " +
                  (i === stepIndex ? "active" : i < stepIndex ? "done" : "")
                }
              >
                <span className="loading-step-dot" />
                <span>{s.label}</span>
              </div>
            ))}
          </div>

        </div>
        <img src="/logo/taurus_logo_full.png" style={{ height: 32, marginRight: 12 }} alt="Taurus Logo" />
      </div>

    );
  }



  return (
    <div className="homepage">
      <Navbar />
      <Hero hero={heroPick} />

      {dedupedRows.map((row, idx) => (
        <Row
          key={`${row.row_type || "row"}-${idx}`}
          title={row.title || "Recommended"}
          movies={row.items || []}
        />
      ))}

      <footer className="footer">
        <p>© 2026 Taurus. All rights reserved.</p>

        <button className="footer-link" type="button" onClick={openMsg}>
          DMCA Notices
        </button>
      </footer>

      {msgOpen && (
        <div className="modal-backdrop" onClick={closeMsg} role="presentation">
          <div
            className="modal-card"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label="Messages"
          >
            <button className="modal-close" type="button" onClick={closeMsg} aria-label="Close">
              ×
            </button>

            <h3 className="modal-title">DMCA Notice</h3>
            <p className="modal-text">
              In accordance with the Digital Millennium Copyright Act of 1998 (the text of which may be found on the U.S. Copyright Office website at http://lcweb.loc.gov/copyright/), Taurus will respond expeditiously to claims of copyright infringement that are reported to Taurus’s designated copyright agent identified below. Please also note that under Section 512(f) any person who knowingly materially misrepresents that material or activity is infringing may be subject to liability. Taurus reserves the right at its sole and entire discretion, to remove content and terminate the accounts of Taurus users who infringe, or appear to infringe, the intellectual property or other rights of third parties.

              If you believe that your copywriten work has been copied in a way that constitutes copyright infringement, please provide Taurus’s copyright agent the following information:

              A physical or electronic signature of a person authorized to act on behalf of the owner of an exclusive right that is allegedly infringed.
              Identification of the copyright work claimed to have been infringed, or, if multiple copyrighted works at a single online site are covered by a single notification, a representative list of such works at the Website.
              Identification of the material that is claimed to be infringing or to be the subject of infringing activity and that is to be removed or access to which is to be disabled, and information reasonably sufficient to permit Taurus to locate the material.
              Information reasonably sufficient to permit Taurus to contact the complaining party, including a name, address, telephone number and, if available, an email address at which the complaining party may be contacted.
              A statement that the complaining party has a good-faith belief that use of the material in the manner complained of is not authorized by the copyright owner, its agent or the law.
              A statement that the information in the notification is accurate and, under penalty of perjury, that the complaining party is authorized to act on behalf of the owner of an exclusive right that is allegedly infringed.
              All claims of copyright infringement on or regarding this Website should be delivered to Taurus’s designated copyright agent at the following address:

              Copyright Contact Information:
              Please contact us at taurusadmin@proton.me

              We apologize for any kind of misuse of our service and promise to do our best to find and terminate abusive files.
            </p>
          </div>
        </div>
      )}

    </div>
  );
};

export default HomePage;

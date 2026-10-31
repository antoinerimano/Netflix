// src/pages/HomePage.jsx
import React, { useEffect, useMemo, useState } from "react";
import Navbar from "../components/Navbar";
import Hero, { heroArtwork } from "../components/Hero";
import { Skeleton } from "../design";
import "./HomePage.css";
import Row from "../components/Row";
import Footer from "../components/Footer";
import { fetchHomeRecoRows } from "../api/recoApi";

const ROW_SIZE = 18;

const HomePage = () => {
  const [loading, setLoading] = useState(true);
  const [heroPick, setHeroPick] = useState(null);

  // rows backend
  const [homeRows, setHomeRows] = useState([]); // [{row_type,title,items:[...]}, ...]
  const [profileId, setProfileId] = useState(() =>
    localStorage.getItem("activeProfileId")
  );

  useEffect(() => {
    const onChange = () =>
      setProfileId(localStorage.getItem("activeProfileId"));
    window.addEventListener("activeProfileChanged", onChange);
    return () => window.removeEventListener("activeProfileChanged", onChange);
  }, []);

  // --- Fetch backend reco rows ---
  useEffect(() => {
    let alive = true;
    const pid = localStorage.getItem("activeProfileId");

    if (!pid) {
      setHomeRows([]);
      setHeroPick(null);
      setLoading(false);
      return () => {
        alive = false;
      };
    }

    setLoading(true);

    fetchHomeRecoRows(pid)
      .then((data) => {
        if (!alive) return;

        const rows = Array.isArray(data) ? data : data?.rows || [];
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
          typeof it?.trailer_clip_url === "string" &&
          it.trailer_clip_url.trim().length > 0;
        // a wide artwork, else at least a poster: a banner without any image was all black
        const hasBg = (it) => !!(it?.landscape_image || it?.landscape_url);
        const hasArt = (it) => !!heroArtwork(it);

        const candidates = [];
        for (const t of priority) {
          const r = arr.find((x) => x?.row_type === t);
          if (r?.items?.length) candidates.push(...r.items);
        }
        if (candidates.length === 0) {
          for (const r of arr) if (r?.items?.length) candidates.push(...r.items);
        }

        let pick = candidates.find((it) => hasTrailer(it) && hasBg(it)) || null;
        pick = pick || candidates.find((it) => hasBg(it)) || null;
        pick = pick || candidates.find((it) => hasArt(it)) || null;

        setHeroPick(pick);

        // small delay makes UI feel nicer
        setTimeout(() => {
          if (!alive) return;
          setLoading(false);
        }, 150);
      })
      .catch(() => {
        if (!alive) return;
        setHomeRows([]);
        setLoading(false);
      });

    return () => {
      alive = false;
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
    // the page's shape while it loads (banner + rows), not a spinner on an empty screen
    return (
      <div className="homepage">
        <Navbar />
        <div className="home-skeleton" aria-busy="true" aria-label="Loading">
          <div className="home-skeleton__hero">
            <Skeleton variant="text" width="9rem" />
            <Skeleton width="min(28rem, 70%)" height="3.5rem" />
            <Skeleton variant="text" width="min(34rem, 80%)" />
            <Skeleton variant="text" width="min(26rem, 60%)" />
            <div className="home-skeleton__buttons">
              <Skeleton width="8rem" height="3.25rem" />
              <Skeleton width="10rem" height="3.25rem" />
            </div>
          </div>
          {[0, 1].map((r) => (
            <div key={r} className="home-skeleton__row">
              <Skeleton variant="text" width="12rem" height="1.4rem" />
              <div className="home-skeleton__cards">
                {[0, 1, 2, 3, 4, 5].map((c) => (
                  <Skeleton key={c} className="home-skeleton__card" />
                ))}
              </div>
            </div>
          ))}
        </div>
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

      <Footer />
    </div>
  );
};

export default HomePage;

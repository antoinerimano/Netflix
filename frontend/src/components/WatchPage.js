import React, { useEffect, useMemo, useState, useRef, useCallback } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import "./WatchPage.css";

import { fetchTitleById, fetchMovieById, fetchEpisodesBySeasonNumber } from "../api/titlesApi";

function storageKey(profileId, titleId) {
  return `watchprefs_${profileId || "anon"}_${titleId}`;
}

function normalizeUrl(u) {
  const s = String(u || "").trim();
  if (!s) return "";
  if (!/^https?:\/\//i.test(s) && /^[\w-]+\.[\w.-]+/i.test(s)) return `https://${s}`;
  return s;
}

function isDirectVideo(url) {
  return /\.(m3u8|mp4)(\?|#|$)/i.test(url || "");
}

// --- NEW: read season/episode from query ---
function readPositiveInt(search, key, fallback) {
  const v = new URLSearchParams(search).get(key);
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}

// --- Existing (movies / fallback) ---
function getProvidersFromTitle(t) {
  const links = [
    { key: "video_url", label: "Vidking", url: t?.video_url },
    { key: "movie_link2", label: "Videasy", url: t?.movie_link2 },
    { key: "movie_link3", label: "Vidsrc", url: t?.movie_link3 },
    { key: "movie_link4", label: "VidFast", url: t?.movie_link4 },
    { key: "movie_link5", label: "VidPlus", url: t?.movie_link5 },
    { key: "movie_link6", label: "111movies", url: t?.movie_link6 },
  ];
  return links.filter((p) => typeof p.url === "string" && p.url.trim().length > 5);
}

// --- NEW: providers from an EPISODE (TV) ---
function getProvidersFromEpisode(ep) {
  if (!ep) return [];

  const links = [
    { key: "video_url", label: "Vidking", url: ep.video_url },
    { key: "episode_link2", label: "Videasy", url: ep.episode_link2 },
    { key: "episode_link3", label: "Vidsrc", url: ep.episode_link3 },
    { key: "episode_link4", label: "VidFast", url: ep.episode_link4 },
    { key: "episode_link5", label: "VidPlus", url: ep.episode_link5 },
    { key: "episode_link6", label: "111movies", url: ep.episode_link6 },
  ];

  // Filtre pour n'afficher que les liens qui ne sont pas vides
  return links.filter((p) => typeof p.url === "string" && p.url.trim().length > 5);
}

function clampText(s, max = 180) {
  const str = String(s || "").trim();
  if (!str) return "";
  if (str.length <= max) return str;
  return str.slice(0, max - 1).trimEnd() + "…";
}

export default function WatchPage() {
  const { id } = useParams();
  const titleId = Number(id);
  const navigate = useNavigate();
  const location = useLocation();

  const activeProfileId = localStorage.getItem("activeProfileId") || "anon";

  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState(null);
  const [err, setErr] = useState("");

  // --- NEW: keep season/episode in state (from URL) ---
  const seasonFromUrl = useMemo(() => readPositiveInt(location.search, "season", 1), [location.search]);
  const episodeFromUrl = useMemo(() => readPositiveInt(location.search, "episode", 1), [location.search]);
  const [seasonNumber, setSeasonNumber] = useState(seasonFromUrl);
  const [episodeNumber, setEpisodeNumber] = useState(episodeFromUrl);

  useEffect(() => {
    setSeasonNumber(seasonFromUrl);
    setEpisodeNumber(episodeFromUrl);
  }, [seasonFromUrl, episodeFromUrl]);

  // --- NEW: the episode we want to play (TV only) ---
  const [activeEpisode, setActiveEpisode] = useState(null);
  const [episodeLoadError, setEpisodeLoadError] = useState("");

  const userPickedRef = useRef(false);
  const hasPrefsRef = useRef(false);
  const [prefsLoaded, setPrefsLoaded] = useState(false);

  // ✅ Default selection is NOT custom anymore (we auto-pick first provider)
  const [selectedKey, setSelectedKey] = useState("");
  const [customUrl, setCustomUrl] = useState("");
  const [resolvedUrl, setResolvedUrl] = useState("");

  const [panelOpen, setPanelOpen] = useState(true);
  const [theme, setTheme] = useState("dark");
  const [hint, setHint] = useState("");

  const [isPulsing, setIsPulsing] = useState(false);
  const [sourceLoading, setSourceLoading] = useState(false);

  // ✅ Hide hint while user is interacting with the player (hover)
  const [hoverPlayer, setHoverPlayer] = useState(false);

  const iframeRef = useRef(null);

  const showHint = useCallback((msg) => setHint(msg), []);


  // Load title
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        setLoading(true);
        setErr("");
        let data = null;
        try {
          data = await fetchTitleById(titleId);
        } catch {
          data = await fetchMovieById(titleId);
        }
        if (!alive) return;
        setTitle(data || null);
      } catch (e) {
        if (!alive) return;
        setErr(e?.message || "Failed to load title");
      } finally {
        alive && setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [titleId]);

  // --- NEW: detect TV show ---
  const isTV = useMemo(() => {
    const t = String(title?.type || title?.kind || "").toLowerCase();
    // common patterns: "tv", "tvshow", "show"
    return t === "tv" || t === "tvshow" || t === "show";
  }, [title]);

  // --- NEW: load the exact episode when TV + season/episode present ---
  useEffect(() => {
    let alive = true;

    (async () => {
      setEpisodeLoadError("");
      setActiveEpisode(null);

      if (!title || !isTV) return;

      try {
        const eps = await fetchEpisodesBySeasonNumber(titleId, seasonNumber);
        if (!alive) return;

        const list = Array.isArray(eps) ? eps : [];
        const found =
          list.find((e) => Number(e?.episode_number) === Number(episodeNumber)) ||
          null;

        setActiveEpisode(found);

        if (!found) {
          setEpisodeLoadError(`Episode not found (S${seasonNumber}E${episodeNumber}).`);
        }
      } catch (e) {
        if (!alive) return;
        setEpisodeLoadError("Failed to load episode links.");
        setActiveEpisode(null);
      }
    })();

    return () => {
      alive = false;
    };
  }, [title, isTV, titleId, seasonNumber, episodeNumber]);


      // ✅ Back always returns to the details page for this title
  const goBack = useCallback(() => {
    // if your details pages are separated by type
    if (isTV) {
      navigate(`/tv/${titleId}`, { replace: true });
    } else {
      navigate(`/movies/${titleId}`, { replace: true });
    }
  }, [navigate, isTV, titleId]);

  // --- CHANGED: providers come from episode (TV) or from title (movie) ---
  const providers = useMemo(() => {
    if (isTV) return getProvidersFromEpisode(activeEpisode);
    return getProvidersFromTitle(title);
  }, [title, isTV, activeEpisode]);

  // Load prefs
  useEffect(() => {
    const key = storageKey(activeProfileId, titleId);
    const raw = localStorage.getItem(key);

    if (!raw) {
      hasPrefsRef.current = false;
      setPrefsLoaded(true);
      return;
    }

    try {
      const prefs = JSON.parse(raw);

      hasPrefsRef.current = !!prefs?.selectedKey;

      if (prefs?.selectedKey) setSelectedKey(prefs.selectedKey);
      if (typeof prefs?.customUrl === "string") setCustomUrl(prefs.customUrl);
      if (typeof prefs?.panelOpen === "boolean") setPanelOpen(prefs.panelOpen);
      if (prefs?.theme === "dark" || prefs?.theme === "light") setTheme(prefs.theme);
    } catch {
      hasPrefsRef.current = false;
    } finally {
      setPrefsLoaded(true);
    }
  }, [activeProfileId, titleId]);

  useEffect(() => {
    // wait until we know if prefs exist
    if (!prefsLoaded) return;

    // if user already picked something manually, never override
    if (userPickedRef.current) return;

    // if prefs exist, never override
    if (hasPrefsRef.current) return;

    // if providers exist, ALWAYS start on first provider (even if we temporarily fell back to custom)
    if (providers.length > 0) {
      if (selectedKey !== providers[0].key) setSelectedKey(providers[0].key);
      return;
    }

    // no providers -> fallback to custom
    if (!selectedKey) setSelectedKey("custom");
  }, [prefsLoaded, providers, selectedKey]);

  // Save prefs
  useEffect(() => {
    // avoid saving an empty selectedKey
    if (!selectedKey) return;

    const key = storageKey(activeProfileId, titleId);
    localStorage.setItem(
      key,
      JSON.stringify({
        selectedKey,
        customUrl,
        panelOpen,
        theme,
        updatedAt: Date.now(),
      })
    );
  }, [activeProfileId, titleId, selectedKey, customUrl, panelOpen, theme]);

  // Resolve URL
  useEffect(() => {
    setHint("");

    if (!selectedKey) {
      setResolvedUrl("");
      return;
    }

    if (selectedKey === "custom") {
      setResolvedUrl(normalizeUrl(customUrl));
      return;
    }

    const p = providers.find((x) => x.key === selectedKey);
    setResolvedUrl(normalizeUrl(p?.url || ""));
  }, [selectedKey, customUrl, providers]);

  // Hint UX if embed seems blocked
  useEffect(() => {
    if (!resolvedUrl) return;
    if (selectedKey === "custom") return;

    showHint("Loading source…");

  }, [resolvedUrl, selectedKey, showHint]);

  useEffect(() => {
    if (!resolvedUrl) {
      setSourceLoading(false);
      return;
    }

    // Start loading + pulse whenever the source changes
    setSourceLoading(true);
    setIsPulsing(true);

    const t = setTimeout(() => setIsPulsing(false), 650); // matches wpPulse duration
    return () => clearTimeout(t);
  }, [resolvedUrl]);

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e) => {
      const k = (e.key || "").toLowerCase();

      if ((e.ctrlKey || e.metaKey) && k === "k") {
        e.preventDefault();
        setSelectedKey("custom");
        userPickedRef.current = true;

        setPanelOpen(true);
        setTimeout(() => document.querySelector(".watchpage__input")?.focus(), 0);
        return;
      }

      if (k === "p") {
        setPanelOpen((v) => !v);
        return;
      }

      if (k === "d") {
        setTheme((t) => (t === "dark" ? "light" : "dark"));
        return;
      }

      // optional: Back shortcut
      if (k === "backspace" && !e.target?.matches?.("input, textarea")) {
        e.preventDefault();
        goBack();
        return;
      }
    };

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goBack]);

  const backdrop = title?.landscape_image || title?.landscape_url || "";
  const poster = title?.poster || "";
  const metaLine = useMemo(() => {
    const year = title?.release_year || (title?.release_date ? String(title.release_date).slice(0, 4) : "");
    const vote = typeof title?.vote_average === "number" ? title.vote_average.toFixed(1) : title?.rating;
    const genre = title?.genre || "";
    return [year, vote ? `★ ${vote}` : "", genre].filter(Boolean).join(" · ");
  }, [title]);

  const sourceType = useMemo(() => {
    if (!resolvedUrl) return "none";
    return isDirectVideo(resolvedUrl) ? "direct" : "iframe";
  }, [resolvedUrl]);

  const PlayerNode = useMemo(() => {
    if (!resolvedUrl) {
      return (
        <div className="watchpage__empty">
          <div className="watchpage__emptyCard">
            <div className="watchpage__emptyTitle">Choose a source</div>
            <div className="watchpage__emptyDesc">
              Select a provider on the right, or paste your own link.
              <div className="watchpage__shortcutLine">
                Shortcuts: <span className="watchpage__kbd">Ctrl/⌘</span>+<span className="watchpage__kbd">K</span>{" "}
                Custom · <span className="watchpage__kbd">P</span> Panel · <span className="watchpage__kbd">D</span> Theme
              </div>
            </div>
            {/* NEW: small debug hint for TV */}
            {isTV && episodeLoadError ? (
              <div style={{ marginTop: 10, opacity: 0.8, fontSize: 13 }}>
                {episodeLoadError}
              </div>
            ) : null}
          </div>
        </div>
      );
    }

    if (sourceType === "direct") {
      return (
        <video
          className="watchpage__video"
          controls
          playsInline
          src={resolvedUrl}
          onCanPlay={() => setSourceLoading(false)}
          onError={() => {
            setSourceLoading(false);
            setHint("This link doesn’t seem playable. Try another source.");
          }}
        />
      );
    }

    return (
      <iframe
        ref={iframeRef}
        className="watchpage__iframe"
        src={resolvedUrl}
        title="Player"
        allow="autoplay; fullscreen; picture-in-picture"
        allowFullScreen
        loading="lazy"
        onLoad={() => {
          setSourceLoading(false);
          setHint("");
        }}
      />
    );
  }, [resolvedUrl, sourceType, isTV, episodeLoadError]);

  if (loading) {
    return (
      <div className={`watchpage ${theme === "light" ? "theme-light" : "theme-dark"}`}>
        <div className="watchpage__center">
          <div className="watchpage__skeleton">
            <div className="sk sk-top" />
            <div className="sk sk-main" />
            <div className="sk sk-side" />
          </div>
        </div>
      </div>
    );
  }

  if (err || !title) {
    return (
      <div className={`watchpage ${theme === "light" ? "theme-light" : "theme-dark"}`}>
        <div className="watchpage__center">
          <div className="watchpage__errorCard">
            <div className="watchpage__errorTitle">Unable to load</div>
            <div className="watchpage__errorText">{err || "Not found"}</div>
            <button className="watchpage__btn" onClick={goBack}>
              ← Back
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`watchpage ${theme === "light" ? "theme-light" : "theme-dark"} ${panelOpen ? "" : "panel-closed"}`}>
      <div className="watchpage__bg" style={{ backgroundImage: backdrop ? `url(${backdrop})` : undefined }} />
      <div className="watchpage__overlay" />
      <div className="watchpage__noise" />

      <div className="watchpage__shell">
        <div className="watchpage__topbar">
          <button className="watchpage__iconBtn" onClick={goBack} title="Back">
            ←
          </button>

          <div className="watchpage__topmeta">
            <div className="watchpage__topTitle">
              {title.title}
              {/* NEW: show S/E when TV and params exist */}
              {isTV ? ` · S${seasonNumber}E${episodeNumber}` : ""}
            </div>
            <div className="watchpage__topSub">{metaLine || clampText(title.tagline || title.description, 92)}</div>
          </div>

          <div className="watchpage__topActions">
            <button
              className="watchpage__pillBtn"
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
              title="Toggle theme (D)"
            >
              {theme === "dark" ? "Bright mode" : "Dark mode"}
            </button>

            <button className="watchpage__pillBtn" onClick={() => setPanelOpen((v) => !v)} title="Toggle panel (P)">
              {panelOpen ? "Hide panel" : "Show panel"}
            </button>
          </div>
        </div>

        <div className={`watchpage__layout ${panelOpen ? "" : "panel-closed"}`}>
          <div className={`watchpage__stage ${isPulsing ? "is-pulsing" : ""}`}>
            <div className="watchpage__stageHeader">
              <div className="watchpage__stageLeft">
                {poster ? <img className="watchpage__posterMini" src={poster} alt={title.title} /> : null}
                <div className="watchpage__stageText">
                  <div className="watchpage__stageTitle">{title.title}</div>
                  <div className="watchpage__stageDesc">{clampText(title.tagline || title.description, 160)}</div>
                </div>
              </div>
            </div>

            <div
              className="watchpage__playerWrap"
              onMouseEnter={() => setHoverPlayer(true)}
              onMouseLeave={() => setHoverPlayer(false)}
            >
              {PlayerNode}

              {hint && !hoverPlayer ? (
                <div className="watchpage__softHint">
                  <div className="watchpage__softHintDot" />
                  <div className="watchpage__softHintText">{hint}</div>
                  <button className="watchpage__softHintBtn" onClick={() => setPanelOpen(true)}>
                    Sources
                  </button>
                </div>
              ) : null}
            </div>

            <div className="watchpage__shortcuts">
              <strong>Navigation : </strong>
              <span className="watchpage__kbd">←</span> Back

              <strong>Sources : </strong>
              <span className="watchpage__kbd">Ctrl/⌘</span>+<span className="watchpage__kbd">K</span> Custom link,
              <span className="watchpage__kbd">P</span> Toggle panel

              <strong>Display : </strong>
              <span className="watchpage__kbd">D</span> Toggle theme
            </div>
          </div>

          <aside className="watchpage__panel" aria-label="Sources panel">
            <div className="watchpage__controls">
              <div className="watchpage__providerRow">
                {/* ✅ Providers first */}
                {providers.map((p) => (
                  <button
                    key={p.key}
                    className={`watchpage__chip ${selectedKey === p.key ? "is-active" : ""}`}

                    onClick={() => {
                      userPickedRef.current = true;   // ✅ prevent auto-reset to first provider
                      setSelectedKey(p.key);
                    }}
                  >
                    {p.label}
                    <span className="watchpage__chipBadge">HD</span>
                  </button>
                ))}

                {/* ✅ Custom ALWAYS last */}
                <button
                  className={`watchpage__chip ${selectedKey === "custom" ? "is-active" : ""}`}
                  onClick={() => {
                    userPickedRef.current = true;   // ✅ prevent auto-reset
                    setSelectedKey("custom");
                  }}
                >
                  Custom link
                </button>
              </div>

              {selectedKey === "custom" ? (
                <div className="watchpage__customBox">
                  <input
                    className="watchpage__input"
                    value={customUrl}
                    onChange={(e) => setCustomUrl(e.target.value)}
                    placeholder="Paste YOUR link (https://...)"
                    spellCheck={false}
                  />
                  <button className="watchpage__btn" onClick={() => setCustomUrl("")}>
                    Clear
                  </button>
                </div>
              ) : (
                <div className="watchpage__sourceInfo">
                  <div className="watchpage__sourceTop">
                    <div className="watchpage__sourceLabel">Selected</div>
                    <div className={`watchpage__sourcePill ${sourceType === "direct" ? "is-direct" : "is-embed"}`}>
                      {sourceType === "direct" ? "Direct video" : "Embedded"}
                    </div>
                  </div>

                  {/* ✅ force a clean vertical stack (value + loading) */}
                  <div className="watchpage__sourceBody">
                    <div className="watchpage__sourceValue">
                      {providers.find((x) => x.key === selectedKey)?.label || "—"}
                    </div>

                    {sourceLoading ? (
                      <div className="watchpage__sourceLoading">
                        <span className="watchpage__spinner" aria-hidden="true" />
                        Loading…
                      </div>
                    ) : null}
                  </div>
                </div>
              )}

              <div className="watchpage__divider" />

              <div className="watchpage__tipCard">
                <div className="watchpage__tipTitle">Tip</div>
                <div className="watchpage__tipText">If a source is blank, switch provider. Some sites block embedding.</div>
              </div>
            </div>

            <div className="watchpage__panelFoot">
              <div className="watchpage__panelFootTitle">Saved per profile</div>
              <div className="watchpage__panelFootText">Last source + custom link + theme are remembered.</div>
            </div>
          </aside>
        </div>
      </div>
    </div>
  );
}
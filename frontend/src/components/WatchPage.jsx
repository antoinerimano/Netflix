import React, { useEffect, useMemo, useState, useRef, useCallback } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import { formatNumber } from "../i18n/format";
import { genreName, splitGenres } from "./detail/DetailHero";
import "./WatchPage.css";

import { fetchTitleById, fetchMovieById, fetchProviders, buildProviderLinks } from "../api/titlesApi";
import { saveWatchProgress, reportPlayback, fetchPreferredSource, fetchCollection } from "../api/recoApi";
import { patchProfile } from "../api/userApi";
import { enterPlayer, setBackHandler } from "../tv/spatialNavigation";
import { tmdbBackground, IMG } from "../utils/tmdbImage";
import { Button, Chip, EmptyState, Skeleton, Spinner, Switch } from "../design";
import { ArrowLeftIcon, ChevronRightIcon, MaximizeIcon, LinkIcon } from "../design/icons";
import WatchInfo from "./watch/WatchInfo";
import { usePlayerRemote } from "./watch/playerRemote";

import {
  LEGACY_SOURCE_KEYS,
  SOURCE_LOAD_TIMEOUT_MS,
  SOURCE_QUICK_LEAVE_MS,
  SOURCE_SILENT_TIMEOUT_MS,
  SOURCE_STAYED_MS,
  isDirectVideo,
  normalizeUrl,
  readPlayerEvent,
  readPositiveInt,
  storageKey,
} from "./watch/playerEvents";
import {
  orderSources,
  readBlockPopups,
  readSandboxFailures,
  rememberSandboxFailure,
  sandboxFor,
  shouldOfferAllow,
  storeBlockPopups,
} from "./watch/popups";

export default function WatchPage() {
  const { t, i18n } = useTranslation("watch");
  const lng = i18n.resolvedLanguage;
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
  // resume point in seconds (?t=), from "Continue watching"
  const startFromUrl = useMemo(() => readPositiveInt(location.search, "t", 0), [location.search]);
  const [seasonNumber, setSeasonNumber] = useState(seasonFromUrl);
  const [episodeNumber, setEpisodeNumber] = useState(episodeFromUrl);

  useEffect(() => {
    setSeasonNumber(seasonFromUrl);
    setEpisodeNumber(episodeFromUrl);
  }, [seasonFromUrl, episodeFromUrl]);

  // stream providers (domain + path templates), shared by every title
  const [providerDefs, setProviderDefs] = useState([]);
  const [providersError, setProvidersError] = useState("");

  const userPickedRef = useRef(false);
  const hasPrefsRef = useRef(false);
  const savedKeyRef = useRef(null); // source saved in this browser for this title
  // smart playback
  const attemptRef = useRef(null); // current source: { key, startedAt, playing, reported, report(worked) }
  const iframeLoadedRef = useRef(false);
  const autoFailedRef = useRef(new Set()); // sources that failed by themselves on this page
  const [banner, setBanner] = useState(null); // { text, nextKey?, nextLabel? }
  const [serverPref, setServerPref] = useState(undefined); // undefined = loading, null = unavailable
  const [, setFailedTick] = useState(0); // autoFailedRef changed (the "allow pop-ups" offer reads it)

  // Block pop-ups (ROADMAP 9.1): the profile's setting, sources that failed sandboxed for this
  // profile (learned), and the ones the viewer let open pop-ups on this page ("Allow pop-ups for
  // this source": the setting doesn't change)
  const [blockPopups, setBlockPopups] = useState(readBlockPopups);
  const [learnedNoSandbox, setLearnedNoSandbox] = useState(() => readSandboxFailures(activeProfileId));
  const [allowedOnce, setAllowedOnce] = useState(() => new Set());
  const [prefsLoaded, setPrefsLoaded] = useState(false);

  // ✅ Default selection is NOT custom anymore (we auto-pick first provider)
  const [selectedKey, setSelectedKey] = useState("");
  const [customUrl, setCustomUrl] = useState("");
  const [resolvedUrl, setResolvedUrl] = useState("");

  const [panelOpen, setPanelOpen] = useState(true);
  const [theme, setTheme] = useState("dark");
  const [hint, setHint] = useState("");

  const [isPulsing, setIsPulsing] = useState(false);
  // full screen with the remote handed to the player: show its keys for a few seconds
  const [playerKeysHint, setPlayerKeysHint] = useState(false);
  const [sourceLoading, setSourceLoading] = useState(false);

  // ✅ Hide hint while user is interacting with the player (hover)
  const [hoverPlayer, setHoverPlayer] = useState(false);

  const iframeRef = useRef(null);
  const videoRef = useRef(null);
  const playerWrapRef = useRef(null);

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
        setErr(t("loadFailed"));
      } finally {
        alive && setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [titleId, lng]); // eslint-disable-line react-hooks/exhaustive-deps -- lng: title + synopses in the app's language

  // --- NEW: detect TV show ---
  const isTV = useMemo(() => {
    const kind = String(title?.type || title?.kind || "").toLowerCase();
    // common patterns: "tv", "tvshow", "show"
    return kind === "tv" || kind === "tvshow" || kind === "show";
  }, [title]);

  // Load stream providers
  useEffect(() => {
    let alive = true;
    fetchProviders()
      .then((list) => alive && setProviderDefs(list))
      .catch(() => alive && setProvidersError(t("sources.loadFailed")));
    return () => {
      alive = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps


  // Continue watching: remember what this profile opened (movie, or season/episode)
  useEffect(() => {
    if (!title?.id) return;
    const pid = localStorage.getItem("activeProfileId");
    if (!pid) return;
    saveWatchProgress({
      profileId: pid,
      titleId: title.id,
      season: isTV ? seasonNumber : null,
      episode: isTV ? episodeNumber : null,
    }).catch(() => {});
  }, [title?.id, isTV, seasonNumber, episodeNumber]);

  // Next aired episode: rest of this season, then the first episode of the next season
  const nextEpisode = useMemo(() => {
    if (!isTV || !Array.isArray(title?.seasons)) return null;
    const today = new Date().toISOString().slice(0, 10);
    const airedNumbers = (season) =>
      (season?.episodes || [])
        .filter((ep) => !ep.air_date || ep.air_date <= today)
        .map((ep) => Number(ep.episode_number))
        .sort((a, b) => a - b);

    const seasons = [...title.seasons].sort((a, b) => a.season_number - b.season_number);
    const current = seasons.find((s) => Number(s.season_number) === Number(seasonNumber));
    const laterInSeason = airedNumbers(current).find((n) => n > episodeNumber);
    if (laterInSeason) return { season: seasonNumber, episode: laterInSeason };

    for (const s of seasons) {
      if (s.season_number > seasonNumber) {
        const first = airedNumbers(s)[0];
        if (first) return { season: s.season_number, episode: first };
      }
    }
    return null;
  }, [isTV, title, seasonNumber, episodeNumber]);

  // a movie of a franchise: the next part in watch order (released), for the "Next movie" button
  const [nextPart, setNextPart] = useState(null);
  useEffect(() => {
    setNextPart(null);
    const collectionId = !isTV ? title?.collection_id : null;
    const profileId = localStorage.getItem("activeProfileId");
    if (!collectionId || !profileId) return undefined;
    let alive = true;
    fetchCollection(profileId, collectionId)
      .then((c) => {
        if (!alive) return;
        const i = c.parts.findIndex((p) => p.title.id === title.id);
        const next = i >= 0 ? c.parts.slice(i + 1).find((p) => !p.upcoming) : null;
        setNextPart(next ? next.title : null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [isTV, title?.id, title?.collection_id]);

  const goToNextPart = useCallback(() => {
    if (nextPart) navigate(`/watch/${nextPart.id}`, { replace: true });
  }, [navigate, nextPart]);

  const goToNextEpisode = useCallback(() => {
    if (!nextEpisode) return;
    navigate(`/watch/${titleId}?season=${nextEpisode.season}&episode=${nextEpisode.episode}`, { replace: true });
  }, [navigate, titleId, nextEpisode]);

  // ✅ Back always returns to the details page for this title
  const goBack = useCallback(() => {
    // if your details pages are separated by type
    if (isTV) {
      navigate(`/tv/${titleId}`, { replace: true });
    } else {
      navigate(`/movies/${titleId}`, { replace: true });
    }
  }, [navigate, isTV, titleId]);

  // Players with a remote API (CineSrc): OK / arrows are sent to them, the remote stays here
  const { hasRemote } = usePlayerRemote({ url: resolvedUrl, iframeRef, wrapRef: playerWrapRef });

  // Full screen, then the TV remote / keyboard for the player (OK = play / pause there).
  // An embedded player (cross-origin iframe) gets the focus only once the browser is in full
  // screen: Back / Escape then leave full screen (the browser does it, even inside the player)
  // and the page takes the focus back. Without full screen nothing could bring the remote back
  // out of the player, so the remote stays on the page and the player keeps its own controls.
  const goFullscreen = useCallback(async () => {
    const wrap = playerWrapRef.current;
    if (!wrap) return;
    const isFullscreen = () => !!(document.fullscreenElement || document.webkitFullscreenElement);
    if (!isFullscreen()) {
      const request = wrap.requestFullscreen || wrap.webkitRequestFullscreen;
      try {
        await request?.call(wrap);
      } catch {
        /* refused: checked below */
      }
      // webkitRequestFullscreen returns nothing: give it a moment
      if (!isFullscreen()) await new Promise((r) => setTimeout(r, 400));
    }
    if (!isFullscreen()) {
      setBanner({ text: t("player.noFullscreen") });
      return;
    }
    if (hasRemote || !iframeRef.current) {
      // our own <video> or a player we drive: the remote stays on the page (the tile)
      if (videoRef.current) enterPlayer(videoRef.current);
      else wrap.focus({ preventScroll: true });
    } else {
      enterPlayer(iframeRef.current);
    }
    setPlayerKeysHint(true);
  }, [hasRemote, t]);

  useEffect(() => {
    if (!playerKeysHint) return;
    const timer = setTimeout(() => setPlayerKeysHint(false), 5000);
    const onChange = () => {
      if (!document.fullscreenElement && !document.webkitFullscreenElement) setPlayerKeysHint(false);
    };
    document.addEventListener("fullscreenchange", onChange);
    document.addEventListener("webkitfullscreenchange", onChange);
    return () => {
      clearTimeout(timer);
      document.removeEventListener("fullscreenchange", onChange);
      document.removeEventListener("webkitfullscreenchange", onChange);
    };
  }, [playerKeysHint]);

  // TV remote Back / Escape: back to this title's details page (leaves full screen first)
  useEffect(() => setBackHandler(goBack), [goBack]);

  // Links: provider domain + path template, filled with this movie / episode
  const linkedProviders = useMemo(() => {
    if (!title) return [];
    if (isTV) {
      return buildProviderLinks(
        providerDefs,
        { tmdb_id: title.tmdb_id, season: seasonNumber, episode: episodeNumber, start: startFromUrl },
        "episode"
      );
    }
    return buildProviderLinks(
      providerDefs,
      { tmdb_id: title.tmdb_id, imdb_id: title.imdb_code, start: startFromUrl },
      "movie"
    );
  }, [title, isTV, providerDefs, seasonNumber, episodeNumber, startFromUrl]);

  // Block pop-ups on: the sources that don't play sandboxed last ("may open pop-ups"), "No pop-ups"
  // on the ones the scout saw play sandboxed
  const providers = useMemo(
    () => orderSources(linkedProviders, { block: blockPopups, learned: learnedNoSandbox }),
    [linkedProviders, blockPopups, learnedNoSandbox]
  );

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
      savedKeyRef.current = prefs?.selectedKey ? LEGACY_SOURCE_KEYS[prefs.selectedKey] || prefs.selectedKey : null;
      if (typeof prefs?.customUrl === "string") setCustomUrl(prefs.customUrl);
      if (typeof prefs?.panelOpen === "boolean") setPanelOpen(prefs.panelOpen);
      if (prefs?.theme === "dark" || prefs?.theme === "light") setTheme(prefs.theme);
    } catch {
      hasPrefsRef.current = false;
    } finally {
      setPrefsLoaded(true);
    }
  }, [activeProfileId, titleId]);

  // Smart playback: which source worked last (this title on any device, else this profile)
  useEffect(() => {
    let alive = true;
    setServerPref(undefined);
    const pid = localStorage.getItem("activeProfileId");
    fetchPreferredSource({ profileId: pid, titleId })
      .then((pref) => alive && setServerPref(pref))
      .catch(() => alive && setServerPref(null));
    return () => {
      alive = false;
    };
  }, [titleId]);

  // Starting source. Until the viewer picks one: custom link they saved > source that worked for this
  // title > the one they used here last > source that worked for this profile > best ranked provider.
  useEffect(() => {
    if (!prefsLoaded || serverPref === undefined) return; // wait for local prefs + server memory

    const stillExists = selectedKey === "custom" || providers.some((p) => p.key === selectedKey);
    const waitingForProviders = !title || (providerDefs.length === 0 && !providersError);
    if (waitingForProviders) return;

    // the viewer (or an automatic fallback) already chose: keep it while it exists
    if (userPickedRef.current && stillExists) return;

    if (hasPrefsRef.current && savedKeyRef.current === "custom") {
      if (selectedKey !== "custom") setSelectedKey("custom");
      return;
    }

    // with pop-ups blocked, a source that plays sandboxed first (any source if none does)
    const available = new Set(providers.map((p) => p.key));
    const safe = new Set(providers.filter((p) => !p.popupRisk).map((p) => p.key));
    const candidates = [
      serverPref?.title,
      hasPrefsRef.current ? savedKeyRef.current : null,
      serverPref?.profile,
      providers[0]?.key,
    ];
    const pick = candidates.find((key) => key && safe.has(key)) || candidates.find((key) => key && available.has(key));

    if (pick) {
      if (selectedKey !== pick) setSelectedKey(pick);
    } else if (selectedKey !== "custom") {
      setSelectedKey("custom"); // no provider can play this title
    }
  }, [prefsLoaded, serverPref, title, providers, providerDefs, selectedKey, providersError]);

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

    showHint(t("player.loadingSource"));

  }, [resolvedUrl, selectedKey, showHint]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!resolvedUrl) {
      setSourceLoading(false);
      return;
    }

    // Start loading + pulse whenever the source changes
    setSourceLoading(true);
    setIsPulsing(true);

    const timer = setTimeout(() => setIsPulsing(false), 650); // matches wpPulse duration
    return () => clearTimeout(timer);
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

      // single-letter shortcuts, not while typing (a "p" in the custom link hid the panel)
      if (e.target?.matches?.("input, textarea")) return;

      if (k === "f") {
        goFullscreen();
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
  }, [goBack, goFullscreen]);

  const backdrop = title?.landscape_image || title?.landscape_url || "";
  const metaLine = useMemo(() => {
    const year = title?.release_year || (title?.release_date ? String(title.release_date).slice(0, 4) : "");
    const voteNumber = typeof title?.vote_average === "number" ? title.vote_average : parseFloat(title?.rating);
    const vote = Number.isFinite(voteNumber) && voteNumber > 0 ? formatNumber(voteNumber, { minimumFractionDigits: 1, maximumFractionDigits: 1 }, lng) : "";
    const genre = splitGenres(title?.genre).map((g) => genreName(g)).join(", ");
    return [year, vote ? `★ ${vote}` : "", genre].filter(Boolean).join(" · ");
  }, [title, lng]);

  const sourceType = useMemo(() => {
    if (!resolvedUrl) return "none";
    return isDirectVideo(resolvedUrl) ? "direct" : "iframe";
  }, [resolvedUrl]);

  // the player's sandbox: no pop-ups, no redirect of this page (undefined = none). A change
  // remounts the iframe (its key): a sandbox only applies when the frame loads.
  const sandboxAttr = sourceType === "iframe" ? sandboxFor(resolvedUrl, blockPopups && !allowedOnce.has(selectedKey)) : undefined;

  const learnSandboxFailure = useCallback(
    (key) => {
      rememberSandboxFailure(activeProfileId, key);
      setLearnedNoSandbox(readSandboxFailures(activeProfileId));
    },
    [activeProfileId]
  );

  // The switch (watch page) and the profile form: saved on the profile, like its other settings
  const toggleBlockPopups = useCallback((on) => {
    // the sources get re-ordered: stay on the one playing (the starting pick must not run again)
    userPickedRef.current = true;
    setBlockPopups(on);
    storeBlockPopups(on);
    const userId = localStorage.getItem("userId");
    const profileId = localStorage.getItem("activeProfileId");
    if (userId && profileId) patchProfile(userId, profileId, { block_popups: on }).catch(() => {});
  }, []);

  const allowPopupsOnce = useCallback((key) => {
    setAllowedOnce((prev) => new Set(prev).add(key));
    // the offer goes away: the remote lands on the source it was about
    setTimeout(() => document.querySelector(".watchpage__chip.is-selected")?.focus({ preventScroll: true }), 0);
  }, []);

  // Smart playback: did the current source play? Reported to the server (it opens the source that
  // worked next time, and ranks providers); falls back when a source never loads.
  useEffect(() => {
    autoFailedRef.current = new Set(); // new title / episode: every source gets a fresh chance
    setFailedTick((n) => n + 1);
    setAllowedOnce(new Set()); // "Allow pop-ups for this source" was for that title only
  }, [titleId, seasonNumber, episodeNumber]);

  useEffect(() => {
    iframeLoadedRef.current = false;
    const p = providers.find((x) => x.key === selectedKey);
    if (!p || sourceType !== "iframe" || !title?.id) {
      attemptRef.current = null;
      return;
    }
    const pid = localStorage.getItem("activeProfileId");
    const sandboxed = !!sandboxAttr;
    const lifted = blockPopups && !sandboxed; // pop-ups allowed for this source only ("Allow pop-ups")
    const attempt = { key: p.key, startedAt: Date.now(), playing: false, reported: false };
    attempt.report = (worked) => {
      if (attempt.reported || !pid) return;
      attempt.reported = true;
      reportPlayback({ profileId: pid, titleId: title.id, provider: p.key, worked, sandboxed }).catch(() => {});
    };
    attemptRef.current = attempt;
    const nextSource = () =>
      providers.find((x) => x.key !== p.key && !x.down && !autoFailedRef.current.has(x.key));

    const onMessage = (e) => {
      if (!iframeRef.current || e.source !== iframeRef.current.contentWindow) return;
      if (readPlayerEvent(e.data)?.playing && !attempt.playing) {
        attempt.playing = true;
        setBanner(null);
        attempt.report(true);
        // it didn't play sandboxed, it plays with pop-ups allowed: the sandbox was the problem
        if (lifted && p.sandboxOk !== "yes" && autoFailedRef.current.has(p.key)) learnSandboxFailure(p.key);
      }
    };
    window.addEventListener("message", onMessage);

    const timers = [
      // the page never loaded: move on by itself
      setTimeout(() => {
        if (iframeLoadedRef.current || attempt.playing) return;
        const next = nextSource();
        autoFailedRef.current.add(p.key);
        setFailedTick((n) => n + 1);
        // failed by itself while sandboxed: this profile's watch page now puts it last when pop-ups
        // are blocked (unless the scout saw it play sandboxed: then it is just down)
        if (sandboxed && p.sandboxOk !== "yes") learnSandboxFailure(p.key);
        if (!next) return;
        attempt.report(false);
        userPickedRef.current = true;
        setBanner({ text: t("sources.switched", { from: p.label, to: next.label }) });
        setSelectedKey(next.key);
      }, SOURCE_LOAD_TIMEOUT_MS),
      // loaded but silent: only for players that report playback, offer the next source
      p.sendsEvents &&
        setTimeout(() => {
          if (attempt.playing) return;
          const next = nextSource();
          if (next) setBanner({ text: t("sources.notPlaying", { source: p.label }), nextKey: next.key, nextLabel: next.label });
        }, SOURCE_SILENT_TIMEOUT_MS),
      // still on it after a while: it works (the only signal for players that report nothing)
      setTimeout(() => {
        if (document.visibilityState === "visible") attempt.report(true);
      }, SOURCE_STAYED_MS),
    ].filter(Boolean);

    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener("message", onMessage);
    };
  }, [selectedKey, resolvedUrl, sourceType, title?.id, providers, sandboxAttr]); // eslint-disable-line react-hooks/exhaustive-deps -- t: only the banner text, a new language must not restart the source

  // "switched to X" notices go away by themselves; "Not playing?" offers stay until used
  useEffect(() => {
    if (!banner || banner.nextKey) return;
    const timer = setTimeout(() => setBanner(null), 8000);
    return () => clearTimeout(timer);
  }, [banner]);

  // Every source change made by the viewer goes through here
  const switchSource = useCallback((key) => {
    const a = attemptRef.current;
    // left a source quickly without it ever playing: it didn't work
    if (a && a.key !== key && !a.playing && Date.now() - a.startedAt < SOURCE_QUICK_LEAVE_MS) a.report(false);
    userPickedRef.current = true;
    setBanner(null);
    setSelectedKey(key);
  }, []);

  // Watch progress from the player's own events (Videasy, CineSrc, VidCore "ended"):
  // saved every 15 s and on pause / seek / end, so "Continue watching" can resume and show a bar.
  useEffect(() => {
    if (!title?.id || sourceType !== "iframe") return;
    const pid = localStorage.getItem("activeProfileId");
    if (!pid) return;

    let current = { season: isTV ? seasonNumber : null, episode: isTV ? episodeNumber : null };
    let last = {}; // { position, duration } latest known, seconds
    let lastSavedAt = 0;
    let ended = false;

    const save = (extra = {}) =>
      saveWatchProgress({
        profileId: pid,
        titleId: title.id,
        ...current,
        position: last.position != null ? Math.floor(last.position) : null,
        duration: last.duration ? Math.floor(last.duration) : null,
        ...extra,
      }).catch(() => {});

    const onMessage = (e) => {
      // only the player this page loaded (not other frames / pages)
      if (!iframeRef.current || e.source !== iframeRef.current.contentWindow) return;
      const ev = readPlayerEvent(e.data);
      if (!ev) return;

      // the player moved to another episode by itself (auto-next / its own episode list)
      if (isTV && ev.season && ev.episode && (ev.season !== current.season || ev.episode !== current.episode)) {
        current = { season: ev.season, episode: ev.episode };
        last = {};
        ended = false;
      }
      if (ended) return;
      if (Number.isFinite(ev.position)) last.position = ev.position;
      if (Number.isFinite(ev.duration) && ev.duration > 0) last.duration = ev.duration;

      if (ev.ended) {
        ended = true;
        save({ finished: true });
        return;
      }
      const now = Date.now();
      if (last.position != null && (ev.flush || now - lastSavedAt > 15000)) {
        lastSavedAt = now;
        save();
      }
    };

    window.addEventListener("message", onMessage);
    return () => {
      window.removeEventListener("message", onMessage);
      if (!ended && last.position != null) save(); // leaving the page / changing source
    };
  }, [title?.id, sourceType, resolvedUrl, isTV, seasonNumber, episodeNumber]);

  const PlayerNode = useMemo(() => {
    if (!resolvedUrl) {
      return (
        <div className="watchpage__empty">
          <div className="watchpage__emptyCard">
            <div className="watchpage__emptyTitle">{t("player.chooseTitle")}</div>
            <div className="watchpage__emptyDesc">{t("player.chooseText")}</div>
            {providersError ? (
              <div style={{ marginTop: 10, opacity: 0.8, fontSize: 13 }}>
                {providersError}
              </div>
            ) : null}
          </div>
        </div>
      );
    }

    if (sourceType === "direct") {
      return (
        <video
          ref={videoRef}
          className="watchpage__video"
          controls
          playsInline
          src={resolvedUrl}
          onCanPlay={() => setSourceLoading(false)}
          onError={() => {
            setSourceLoading(false);
            setHint(t("player.notPlayable"));
          }}
        />
      );
    }

    return (
      <iframe
        // Block pop-ups: a new sandbox only applies to a new frame
        key={sandboxAttr ? "sandboxed" : "open"}
        ref={iframeRef}
        className="watchpage__iframe"
        src={resolvedUrl}
        title={t("player.label")}
        allow="autoplay; fullscreen *; picture-in-picture; encrypted-media"
        sandbox={sandboxAttr}
        allowFullScreen
        webkitallowfullscreen="true"
        mozallowfullscreen="true"
        loading="lazy"
        onLoad={() => {
          iframeLoadedRef.current = true;
          setSourceLoading(false);
          setHint("");
        }}
      />
    );
  }, [resolvedUrl, sourceType, providersError, sandboxAttr, t]);

  if (loading) {
    return (
      <div className="watchpage">
        <header className="watchpage__top">
          <Skeleton variant="circle" width="2.75rem" height="2.75rem" />
          <div className="watchpage__titles">
            <Skeleton variant="text" width="14rem" height="1.2rem" />
            <Skeleton variant="text" width="8rem" />
          </div>
        </header>
        <main className="watchpage__main">
          <Skeleton className="watchpage__playerWrap watchpage__playerWrap--skeleton" />
        </main>
      </div>
    );
  }

  if (err || !title) {
    return (
      <div className="watchpage">
        <EmptyState
          page
          tone="error"
          title={t("cantPlay")}
          actions={
            <>
              <Button variant="primary" to="/">{t("actions.goHome")}</Button>
              <Button variant="ghost" onClick={goBack}>{t("actions.goBack")}</Button>
            </>
          }
        >
          {err || t("common:errors.notFound", { context: "title" })}
        </EmptyState>
      </div>
    );
  }

  const selectedProvider = providers.find((x) => x.key === selectedKey);
  // re-rendered when autoFailedRef changes (setFailedTick)
  const offerAllow =
    sourceType === "iframe" &&
    shouldOfferAllow({ block: blockPopups, current: selectedProvider, sources: providers, failed: autoFailedRef.current, allowed: allowedOnce });
  const subtitle = [isTV ? t("seasonEpisode", { season: seasonNumber, episode: episodeNumber }) : "", metaLine].filter(Boolean).join(" · ");

  return (
    <div className="watchpage">
      <div className="watchpage__bg" aria-hidden="true" style={{ backgroundImage: tmdbBackground(backdrop, IMG.blurredBackground) }} />

      <header className="watchpage__top">
        <Button variant="glass" icon={<ArrowLeftIcon />} label={t("back")} onClick={goBack} className="watchpage__back" />

        <div className="watchpage__titles">
          <h1 className="watchpage__title">{title.title}</h1>
          {subtitle ? <p className="watchpage__subtitle">{subtitle}</p> : null}
        </div>

        <div className="watchpage__actions">
          {nextEpisode ? (
            <Button
              variant="glass"
              size="sm"
              iconRight={<ChevronRightIcon />}
              onClick={goToNextEpisode}
              title={t("seasonEpisode", { season: nextEpisode.season, episode: nextEpisode.episode })}
            >
              {t("nextEpisode")}
            </Button>
          ) : null}
          {nextPart ? (
            <Button variant="glass" size="sm" iconRight={<ChevronRightIcon />} onClick={goToNextPart} title={nextPart.title}>
              {t("nextMovie")}
            </Button>
          ) : null}
          {sourceType !== "none" ? (
            <Button
              variant="glass"
              size="sm"
              icon={<MaximizeIcon />}
              onClick={goFullscreen}
              title={t("fullscreenHint")}
              className="watchpage__fullscreenBtn"
            >
              <span className="watchpage__actionLabel">{t("fullscreen")}</span>
            </Button>
          ) : null}
        </div>
      </header>

      <main className="watchpage__main">
        <div
          ref={playerWrapRef}
          className={`watchpage__playerWrap${isPulsing ? " is-pulsing" : ""}`}
          // TV remote / keyboard: the player is a tile, OK = full screen with the remote
          // handed to the player (play / pause, seek...); Back leaves it
          tabIndex={sourceType !== "none" ? 0 : -1}
          aria-label={t("player.tileLabel")}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.target === e.currentTarget && sourceType !== "none") {
              e.preventDefault();
              goFullscreen();
            }
          }}
          onMouseEnter={() => setHoverPlayer(true)}
          onMouseLeave={() => setHoverPlayer(false)}
        >
          {PlayerNode}

          {sourceLoading && sourceType === "iframe" ? (
            <div className="watchpage__loading" aria-live="polite">
              <Spinner label={selectedProvider?.label ? t("player.loadingNamed", { source: selectedProvider.label }) : t("player.loadingSource")} />
            </div>
          ) : null}

          {sourceType !== "none" ? (
            <div className="watchpage__playerFocusHint" aria-hidden="true">
              <Trans t={t} i18nKey="keys.control" components={{ key: <span className="watchpage__key" /> }} />
            </div>
          ) : null}

          {playerKeysHint ? (
            <div className="watchpage__playerKeys" aria-hidden="true">
              <span><Trans t={t} i18nKey="keys.playPause" components={{ key: <span className="watchpage__key" /> }} /></span>
              <span><Trans t={t} i18nKey="keys.seek" components={{ key: <span className="watchpage__key" /> }} /></span>
              {hasRemote ? (
                <span><Trans t={t} i18nKey="keys.volume" components={{ key: <span className="watchpage__key" /> }} /></span>
              ) : null}
              <span><Trans t={t} i18nKey="keys.exit" components={{ key: <span className="watchpage__key" /> }} /></span>
            </div>
          ) : null}

          {banner ? (
            <div className="watchpage__softHint" role="status">
              <div className="watchpage__softHintText">{banner.text}</div>
              {banner.nextKey ? (
                <Button variant="secondary" size="sm" className="watchpage__softHintBtn" onClick={() => switchSource(banner.nextKey)}>
                  {t("sources.try", { source: banner.nextLabel })}
                </Button>
              ) : null}
            </div>
          ) : hint && !hoverPlayer ? (
            <div className="watchpage__softHint" role="status">
              <div className="watchpage__softHintText">{hint}</div>
            </div>
          ) : null}
        </div>

        {/* SOURCES: under the player, one row of chips (a blank player = try the next one) */}
        <section className="watchpage__sources" aria-label={t("sources.label")}>
          <div className="watchpage__sourcesHead">
            <h2 className="watchpage__sourcesTitle">{t("sources.title")}</h2>
            <p className="watchpage__sourcesHelp">{t("sources.help")}</p>
          </div>
          <div className="watchpage__sourceRow">
            <div className="ui-scroller watchpage__providerRow" role="group" aria-label={t("sources.choose")}>
              {providers.map((p) => (
                <Chip
                  key={p.key}
                  className="watchpage__chip"
                  selected={selectedKey === p.key}
                  onClick={() => switchSource(p.key)} // also stops the auto-reset to the first provider
                  title={p.down ? t("sources.downHint") : p.popupRisk ? t("popups.mayOpenHint") : undefined}
                >
                  {p.label}
                  {p.noPopups ? <span className="watchpage__chipTag">{t("popups.noPopups")}</span> : null}
                  {p.down ? <span className="watchpage__chipNote">{t("sources.down")}</span> : null}
                  {p.popupRisk && !p.down ? <span className="watchpage__chipNote">{t("popups.mayOpen")}</span> : null}
                </Chip>
              ))}
              <Chip className="watchpage__chip" selected={selectedKey === "custom"} onClick={() => switchSource("custom")}>
                <LinkIcon className="watchpage__chipIcon" aria-hidden="true" />
                {t("sources.custom")}
              </Chip>
            </div>
            {/* Block pop-ups (9.1): beside the sources (Right from the last one); OK toggles it, the
                focus stays on it while the player reloads */}
            <Switch
              className="watchpage__popupSwitch"
              checked={blockPopups}
              onChange={toggleBlockPopups}
              label={t("popups.block")}
              title={t("popups.blockHint")}
            />
          </div>

          {offerAllow ? (
            <div className="watchpage__popupOffer" role="status">
              <p className="watchpage__popupOfferText">{t("popups.offer", { source: selectedProvider.label })}</p>
              <Button variant="secondary" size="sm" onClick={() => allowPopupsOnce(selectedProvider.key)}>
                {t("popups.allowOnce")}
              </Button>
            </div>
          ) : null}

          {selectedKey === "custom" ? (
            <div className="watchpage__customBox">
              <input
                className="watchpage__input"
                type="url"
                value={customUrl}
                onChange={(e) => setCustomUrl(e.target.value)}
                placeholder={t("sources.customPlaceholder")}
                aria-label={t("sources.customLabel")}
                spellCheck={false}
              />
              {customUrl ? (
                <Button variant="ghost" size="sm" onClick={() => setCustomUrl("")}>
                  {t("catalog:search.clear")}
                </Button>
              ) : null}
            </div>
          ) : null}
          {providersError ? <p className="watchpage__sourcesHelp">{providersError}</p> : null}
        </section>

        <div className="watchpage__info">
          <WatchInfo
            title={title}
            isTV={isTV}
            seasonNumber={seasonNumber}
            episodeNumber={episodeNumber}
            onPlayEpisode={(season, episode) => {
              navigate(`/watch/${titleId}?season=${season}&episode=${episode}`, { replace: true });
              window.scrollTo({ top: 0, behavior: "smooth" }); // back to the player
            }}
          />
        </div>
      </main>
    </div>
  );
}

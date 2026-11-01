import React, { useEffect, useMemo, useState, useRef, useCallback } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import { formatNumber } from "../i18n/format";
import { genreName, splitGenres } from "./detail/DetailHero";
import "./WatchPage.css";

import { fetchTitleById, fetchMovieById, fetchProviders, buildProviderLinks } from "../api/titlesApi";
import { saveWatchProgress, reportPlayback, fetchPreferredSource } from "../api/recoApi";
import { enterPlayer, setBackHandler } from "../tv/spatialNavigation";
import { tmdbBackground, IMG } from "../utils/tmdbImage";
import { Button, Chip, EmptyState, Skeleton, Spinner } from "../design";
import { ArrowLeftIcon, ChevronRightIcon, MaximizeIcon, LinkIcon } from "../design/icons";
import WatchInfo from "./watch/WatchInfo";
import { usePlayerRemote } from "./watch/playerRemote";

// sources saved by older versions used the DB column names
const LEGACY_SOURCE_KEYS = {
  video_url: "vidking",
  movie_link2: "videasy", episode_link2: "videasy",
  movie_link3: "vidsrc", episode_link3: "vidsrc",
  movie_link4: "vidfast", episode_link4: "vidfast",
  movie_link5: "vidplus", episode_link5: "vidplus",
  movie_link6: "111movies", episode_link6: "111movies",
};

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
// Smart playback timings
const SOURCE_LOAD_TIMEOUT_MS = 15000; // page never loaded: switch to the next source by itself
const SOURCE_SILENT_TIMEOUT_MS = 20000; // loaded, but a player that reports playback stayed silent: offer the next one
const SOURCE_STAYED_MS = 120000; // stayed this long on a source: it works
const SOURCE_QUICK_LEAVE_MS = 60000; // switched away sooner, without playback: it didn't work

// Normalize the players' postMessage events (formats from their docs) to
// { position?, duration?, playing?, ended?, flush?, season?, episode? } (seconds), or null.
// playing = proof the source actually plays (smart playback).
function readPlayerEvent(raw) {
  let data = raw;
  if (typeof data === "string") {
    if (data.startsWith("vidcore:")) data = { type: data };
    else {
      try {
        data = JSON.parse(data);
      } catch {
        return null;
      }
    }
  }
  if (!data || typeof data !== "object" || typeof data.type !== "string") return null;
  const num = (v) => (v === null || v === undefined || v === "" ? NaN : Number(v));

  // Videasy: { type: "PLAYER_EVENT", data: { player_status, player_progress, player_duration, player_info } }
  if (data.type === "PLAYER_EVENT") {
    let d = data.data;
    if (typeof d === "string") {
      try {
        d = JSON.parse(d);
      } catch {
        return null;
      }
    }
    if (!d) return null;
    const status = String(d.player_status || "");
    return {
      position: num(d.player_progress),
      duration: num(d.player_duration),
      playing: status === "playing" || Number(d.player_progress) > 0,
      ended: status === "completed",
      flush: status === "paused" || status === "seeked",
      season: num(d.player_info?.season) || undefined,
      episode: num(d.player_info?.episode) || undefined,
    };
  }

  // CineSrc: { type: "cinesrc:timeupdate", currentTime, duration }, cinesrc:ended, cinesrc:nextepisode ...
  if (data.type.startsWith("cinesrc:")) {
    const kind = data.type.slice("cinesrc:".length);
    if (kind === "timeupdate" || kind === "seeked") {
      const position = num(data.currentTime);
      return { position, duration: num(data.duration), playing: position > 0, flush: kind === "seeked" };
    }
    if (kind === "play") return { playing: true };
    if (kind === "pause") return { flush: true };
    if (kind === "ended") return { ended: true };
    if (kind === "nextepisode") return { season: num(data.season), episode: num(data.episode) };
    return null;
  }

  // VidCore: only play / pause / ended, no position
  if (data.type === "vidcore:play") return { playing: true };
  if (data.type === "vidcore:ended") return { ended: true };
  return null;
}

function readPositiveInt(search, key, fallback) {
  const v = new URLSearchParams(search).get(key);
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}


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
  const providers = useMemo(() => {
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

    const available = new Set(providers.map((p) => p.key));
    const pick = [
      serverPref?.title,
      hasPrefsRef.current ? savedKeyRef.current : null,
      serverPref?.profile,
      providers[0]?.key,
    ].find((key) => key && available.has(key));

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

  // Smart playback: did the current source play? Reported to the server (it opens the source that
  // worked next time, and ranks providers); falls back when a source never loads.
  useEffect(() => {
    autoFailedRef.current = new Set(); // new title / episode: every source gets a fresh chance
  }, [titleId, seasonNumber, episodeNumber]);

  useEffect(() => {
    iframeLoadedRef.current = false;
    const p = providers.find((x) => x.key === selectedKey);
    if (!p || sourceType !== "iframe" || !title?.id) {
      attemptRef.current = null;
      return;
    }
    const pid = localStorage.getItem("activeProfileId");
    const attempt = { key: p.key, startedAt: Date.now(), playing: false, reported: false };
    attempt.report = (worked) => {
      if (attempt.reported || !pid) return;
      attempt.reported = true;
      reportPlayback({ profileId: pid, titleId: title.id, provider: p.key, worked }).catch(() => {});
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
      }
    };
    window.addEventListener("message", onMessage);

    const timers = [
      // the page never loaded: move on by itself
      setTimeout(() => {
        if (iframeLoadedRef.current || attempt.playing) return;
        const next = nextSource();
        if (!next) return;
        attempt.report(false);
        autoFailedRef.current.add(p.key);
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
  }, [selectedKey, resolvedUrl, sourceType, title?.id, providers]); // eslint-disable-line react-hooks/exhaustive-deps -- t: only the banner text, a new language must not restart the source

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
        ref={iframeRef}
        className="watchpage__iframe"
        src={resolvedUrl}
        title={t("player.label")}
        allow="autoplay; fullscreen *; picture-in-picture; encrypted-media"
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
  }, [resolvedUrl, sourceType, providersError, t]);

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
          <div className="ui-scroller watchpage__providerRow" role="group" aria-label={t("sources.choose")}>
            {providers.map((p) => (
              <Chip
                key={p.key}
                className="watchpage__chip"
                selected={selectedKey === p.key}
                onClick={() => switchSource(p.key)} // also stops the auto-reset to the first provider
                title={p.down ? t("sources.downHint") : undefined}
              >
                {p.label}
                {p.down ? <span className="watchpage__chipNote">{t("sources.down")}</span> : null}
              </Chip>
            ))}
            <Chip className="watchpage__chip" selected={selectedKey === "custom"} onClick={() => switchSource("custom")}>
              <LinkIcon className="watchpage__chipIcon" aria-hidden="true" />
              {t("sources.custom")}
            </Chip>
          </div>

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

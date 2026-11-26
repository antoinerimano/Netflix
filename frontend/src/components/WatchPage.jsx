import React, { useEffect, useMemo, useState, useRef, useCallback } from "react";
import { useNavigate, useParams, useLocation } from "react-router-dom";
import { Trans, useTranslation } from "react-i18next";
import { formatNumber } from "../i18n/format";
import { genreName, splitGenres } from "./detail/DetailHero";
import "./WatchPage.css";

import { fetchTitleById, fetchMovieById, fetchProviders, buildProviderLinks, fetchSimilarTitles } from "../api/titlesApi";
import { saveWatchProgress, reportPlayback, fetchPreferredSource, fetchCollection } from "../api/recoApi";
import { enterPlayer, setBackHandler } from "../tv/spatialNavigation";
import { tmdbBackground, IMG } from "../utils/tmdbImage";
import { Button, Chip, EmptyState, Skeleton, Spinner } from "../design";
import { ArrowLeftIcon, ChevronRightIcon, MaximizeIcon, LinkIcon } from "../design/icons";
import WatchInfo from "./watch/WatchInfo";
import { usePlayerRemote } from "./watch/playerRemote";
import { isPlayerMessage, nextSource, orderSources } from "./watch/sourceOrder";
import UpNextCard from "./watch/UpNextCard";
import ReportProblem from "./watch/ReportProblem";
import { NEXT_COUNTDOWN_S, findNextEpisode, isEpisodeEnding, upNextMode } from "./watch/autoNext";

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
  const autoFailedRef = useRef(new Set()); // sources tried on this page that didn't play
  const autoOffRef = useRef(false); // "Undo" pressed: no more automatic switches for this title / episode
  const sourceOrderRef = useRef([]);
  const [banner, setBanner] = useState(null); // { text, nextKey?, nextLabel?, undoKey? }
  const [allFailed, setAllFailed] = useState(null); // { count }: every source was tried, none played
  const [reloadNonce, setReloadNonce] = useState(0); // "Try again" on the same source reloads it
  const bannerRef = useRef(null);
  const allFailedRef = useRef(null);
  const pointerOverRef = useRef(false);
  // next episode by the app (9.3): the card at an episode's end
  const [upNext, setUpNext] = useState(null); // { mode: countdown | offer | still | end, next, seconds }
  const [similar, setSimilar] = useState(null); // show over: "More like this" (null = not loaded)
  const upNextRef = useRef(null);
  const upNextDoneRef = useRef(false); // the card was shown for this episode: once per episode
  const autoStartsRef = useRef(0); // episodes started by themselves since the last key press
  const [serverPref, setServerPref] = useState(undefined); // undefined = loading, null = unavailable
  const [reportOpen, setReportOpen] = useState(false); // "Playback problem?" (9.8)
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
  const nextEpisode = useMemo(
    () => (isTV ? findNextEpisode(title?.seasons, seasonNumber, episodeNumber) : null),
    [isTV, title, seasonNumber, episodeNumber]
  );

  // "Play next episode automatically" (profile setting, on by default)
  const autoplayNext = useMemo(() => {
    try {
      return JSON.parse(localStorage.getItem("activeProfile") || "{}")?.autoplay_next !== false;
    } catch {
      return true;
    }
  }, [activeProfileId]); // eslint-disable-line react-hooks/exhaustive-deps -- read again for another profile

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
    userPickedRef.current = true; // on the same source
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

  // TV remote Back / Escape: back to this title's details page (leaves full screen first);
  // with the next-episode card up, Back is its Cancel
  const cancelUpNextRef = useRef(null);
  useEffect(
    () => setBackHandler(upNext ? () => cancelUpNextRef.current?.() : goBack),
    [goBack, upNext]
  );

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

  // Every source in the order they're tried: what worked before first, what failed on this title last
  const sourceOrder = useMemo(
    () =>
      orderSources(providers, {
        title: serverPref?.title,
        saved: prefsLoaded && hasPrefsRef.current ? savedKeyRef.current : null,
        profile: serverPref?.profile,
        failed: serverPref?.failed,
        anime: title?.section === "anime", // ROADMAP 9.5: the sources that play anime first
      }),
    [providers, serverPref, prefsLoaded, title?.section]
  );
  sourceOrderRef.current = sourceOrder;

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

    const pick = sourceOrder[0];

    if (pick) {
      if (selectedKey !== pick) setSelectedKey(pick);
    } else if (selectedKey !== "custom") {
      setSelectedKey("custom"); // no provider can play this title
    }
  }, [prefsLoaded, serverPref, title, providers, providerDefs, selectedKey, providersError, sourceOrder]);

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
    // new title / episode: every source gets a fresh chance, and switches by itself again
    autoFailedRef.current = new Set();
    autoOffRef.current = false;
    setAllFailed(null);
    upNextDoneRef.current = false;
    setUpNext(null);
    setSimilar(null);
  }, [titleId, seasonNumber, episodeNumber]);

  // The source didn't play: try the next one by itself (9.2), through the whole list, then one
  // clear screen. "Played" = a real player event (play / time), not the iframe's load: a dead
  // embed page loads too. Players that report nothing can only fail by never loading.
  useEffect(() => {
    iframeLoadedRef.current = false;
    const p = providers.find((x) => x.key === selectedKey);
    if (!p || sourceType !== "iframe" || !title?.id) {
      attemptRef.current = null;
      return;
    }
    const pid = localStorage.getItem("activeProfileId");
    const attempt = { key: p.key, startedAt: Date.now(), playing: false, alive: false, reported: false };
    attempt.report = (worked) => {
      if (attempt.reported || !pid) return;
      attempt.reported = true;
      reportPlayback({ profileId: pid, titleId: title.id, provider: p.key, worked }).catch(() => {});
    };
    attemptRef.current = attempt;
    const timers = [];
    const later = (fn, ms) => timers.push(setTimeout(fn, ms));

    const isFullscreen = () => !!(document.fullscreenElement || document.webkitFullscreenElement);
    // the viewer is busy with the player (its own play button, full screen): offer, don't switch
    const engaged = () => isFullscreen() || pointerOverRef.current || document.activeElement === iframeRef.current;

    const failed = () => {
      if (attempt.playing || attempt.failed) return;
      // tab in the background / full screen: decide when the viewer can see it
      if (document.visibilityState !== "visible" || isFullscreen()) {
        later(failed, 3000);
        return;
      }
      attempt.failed = true;
      attempt.report(false);
      autoFailedRef.current.add(p.key);
      const nextKey = nextSource(sourceOrderRef.current, p.key, autoFailedRef.current);
      const next = providers.find((x) => x.key === nextKey);
      if (!next) {
        setBanner(null);
        setAllFailed({ count: autoFailedRef.current.size });
        return;
      }
      if (autoOffRef.current || engaged()) {
        setBanner({ text: t("sources.notPlaying", { source: p.label }), nextKey: next.key, nextLabel: next.label });
        return;
      }
      userPickedRef.current = true;
      setBanner({ text: t("sources.trying", { from: p.label, to: next.label }), undoKey: p.key });
      setSelectedKey(next.key);
    };

    const onMessage = (e) => {
      if (!iframeRef.current || e.source !== iframeRef.current.contentWindow) return;
      if (isPlayerMessage(e.data)) attempt.alive = true;
      if (readPlayerEvent(e.data)?.playing && !attempt.playing) {
        attempt.playing = true;
        setBanner((b) => (b?.nextKey ? null : b)); // an offer to move on is moot; an Undo stays
        setAllFailed(null);
        attempt.report(true);
      }
    };
    window.addEventListener("message", onMessage);

    // the page never loaded
    later(() => {
      if (!iframeLoadedRef.current && !attempt.alive) failed();
    }, SOURCE_LOAD_TIMEOUT_MS);
    // a player that reports playback loaded, but never played
    if (p.sendsEvents) later(failed, SOURCE_SILENT_TIMEOUT_MS);
    // still on it after a while: it works (the only signal for players that report nothing)
    later(() => {
      if (document.visibilityState === "visible") attempt.report(true);
    }, SOURCE_STAYED_MS);

    return () => {
      timers.forEach(clearTimeout);
      window.removeEventListener("message", onMessage);
    };
  }, [selectedKey, resolvedUrl, sourceType, title?.id, providers, reloadNonce]); // eslint-disable-line react-hooks/exhaustive-deps -- t: only the banner text, a new language must not restart the source

  // A banner / screen with the focus goes away: the remote stays on the player, never on nothing
  const keepFocusOnPlayer = useCallback((box) => {
    if (box?.contains(document.activeElement)) playerWrapRef.current?.focus({ preventScroll: true });
  }, []);

  // "trying X" notices go away by themselves; "Not playing?" offers stay until used
  useEffect(() => {
    if (!banner || banner.nextKey) return;
    const timer = setTimeout(() => {
      keepFocusOnPlayer(bannerRef.current);
      setBanner(null);
    }, banner.undoKey ? 10000 : 8000);
    return () => clearTimeout(timer);
  }, [banner, keepFocusOnPlayer]);

  // every source failed: the remote goes to "Try again" (unless the viewer is elsewhere on the page)
  useEffect(() => {
    if (!allFailed) return;
    const a = document.activeElement;
    if (!a || a === document.body || playerWrapRef.current?.contains(a)) {
      allFailedRef.current?.querySelector("button")?.focus({ preventScroll: true });
    }
  }, [allFailed]);

  // Every source change made by the viewer goes through here
  const switchSource = useCallback((key, { judge = true } = {}) => {
    const a = attemptRef.current;
    // left a source quickly without it ever playing: it didn't work
    if (judge && a && a.key !== key && !a.playing && Date.now() - a.startedAt < SOURCE_QUICK_LEAVE_MS) a.report(false);
    userPickedRef.current = true;
    keepFocusOnPlayer(bannerRef.current);
    keepFocusOnPlayer(allFailedRef.current);
    setBanner(null);
    setAllFailed(null);
    setSelectedKey(key);
  }, [keepFocusOnPlayer]);

  // "Undo" on "X didn't play, trying Y": back to X, and no more switching by itself here
  const undoSwitch = useCallback(
    (key) => {
      autoOffRef.current = true;
      autoFailedRef.current.delete(key);
      switchSource(key, { judge: false }); // the viewer chose: Y wasn't given its chance, not a failure
    },
    [switchSource]
  );

  // "Try again" on the all-failed screen: the whole list once more, from the best source
  const retryAll = useCallback(() => {
    autoFailedRef.current = new Set();
    autoOffRef.current = false;
    const first = sourceOrderRef.current[0];
    keepFocusOnPlayer(allFailedRef.current);
    setAllFailed(null);
    setBanner(null);
    userPickedRef.current = true;
    if (first && first !== selectedKey) setSelectedKey(first);
    else setReloadNonce((n) => n + 1);
  }, [keepFocusOnPlayer, selectedKey]);

  // "Playback problem?" sent, then "Try <next source>": the reported one counts as tried
  const reportNext = useMemo(() => {
    if (!reportOpen) return null;
    const key = nextSource(sourceOrderRef.current, selectedKey, new Set([...autoFailedRef.current, selectedKey]));
    return providers.find((p) => p.key === key) || null;
  }, [reportOpen, selectedKey, providers]);

  const tryAfterReport = useCallback(
    (key) => {
      autoFailedRef.current.add(selectedKey);
      setReportOpen(false);
      switchSource(key, { judge: false }); // the report already said how it went
    },
    [selectedKey, switchSource]
  );

  // "Choose a source": the remote goes to the chips under the player
  const chooseSourceYourself = useCallback(() => {
    const chips = [...document.querySelectorAll(".watchpage__providerRow .watchpage__chip")];
    (chips.find((c) => c.classList.contains("is-selected")) || chips[0])?.focus({ preventScroll: false });
  }, []);

  // Next episode by the app (9.3), for every source: on the player's "ended" event, or in the
  // episode's last 30 s when the player sends times, a card: "Next episode in 10" (Play now /
  // Cancel), "Still watching?" after 3 episodes started by themselves, "More like this" at the end.
  useEffect(() => {
    if (!isTV || sourceType !== "iframe" || !title?.id) return undefined;
    const since = Date.now(); // a late message from the episode before (its page still unloading) isn't this one's end
    const onMessage = (e) => {
      if (!iframeRef.current || e.source !== iframeRef.current.contentWindow) return;
      const ev = readPlayerEvent(e.data);
      if (!ev) return;
      // the player went to another episode by itself (its own auto-next): leave it to the player
      if (ev.season && ev.episode && (ev.season !== seasonNumber || ev.episode !== episodeNumber)) {
        upNextDoneRef.current = true;
        keepFocusOnPlayer(upNextRef.current);
        setUpNext(null);
        return;
      }
      if (upNextDoneRef.current || !isEpisodeEnding(ev) || Date.now() - since < 3000) return;
      upNextDoneRef.current = true;
      const mode = upNextMode({ next: nextEpisode, autoplay: autoplayNext, autoStarts: autoStartsRef.current });
      setUpNext({ mode, next: nextEpisode, seconds: NEXT_COUNTDOWN_S });
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [isTV, sourceType, title?.id, resolvedUrl, seasonNumber, episodeNumber, nextEpisode, autoplayNext, keepFocusOnPlayer]);

  // someone is there: a key, a click, the player taking the focus -> no "Still watching?"
  useEffect(() => {
    const active = () => {
      autoStartsRef.current = 0;
    };
    const onBlur = () => {
      if (document.activeElement === iframeRef.current) active(); // a click in the player
    };
    window.addEventListener("keydown", active, true);
    window.addEventListener("pointerdown", active, true);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", active, true);
      window.removeEventListener("pointerdown", active, true);
      window.removeEventListener("blur", onBlur);
    };
  }, []);

  const playNext = useCallback(
    ({ auto = false } = {}) => {
      const next = upNext?.next || nextEpisode;
      if (!next) return;
      autoStartsRef.current = auto ? autoStartsRef.current + 1 : 0;
      keepFocusOnPlayer(upNextRef.current);
      setUpNext(null);
      userPickedRef.current = true; // the same source plays the next episode
      navigate(`/watch/${titleId}?season=${next.season}&episode=${next.episode}`, { replace: true });
    },
    [upNext, nextEpisode, keepFocusOnPlayer, navigate, titleId]
  );

  const cancelUpNext = useCallback(() => {
    keepFocusOnPlayer(upNextRef.current);
    setUpNext(null);
  }, [keepFocusOnPlayer]);
  cancelUpNextRef.current = cancelUpNext;

  // the countdown: Play now by itself at 0
  useEffect(() => {
    if (upNext?.mode !== "countdown") return undefined;
    if (upNext.seconds <= 0) {
      playNext({ auto: true });
      return undefined;
    }
    const timer = setTimeout(
      () => setUpNext((u) => (u?.mode === "countdown" ? { ...u, seconds: u.seconds - 1 } : u)),
      1000
    );
    return () => clearTimeout(timer);
  }, [upNext, playNext]);

  // the card takes the remote (unless the viewer is elsewhere on the page); in full screen too
  const upNextShown = upNext?.mode || "";
  useEffect(() => {
    if (!upNextShown) return;
    const a = document.activeElement;
    if (!a || a === document.body || playerWrapRef.current?.contains(a)) {
      upNextRef.current?.querySelector("button")?.focus({ preventScroll: true });
    }
  }, [upNextShown]);

  // show over: a few titles like this one
  useEffect(() => {
    if (upNextShown !== "end" || similar || !title?.id) return undefined;
    let alive = true;
    fetchSimilarTitles(title.id, 3)
      .then((list) => alive && setSimilar(list.slice(0, 3)))
      .catch(() => alive && setSimilar([]));
    return () => {
      alive = false;
    };
  }, [upNextShown, similar, title?.id]);

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
        key={reloadNonce}
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
  }, [resolvedUrl, sourceType, providersError, t, reloadNonce]);

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
          data-tv-inner="" // the remote reaches the buttons shown over it ("Undo", "Try again") with up / down
          aria-label={t("player.tileLabel")}
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.target === e.currentTarget && sourceType !== "none") {
              e.preventDefault();
              goFullscreen();
            }
          }}
          onMouseEnter={() => {
            pointerOverRef.current = true;
            setHoverPlayer(true);
          }}
          onMouseLeave={() => {
            pointerOverRef.current = false;
            setHoverPlayer(false);
          }}
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

          {allFailed ? (
            <div ref={allFailedRef} className="watchpage__allFailed" role="alert">
              <div className="watchpage__emptyCard">
                <div className="watchpage__emptyTitle">{t("sources.allFailedTitle")}</div>
                <div className="watchpage__emptyDesc">{t("sources.allFailedText")}</div>
                <div className="watchpage__allFailedActions">
                  <Button variant="primary" size="sm" onClick={retryAll}>
                    {t("sources.tryAgain")}
                  </Button>
                  <Button variant="secondary" size="sm" onClick={chooseSourceYourself}>
                    {t("player.chooseTitle")}
                  </Button>
                  <Button variant="ghost" size="sm" to="/status">
                    {t("problem.status")}
                  </Button>
                </div>
              </div>
            </div>
          ) : null}

          {upNext ? (
            <UpNextCard
              ref={upNextRef}
              mode={upNext.mode}
              next={upNext.next}
              seconds={upNext.seconds}
              showTitle={title.title}
              similar={similar}
              onPlay={() => playNext()}
              onCancel={cancelUpNext}
              onOpenTitle={(item) => navigate(`/${item.type === "tv" ? "tv" : "movies"}/${item.id}`)}
              onMoreLikeThis={() => navigate(`/tv/${titleId}`)}
            />
          ) : null}

          {banner ? (
            <div ref={bannerRef} className="watchpage__softHint" role="status">
              <div className="watchpage__softHintText">{banner.text}</div>
              {banner.nextKey ? (
                <Button variant="secondary" size="sm" className="watchpage__softHintBtn" onClick={() => switchSource(banner.nextKey)}>
                  {t("sources.try", { source: banner.nextLabel })}
                </Button>
              ) : banner.undoKey ? (
                <Button variant="secondary" size="sm" className="watchpage__softHintBtn" onClick={() => undoSwitch(banner.undoKey)}>
                  {t("sources.undo")}
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
          {/* the chips, then "Playback problem?" on the same line: Right from the last chip reaches it */}
          <div className="watchpage__sourcesBar">
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
          {selectedProvider && sourceType === "iframe" ? (
            <Button variant="ghost" size="sm" className="watchpage__reportBtn" onClick={() => setReportOpen(true)}>
              {t("problem.open")}
            </Button>
          ) : null}
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

      {selectedProvider ? (
        <ReportProblem
          open={reportOpen}
          onClose={() => setReportOpen(false)}
          source={selectedProvider}
          titleId={title.id}
          season={isTV ? seasonNumber : null}
          episode={isTV ? episodeNumber : null}
          next={reportNext}
          onTryNext={tryAfterReport}
        />
      ) : null}
    </div>
  );
}

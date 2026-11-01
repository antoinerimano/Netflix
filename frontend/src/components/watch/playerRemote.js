// src/components/watch/playerRemote.js
// Embedded players are cross-origin iframes: once one has the focus, the page receives no key at
// all, so a TV remote can only leave it if the browser does it (full screen + Back / Escape).
// Players with a documented postMessage API are driven from the page instead: the focus stays on
// the player tile, and OK / arrows become commands. The remote never leaves the app.
//
// Supported: CineSrc (https://cinesrc.st/docs, "Player Methods"). Others (Videasy, VidFast,
// VidSrc, 111movies, VidCore) document no inbound commands: they get the full screen hand-off.
import { useEffect, useRef } from 'react';

const SEEK_STEP = 10; // seconds per ◀ / ▶
const VOLUME_STEP = 0.1;

const hostOf = (url) => {
  try {
    return new URL(url).hostname;
  } catch {
    return '';
  }
};
const originOf = (url) => {
  try {
    return new URL(url).origin;
  } catch {
    return '';
  }
};

const APIS = {
  cinesrc: {
    matches: (url) => /(^|\.)cinesrc\.st$/i.test(hostOf(url)),
    send(win, origin, command, args = []) {
      win.postMessage({ type: 'cinesrc:command', command, args }, origin);
    },
    /** player event -> { paused?, time?, volume?, muted? } */
    read(data) {
      if (!data || typeof data !== 'object' || typeof data.type !== 'string' || !data.type.startsWith('cinesrc:')) return null;
      const kind = data.type.slice('cinesrc:'.length);
      if (kind === 'play') return { paused: false };
      if (kind === 'pause' || kind === 'ended') return { paused: true };
      if (kind === 'timeupdate' || kind === 'seeked') return { time: Number(data.currentTime) };
      if (kind === 'volumechange') return { volume: Number(data.volume), muted: !!data.muted };
      return null;
    },
  },
};

/** The API of the player at url, or null (no remote control: hand the focus to it in full screen) */
export function remoteApiFor(url) {
  return Object.values(APIS).find((api) => api.matches(url || '')) || null;
}

/**
 * Remote control of a player with an API while its tile has the focus (in full screen or not):
 *   OK = play / pause, ◀ / ▶ = -10 s / +10 s, ▲ / ▼ = volume (in full screen only, outside it they
 *   still move around the page). Back / Escape are left alone (leave full screen, then the page).
 */
export function usePlayerRemote({ url, iframeRef, wrapRef }) {
  const state = useRef({ paused: true, time: 0, volume: 1, muted: false });
  const api = remoteApiFor(url);

  // the player's state, from its events
  useEffect(() => {
    if (!api) return undefined;
    state.current = { paused: true, time: 0, volume: 1, muted: false };
    const onMessage = (e) => {
      if (!iframeRef.current || e.source !== iframeRef.current.contentWindow) return;
      let data = e.data;
      if (typeof data === 'string') {
        try {
          data = JSON.parse(data);
        } catch {
          return;
        }
      }
      const ev = api.read(data);
      if (!ev) return;
      if (Number.isNaN(ev.time)) delete ev.time;
      Object.assign(state.current, ev);
    };
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [api, url, iframeRef]);

  // keys, before the page's own navigation (capture phase)
  useEffect(() => {
    if (!api) return undefined;
    const send = (command, args) => {
      const win = iframeRef.current?.contentWindow;
      if (win) api.send(win, originOf(url), command, args);
    };
    const onKey = (e) => {
      const wrap = wrapRef.current;
      if (!wrap || document.activeElement !== wrap || e.altKey || e.ctrlKey || e.metaKey) return;
      const fullscreen = !!(document.fullscreenElement || document.webkitFullscreenElement);
      const s = state.current;
      let handled = true;
      if (e.key === 'Enter' || e.key === ' ' || e.key === 'MediaPlayPause') {
        if (!fullscreen && e.key === 'Enter') return; // outside full screen OK opens it (the tile's own handler)
        send(s.paused ? 'play' : 'pause');
        s.paused = !s.paused;
      } else if (e.key === 'MediaPlay') {
        send('play');
        s.paused = false;
      } else if (e.key === 'MediaPause') {
        send('pause');
        s.paused = true;
      } else if (fullscreen && (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'MediaRewind' || e.key === 'MediaFastForward')) {
        const back = e.key === 'ArrowLeft' || e.key === 'MediaRewind';
        s.time = Math.max(0, (s.time || 0) + (back ? -SEEK_STEP : SEEK_STEP));
        send('seek', [s.time]);
      } else if (fullscreen && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
        s.volume = Math.min(1, Math.max(0, (s.volume ?? 1) + (e.key === 'ArrowUp' ? VOLUME_STEP : -VOLUME_STEP)));
        send('setVolume', [s.volume]);
        if (s.muted && e.key === 'ArrowUp') send('setMuted', [false]);
      } else {
        handled = false;
      }
      if (handled) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [api, url, iframeRef, wrapRef]);

  return { hasRemote: !!api };
}

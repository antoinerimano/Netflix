// Trailer previews on the home rows: one at a time for the whole page, started by the mouse
// (hover) or the TV remote / keyboard (focus). Cards read only their own state
// (usePreviewPhase), so a preview starting or stopping re-renders that card, not the row.
//
//   request(key, src, 'mouse' | 'focus')   the card is hovered / focused
//   cancel(key)                            left / blurred
//
// Timeline after request():
//   0 ms            'arming'   nothing loads (moving across a row costs nothing)
//   LOAD_DELAY      'loading'  the <video> is created and downloads (the clip is small, faststart)
//   SHOW_DELAY[x]   'showing'  once the video can play: it fades in over the artwork
// The remote waits longer: people stop on a card for a moment while moving along a row.
import { useSyncExternalStore } from 'react';

export const LOAD_DELAY = 250;
export const SHOW_DELAY = { mouse: 700, focus: 1500 };
const MUTED_KEY = 'previewMuted';

const defaultCanPreview = () => {
  if (typeof window === 'undefined') return false;
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false;
  const c = navigator.connection;
  if (c && (c.saveData || /(^|-)2g$/.test(c.effectiveType || ''))) return false; // data saver, 2G
  return document.visibilityState !== 'hidden';
};

const readMuted = (storage) => {
  try {
    return storage?.getItem(MUTED_KEY) !== '0'; // muted unless the viewer turned the sound on
  } catch {
    return true;
  }
};

export function createPreviewStore({ canPreview = defaultCanPreview, storage = globalThis.localStorage } = {}) {
  let active = null; // { key, src, phase, wantShow, ready }
  let muted = readMuted(storage);
  const failed = new Set(); // clips that didn't play: not tried again during this visit
  const timers = [];
  const listeners = new Set();

  const emit = () => listeners.forEach((l) => l());
  const clearTimers = () => {
    while (timers.length) clearTimeout(timers.pop());
  };
  const setPhase = (phase) => {
    active = { ...active, phase };
    emit();
  };
  const maybeShow = () => {
    if (active && active.wantShow && active.ready && active.phase === 'loading') setPhase('showing');
  };

  const store = {
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    phaseOf: (key) => (active && active.key === key ? active.phase : 'idle'),
    activeKey: () => (active && active.phase === 'showing' ? active.key : null),
    isMuted: () => muted,

    request(key, src, input = 'mouse') {
      if (!key || !src || failed.has(src)) return;
      if (active && active.key === key) return; // already on it (hover then click focuses too)
      if (!canPreview()) return;
      clearTimers();
      active = { key, src, phase: 'arming', wantShow: false, ready: false };
      emit();
      timers.push(setTimeout(() => setPhase('loading'), LOAD_DELAY));
      timers.push(setTimeout(() => {
        active = { ...active, wantShow: true };
        maybeShow();
      }, SHOW_DELAY[input] ?? SHOW_DELAY.mouse));
    },

    cancel(key) {
      if (!active || (key && active.key !== key)) return;
      clearTimers();
      active = null;
      emit();
    },

    /** the card's video can play */
    ready(key) {
      if (!active || active.key !== key) return;
      active = { ...active, ready: true };
      maybeShow();
    },

    /** the clip couldn't load / play: back to the artwork, not tried again */
    fail(key, src) {
      if (src) failed.add(src);
      store.cancel(key);
    },

    setMuted(value) {
      muted = !!value;
      try {
        storage?.setItem(MUTED_KEY, muted ? '1' : '0');
      } catch {
        /* private mode: only for this visit */
      }
      emit();
    },
  };
  return store;
}

export const previewStore = createPreviewStore();

if (typeof document !== 'undefined') {
  // another tab / the app in the background: no preview playing unseen
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') previewStore.cancel();
  });
}

/** 'idle' | 'arming' | 'loading' | 'showing' for this card */
export const usePreviewPhase = (key) =>
  useSyncExternalStore(previewStore.subscribe, () => previewStore.phaseOf(key), () => 'idle');

export const usePreviewMuted = () =>
  useSyncExternalStore(previewStore.subscribe, previewStore.isMuted, () => true);

/** the key of the preview on screen, or null (the home banner pauses while one plays) */
export const useActivePreview = () =>
  useSyncExternalStore(previewStore.subscribe, previewStore.activeKey, () => null);

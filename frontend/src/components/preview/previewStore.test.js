import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { createPreviewStore, LOAD_DELAY, SHOW_DELAY } from './previewStore';

const memoryStorage = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)) };
};

describe('previewStore', () => {
  let store;
  beforeEach(() => {
    vi.useFakeTimers();
    store = createPreviewStore({ canPreview: () => true, storage: memoryStorage() });
  });
  afterEach(() => vi.useRealTimers());

  it('waits, loads, then shows once the video can play (mouse)', () => {
    store.request('a', 'a.mp4', 'mouse');
    expect(store.phaseOf('a')).toBe('arming'); // passing over a card downloads nothing
    vi.advanceTimersByTime(LOAD_DELAY);
    expect(store.phaseOf('a')).toBe('loading');
    store.ready('a');
    expect(store.phaseOf('a')).toBe('loading'); // ready early: still waits for the delay
    vi.advanceTimersByTime(SHOW_DELAY.mouse - LOAD_DELAY);
    expect(store.phaseOf('a')).toBe('showing');
    expect(store.activeKey()).toBe('a');
  });

  it('shows as soon as a slow video is ready after the delay', () => {
    store.request('a', 'a.mp4');
    vi.advanceTimersByTime(SHOW_DELAY.mouse + 1000);
    expect(store.phaseOf('a')).toBe('loading');
    store.ready('a');
    expect(store.phaseOf('a')).toBe('showing');
  });

  it('the remote waits longer than the mouse', () => {
    store.request('a', 'a.mp4', 'focus');
    vi.advanceTimersByTime(LOAD_DELAY);
    store.ready('a');
    vi.advanceTimersByTime(SHOW_DELAY.mouse);
    expect(store.phaseOf('a')).toBe('loading');
    vi.advanceTimersByTime(SHOW_DELAY.focus - SHOW_DELAY.mouse);
    expect(store.phaseOf('a')).toBe('showing');
  });

  it('one preview at a time; leaving a card stops it, leaving another changes nothing', () => {
    store.request('a', 'a.mp4');
    vi.advanceTimersByTime(LOAD_DELAY);
    store.request('b', 'b.mp4');
    expect(store.phaseOf('a')).toBe('idle');
    expect(store.phaseOf('b')).toBe('arming');
    store.cancel('a'); // a's late "leave" doesn't stop b
    expect(store.phaseOf('b')).toBe('arming');
    store.cancel('b');
    expect(store.phaseOf('b')).toBe('idle');
    vi.advanceTimersByTime(5000); // no timer left behind brings it back
    expect(store.phaseOf('b')).toBe('idle');
  });

  it('asking again for the card already previewed keeps it going', () => {
    store.request('a', 'a.mp4', 'mouse');
    vi.advanceTimersByTime(LOAD_DELAY);
    store.request('a', 'a.mp4', 'focus'); // the click after the hover focuses the card
    expect(store.phaseOf('a')).toBe('loading');
  });

  it('a clip that fails is not tried again', () => {
    store.request('a', 'a.mp4');
    vi.advanceTimersByTime(LOAD_DELAY);
    store.fail('a', 'a.mp4');
    expect(store.phaseOf('a')).toBe('idle');
    store.request('a', 'a.mp4');
    expect(store.phaseOf('a')).toBe('idle');
  });

  it('nothing without a clip, or when previews are off (reduced motion, data saver)', () => {
    store.request('a', '');
    expect(store.phaseOf('a')).toBe('idle');
    const off = createPreviewStore({ canPreview: () => false, storage: memoryStorage() });
    off.request('a', 'a.mp4');
    expect(off.phaseOf('a')).toBe('idle');
  });

  it('muted by default; the choice is remembered and shared by every card', () => {
    const storage = memoryStorage();
    const s1 = createPreviewStore({ canPreview: () => true, storage });
    expect(s1.isMuted()).toBe(true);
    const seen = vi.fn();
    s1.subscribe(seen);
    s1.setMuted(false);
    expect(seen).toHaveBeenCalled();
    expect(createPreviewStore({ storage }).isMuted()).toBe(false);
  });
});

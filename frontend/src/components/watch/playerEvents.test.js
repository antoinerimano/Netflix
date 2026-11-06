// The watch page's helpers: what each player's postMessage means, saved prefs, URLs.
import {
  LEGACY_SOURCE_KEYS,
  isDirectVideo,
  normalizeUrl,
  readPlayerEvent,
  readPositiveInt,
  storageKey,
} from './playerEvents';

describe('readPlayerEvent: Videasy', () => {
  const videasy = (data) => ({ type: 'PLAYER_EVENT', data });

  test('progress while playing', () => {
    expect(readPlayerEvent(videasy({ player_status: 'playing', player_progress: 120.5, player_duration: 5400 }))).toEqual({
      position: 120.5,
      duration: 5400,
      playing: true,
      ended: false,
      flush: false,
      season: undefined,
      episode: undefined,
    });
  });

  test('data sent as a JSON string, as a whole message string too', () => {
    const inner = JSON.stringify({ player_status: 'paused', player_progress: '30', player_duration: '60' });
    const ev = readPlayerEvent(JSON.stringify(videasy(inner)));
    expect(ev).toMatchObject({ position: 30, duration: 60, flush: true, playing: true });
  });

  test('a position above 0 proves playback even without a status', () => {
    expect(readPlayerEvent(videasy({ player_progress: 1 })).playing).toBe(true);
    expect(readPlayerEvent(videasy({ player_progress: 0 })).playing).toBe(false);
  });

  test('completed, seeked and the episode it is on', () => {
    expect(readPlayerEvent(videasy({ player_status: 'completed' })).ended).toBe(true);
    expect(readPlayerEvent(videasy({ player_status: 'seeked' })).flush).toBe(true);
    const ev = readPlayerEvent(videasy({ player_status: 'playing', player_info: { season: '2', episode: 5 } }));
    expect(ev).toMatchObject({ season: 2, episode: 5 });
  });

  test('missing or broken data', () => {
    expect(readPlayerEvent(videasy(null))).toBeNull();
    expect(readPlayerEvent(videasy('{not json'))).toBeNull();
  });

  test('empty numbers are NaN, not 0 (an empty position is not the start)', () => {
    const ev = readPlayerEvent(videasy({ player_status: 'playing', player_progress: '', player_duration: null }));
    expect(ev.position).toBeNaN();
    expect(ev.duration).toBeNaN();
  });
});

describe('readPlayerEvent: CineSrc', () => {
  test('timeupdate / seeked', () => {
    expect(readPlayerEvent({ type: 'cinesrc:timeupdate', currentTime: 42, duration: 100 })).toEqual({
      position: 42,
      duration: 100,
      playing: true,
      flush: false,
    });
    expect(readPlayerEvent({ type: 'cinesrc:seeked', currentTime: 0, duration: 100 })).toMatchObject({
      playing: false,
      flush: true,
    });
  });

  test('play, pause, ended, next episode', () => {
    expect(readPlayerEvent({ type: 'cinesrc:play' })).toEqual({ playing: true });
    expect(readPlayerEvent({ type: 'cinesrc:pause' })).toEqual({ flush: true });
    expect(readPlayerEvent({ type: 'cinesrc:ended' })).toEqual({ ended: true });
    expect(readPlayerEvent({ type: 'cinesrc:nextepisode', season: '1', episode: '4' })).toEqual({ season: 1, episode: 4 });
  });

  test('unknown CineSrc events are ignored', () => {
    expect(readPlayerEvent({ type: 'cinesrc:volumechange' })).toBeNull();
  });
});

describe('readPlayerEvent: VidCore and others', () => {
  test('VidCore sends plain strings', () => {
    expect(readPlayerEvent('vidcore:play')).toEqual({ playing: true });
    expect(readPlayerEvent('vidcore:ended')).toEqual({ ended: true });
    expect(readPlayerEvent('vidcore:pause')).toBeNull();
  });

  test('anything else (ads, extensions, other frames) is ignored', () => {
    for (const raw of [null, undefined, 42, '', 'hello', '{"a":1}', { type: 7 }, { foo: 'bar' }, { type: 'webpackOk' }]) {
      expect(readPlayerEvent(raw)).toBeNull();
    }
  });
});

describe('URLs', () => {
  test('normalizeUrl adds https to a bare domain only', () => {
    expect(normalizeUrl('vidfast.pro/movie/1')).toBe('https://vidfast.pro/movie/1');
    expect(normalizeUrl('  http://a.b/c ')).toBe('http://a.b/c');
    expect(normalizeUrl('https://a.b')).toBe('https://a.b');
    expect(normalizeUrl('/relative/path')).toBe('/relative/path');
    expect(normalizeUrl(null)).toBe('');
  });

  test('isDirectVideo: mp4 / m3u8 files, not embed pages', () => {
    expect(isDirectVideo('https://cdn.x/a.mp4')).toBe(true);
    expect(isDirectVideo('https://cdn.x/live.m3u8?token=1')).toBe(true);
    expect(isDirectVideo('https://cdn.x/a.MP4#t=10')).toBe(true);
    expect(isDirectVideo('https://player.x/embed/mp4player')).toBe(false);
    expect(isDirectVideo('')).toBe(false);
  });
});

describe('saved preferences and the address', () => {
  test('storageKey is per profile and title', () => {
    expect(storageKey('3', 10)).toBe('watchprefs_3_10');
    expect(storageKey(null, 10)).toBe('watchprefs_anon_10');
  });

  test('old saved sources map to provider keys', () => {
    expect(LEGACY_SOURCE_KEYS.video_url).toBe('vidking');
    expect(LEGACY_SOURCE_KEYS.movie_link3).toBe(LEGACY_SOURCE_KEYS.episode_link3);
  });

  test('readPositiveInt falls back on anything but a positive number', () => {
    expect(readPositiveInt('?season=3&episode=7', 'season', 1)).toBe(3);
    expect(readPositiveInt('?season=0', 'season', 1)).toBe(1);
    expect(readPositiveInt('?season=-2', 'season', 1)).toBe(1);
    expect(readPositiveInt('?season=abc', 'season', 1)).toBe(1);
    expect(readPositiveInt('', 't', 0)).toBe(0);
  });
});

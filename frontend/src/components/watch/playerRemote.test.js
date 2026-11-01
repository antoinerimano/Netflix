// Remote control of embedded players with an API (CineSrc): keys become postMessage commands.
import { renderHook } from '@testing-library/react';
import { remoteApiFor, usePlayerRemote } from './playerRemote';

const CINESRC = 'https://cinesrc.st/embed/movie/550';

function setup(url = CINESRC) {
  const wrap = document.createElement('div');
  wrap.tabIndex = 0;
  const iframe = document.createElement('iframe');
  wrap.appendChild(iframe);
  document.body.appendChild(wrap);
  const post = jest.spyOn(iframe.contentWindow, 'postMessage').mockImplementation(() => {});
  const iframeRef = { current: iframe };
  const wrapRef = { current: wrap };
  const hook = renderHook(() => usePlayerRemote({ url, iframeRef, wrapRef }));
  wrap.focus();
  return { wrap, iframe, post, hook };
}

function key(name) {
  const e = new KeyboardEvent('keydown', { key: name, bubbles: true, cancelable: true });
  window.dispatchEvent(e);
  return e;
}

function setFullscreen(el) {
  Object.defineProperty(document, 'fullscreenElement', { configurable: true, get: () => el });
}

afterEach(() => {
  setFullscreen(null);
  document.body.innerHTML = '';
});

test('only players with a documented API are driven by the remote', () => {
  expect(remoteApiFor(CINESRC)).not.toBeNull();
  expect(remoteApiFor('https://player.videasy.ws/movie/550')).toBeNull();
  expect(remoteApiFor('not a url')).toBeNull();
});

test('in full screen OK toggles play / pause and arrows seek / change the volume', () => {
  const { wrap, post } = setup();
  setFullscreen(wrap);
  const origin = 'https://cinesrc.st';

  expect(key('Enter').defaultPrevented).toBe(true);
  expect(post).toHaveBeenLastCalledWith({ type: 'cinesrc:command', command: 'play', args: [] }, origin);
  key('Enter');
  expect(post).toHaveBeenLastCalledWith({ type: 'cinesrc:command', command: 'pause', args: [] }, origin);

  key('ArrowRight');
  expect(post).toHaveBeenLastCalledWith({ type: 'cinesrc:command', command: 'seek', args: [10] }, origin);
  key('ArrowDown');
  expect(post).toHaveBeenLastCalledWith({ type: 'cinesrc:command', command: 'setVolume', args: [0.9] }, origin);
});

test('outside full screen the arrows still move around the page', () => {
  const { post } = setup();
  const e = key('ArrowRight');
  expect(e.defaultPrevented).toBe(false);
  expect(post).not.toHaveBeenCalled();
});

test('players without an API get no commands', () => {
  const { wrap, post } = setup('https://player.videasy.ws/movie/550');
  setFullscreen(wrap);
  key('Enter');
  key('ArrowRight');
  expect(post).not.toHaveBeenCalled();
});

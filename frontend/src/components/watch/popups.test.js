// Block pop-ups (ROADMAP 9.1): the sandbox attribute, the source order, the "allow" offer, what is learned.
import {
  LEARN_TTL_MS,
  SANDBOX,
  orderSources,
  readBlockPopups,
  readSandboxFailures,
  rememberSandboxFailure,
  sandboxFor,
  shouldOfferAllow,
  storeBlockPopups,
} from './popups';

const ORIGIN = 'https://site.example';
const src = (key, sandboxOk = 'unknown', extra = {}) => ({ key, label: key, url: `https://${key}.test/movie/1`, sandboxOk, ...extra });

describe('sandboxFor', () => {
  test('no allow-popups, no allow-top-navigation when blocking', () => {
    const attr = sandboxFor('https://vidfast.pro/movie/1', true, ORIGIN);
    expect(attr).toBe(SANDBOX);
    expect(attr.split(' ').sort()).toEqual(['allow-forms', 'allow-presentation', 'allow-same-origin', 'allow-scripts']);
    expect(attr).not.toMatch(/allow-popups|allow-top-navigation/);
  });

  test('no sandbox when the switch is off, or no player', () => {
    expect(sandboxFor('https://vidfast.pro/movie/1', false, ORIGIN)).toBeUndefined();
    expect(sandboxFor('', true, ORIGIN)).toBeUndefined();
  });

  test('a frame on our own origin never gets allow-scripts + allow-same-origin', () => {
    const attr = sandboxFor('/some/page', true, ORIGIN);
    expect(attr).toContain('allow-scripts');
    expect(attr).not.toContain('allow-same-origin');
    expect(sandboxFor(`${ORIGIN}/x`, true, ORIGIN)).not.toContain('allow-same-origin');
  });
});

describe('orderSources', () => {
  const list = [src('a', 'no'), src('b', 'yes'), src('c'), src('d', 'no'), src('e', 'yes')];

  test('blocking: the ones that do not play sandboxed go last, server order kept in each group', () => {
    const out = orderSources(list, { block: true });
    expect(out.map((p) => p.key)).toEqual(['b', 'c', 'e', 'a', 'd']);
    expect(out.filter((p) => p.popupRisk).map((p) => p.key)).toEqual(['a', 'd']);
    expect(out.filter((p) => p.noPopups).map((p) => p.key)).toEqual(['b', 'e']); // unknown gets no chip
  });

  test('a source that failed sandboxed here goes last too, without the chip', () => {
    const out = orderSources(list, { block: true, learned: new Set(['b']) });
    expect(out.map((p) => p.key)).toEqual(['c', 'e', 'a', 'b', 'd']);
    expect(out.find((p) => p.key === 'b')).toMatchObject({ popupRisk: true, noPopups: false });
  });

  test('switch off: the order the server gave, no marks', () => {
    const out = orderSources(list, { block: false, learned: new Set(['b']) });
    expect(out.map((p) => p.key)).toEqual(['a', 'b', 'c', 'd', 'e']);
    expect(out.some((p) => p.popupRisk || p.noPopups)).toBe(false);
  });

  test('keeps the other fields', () => {
    expect(orderSources([src('a', 'yes', { down: true, sendsEvents: true })], { block: true })[0]).toMatchObject({
      key: 'a', url: 'https://a.test/movie/1', down: true, sendsEvents: true,
    });
  });
});

describe('shouldOfferAllow', () => {
  const sources = orderSources([src('a', 'yes'), src('b'), src('c', 'no')], { block: true });
  const get = (k) => sources.find((p) => p.key === k);

  test('on a source that may open pop-ups', () => {
    expect(shouldOfferAllow({ block: true, current: get('c'), sources, failed: new Set() })).toBe(true);
  });

  test('when the current one failed and none other plays sandboxed', () => {
    expect(shouldOfferAllow({ block: true, current: get('b'), sources, failed: new Set(['b']) })).toBe(false); // a is left
    expect(shouldOfferAllow({ block: true, current: get('b'), sources, failed: new Set(['a', 'b']) })).toBe(true);
    const downA = sources.map((p) => (p.key === 'a' ? { ...p, down: true } : p));
    expect(shouldOfferAllow({ block: true, current: get('b'), sources: downA, failed: new Set(['b']) })).toBe(true);
  });

  test('once per source, never with the switch off, never on a source that plays', () => {
    expect(shouldOfferAllow({ block: true, current: get('c'), sources, failed: new Set(), allowed: new Set(['c']) })).toBe(false);
    expect(shouldOfferAllow({ block: false, current: get('c'), sources, failed: new Set(['a', 'b', 'c']) })).toBe(false);
    expect(shouldOfferAllow({ block: true, current: get('a'), sources, failed: new Set() })).toBe(false);
    expect(shouldOfferAllow({ block: true, current: undefined, sources, failed: new Set() })).toBe(false);
  });
});

describe('learned failures and the setting', () => {
  beforeEach(() => localStorage.clear());

  test('remembered per profile, forgotten after a while', () => {
    const now = 1_000_000_000_000;
    rememberSandboxFailure('7', 'vidfast', now);
    rememberSandboxFailure('7', 'xpass', now - LEARN_TTL_MS - 1);
    expect([...readSandboxFailures('7', now)]).toEqual(['vidfast']);
    expect(readSandboxFailures('8', now).size).toBe(0);
    expect(readSandboxFailures('7', now + LEARN_TTL_MS).size).toBe(0);
  });

  test('broken storage is no failure', () => {
    localStorage.setItem('sandboxFailed_7', '{oops');
    expect(readSandboxFailures('7').size).toBe(0);
  });

  test('on by default, the profile copy follows the switch', () => {
    expect(readBlockPopups()).toBe(true); // no profile
    localStorage.setItem('activeProfile', JSON.stringify({ id: 7, name: 'A' }));
    expect(readBlockPopups()).toBe(true); // saved before 9.1
    storeBlockPopups(false);
    expect(JSON.parse(localStorage.getItem('activeProfile'))).toEqual({ id: 7, name: 'A', block_popups: false });
    expect(readBlockPopups()).toBe(false);
  });
});

import { describe, expect, it } from 'vitest';
import { watchRegion } from './watchRegion';

describe('watchRegion', () => {
  it('takes the first browser language with a region', () => {
    expect(watchRegion(['fr', 'fr-CA', 'en-US'])).toBe('CA');
    expect(watchRegion(['en-us'])).toBe('US');
    expect(watchRegion(['zh-Hant-TW'])).toBe('TW');
    expect(watchRegion(['pt_BR'])).toBe('BR');
  });

  it('leaves it to the server when no language says one', () => {
    expect(watchRegion(['fr', 'en'])).toBe('');
    expect(watchRegion(['es-419'])).toBe(''); // Latin America: not a country
    expect(watchRegion([])).toBe('');
    expect(watchRegion(null)).toBe('');
  });
});

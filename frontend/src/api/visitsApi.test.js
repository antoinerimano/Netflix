import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('./http', () => ({ default: { post: vi.fn(() => Promise.resolve({})) } }));
import http from './http';
import { getVisitorId, sendVisit, trackingAllowed } from './visitsApi';

describe('visitsApi', () => {
  beforeEach(() => {
    localStorage.clear();
    http.post.mockClear();
  });

  it('one random id per browser, kept between visits', () => {
    const id = getVisitorId();
    expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(getVisitorId()).toBe(id);
  });

  it('reports the page with the visitor and the visit', async () => {
    await sendVisit('view', '/movies/42', 'https://www.google.com/');
    expect(http.post).toHaveBeenCalledWith('/events/visit/', expect.objectContaining({
      kind: 'view', path: '/movies/42', referrer: 'https://www.google.com/', visitor_id: getVisitorId(),
    }));
    expect(http.post.mock.calls[0][1].session_id).toBeTruthy();
  });

  it('nothing when the browser asks not to be tracked', () => {
    expect(trackingAllowed({ globalPrivacyControl: true })).toBe(false);
    expect(trackingAllowed({ doNotTrack: '1' })).toBe(false);
    expect(trackingAllowed({ doNotTrack: '0' })).toBe(true);
    expect(trackingAllowed({})).toBe(true);
  });
});

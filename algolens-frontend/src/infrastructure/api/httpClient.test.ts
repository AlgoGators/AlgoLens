// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  HttpTransportError,
  SessionExpiredError,
  fetchWithAuth,
  postWithAuth,
} from './httpClient';

describe('authenticated HTTP failures', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('reports an expired session without forcing a navigation or retry', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('', { status: 401, statusText: 'Unauthorized' }),
    );
    const before = window.location.href;

    await expect(fetchWithAuth('/portfolio/strategies')).rejects.toBeInstanceOf(SessionExpiredError);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(window.location.href).toBe(before);
  });

  it('applies the same expired-session contract to writes', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('', { status: 422, statusText: 'Unprocessable Entity' }),
    );

    await expect(postWithAuth('/portfolio/positions', {})).rejects.toBeInstanceOf(SessionExpiredError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('wraps a transport rejection once without a hidden retry', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));

    await expect(fetchWithAuth('/portfolio/strategies')).rejects.toBeInstanceOf(HttpTransportError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

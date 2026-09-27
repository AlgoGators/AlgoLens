// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  HttpTransportError,
  SessionExpiredError,
  fetchWithAuth,
  postWithAuth,
  getWithAuth,
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

describe('private inspection GET', () => {
  it('sends one credentialed no-store JSON request and forwards cancellation', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}'));
    const signal = new AbortController().signal;
    await getWithAuth('/configuration', signal);
    expect(fetchMock).toHaveBeenCalledExactlyOnceWith('/configuration', {
      method: 'GET', credentials: 'include', cache: 'no-store',
      headers: { Accept: 'application/json', 'Cache-Control': 'no-store' }, signal,
    });
  });

  it.each([401, 422])('preserves session expiry on %i without a retry or body log', async status => {
    const sentinel = 'private-config-secret';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(sentinel, { status }));
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    await expect(getWithAuth('/configuration')).rejects.toBeInstanceOf(SessionExpiredError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(log.mock.calls.join(' ')).not.toContain(sentinel);
  });
});

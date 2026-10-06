// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';

import { verifySessionRequest } from './authApi';

describe('auth API identity boundary', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('decodes server capabilities and refuses legacy role-only users', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
      user: { id: 7, email: 'member@example.com', role: 'general_member', capabilities: ['view_internal'] },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    await expect(verifySessionRequest()).resolves.toMatchObject({
      status: 200,
      user: { id: '7', capabilities: ['view_internal'] },
    });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
      user: { id: 7, email: 'member@example.com', role: 'general_member' },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    await expect(verifySessionRequest()).rejects.toThrow('invalid_user');
  });
});

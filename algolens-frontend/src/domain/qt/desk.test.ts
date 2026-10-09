import { describe, expect, it } from 'vitest';
import {
  POLL_BUDGET_MS,
  POLL_INTERVAL_MS,
  POLL_SLOW_INTERVAL_MS,
  approvalTokenFrom,
  deskLockedReason,
  describeCommand,
  editBlockedReason,
  isFatalPollError,
  isFinal,
  overrideBlockedReason,
  parseContracts,
  pollDelayMs,
  pollPhase,
  proposalKey,
  publishBlockedReason,
  shouldKeepPolling,
  snapshotBySymbol,
  validateEdit,
  type BookPosition,
  type DeskCommand,
  type DeskState,
} from './desk';

const proposal: BookPosition[] = [
  { symbol: 'ZC.v.0', quantity: 3, average_price: 400, moved_by: null },
  { symbol: 'ZS.v.0', quantity: -2, average_price: 1000, moved_by: null },
];

describe('parseContracts', () => {
  it('accepts signed whole contracts', () => {
    expect(parseContracts('3')).toEqual({ value: 3 });
    expect(parseContracts(' -2 ')).toEqual({ value: -2 });
    expect(parseContracts('0')).toEqual({ value: 0 });
    expect(parseContracts('+4')).toEqual({ value: 4 });
  });

  it('refuses fractions, text and absurd sizes', () => {
    for (const raw of ['1.5', 'abc', '', '1e3', '--1', '2,000', '²', '１', '٣']) {
      expect('error' in parseContracts(raw)).toBe(true);
    }
    expect('error' in parseContracts('100001')).toBe(true);
  });
});

describe('validateEdit', () => {
  it('sends only the symbols whose quantity changed, 0 = flatten', () => {
    const v = validateEdit(proposal, { 'ZC.v.0': '0', 'ZS.v.0': '-2' }, [], 'flatten corn');
    expect(v.ok).toBe(true);
    expect(v.changes).toEqual([{ symbol: 'ZC.v.0', quantity: 0, expected: 3 }]);
  });

  it('requires a reason', () => {
    const v = validateEdit(proposal, { 'ZC.v.0': '1' }, [], '   ');
    expect(v.ok).toBe(false);
    expect(v.formErrors).toContain('A reason is required');
  });

  it('refuses a save with nothing changed', () => {
    const v = validateEdit(proposal, { 'ZC.v.0': '3' }, [], 'r');
    expect(v.ok).toBe(false);
    expect(v.formErrors).toContain('No quantity changed');
  });

  it('flags a fractional quantity on its own field', () => {
    const v = validateEdit(proposal, { 'ZC.v.0': '1.5' }, [], 'r');
    expect(v.ok).toBe(false);
    expect(v.fieldErrors['ZC.v.0']).toMatch(/Whole contracts/);
    expect(v.formErrors).not.toContain('No quantity changed');
  });

  it('adds a new symbol with a non-zero quantity only', () => {
    expect(validateEdit(proposal, { '6E.v.0': '2' }, ['6E.v.0'], 'r').changes).toEqual([
      { symbol: '6E.v.0', quantity: 2, expected: null },
    ]);
    expect(validateEdit(proposal, { '6E.v.0': '0' }, ['6E.v.0'], 'r').fieldErrors['6E.v.0']).toBeTruthy();
    expect(validateEdit(proposal, {}, ['6E.v.0'], 'r').fieldErrors['6E.v.0']).toBeTruthy();
  });

  it('ignores an added symbol already in the proposal', () => {
    const v = validateEdit(proposal, { 'ZC.v.0': '5' }, ['ZC.v.0'], 'r');
    expect(v.changes).toEqual([{ symbol: 'ZC.v.0', quantity: 5, expected: 3 }]);
  });
});

const command = (over: Partial<DeskCommand>): DeskCommand => ({
  id: 1,
  portfolio_id: 'QT',
  date: '2026-10-08',
  kind: 'save',
  status: 'pending',
  requested_by: 'd@x.com',
  reason: 'r',
  payload: {},
  parent_id: null,
  approver_role: null,
  token_expires_at: null,
  result: null,
  message: null,
  created_at: '',
  started_at: null,
  finished_at: null,
  ...over,
});

describe('polling', () => {
  it('polls for up to the engine job timeout (30 min)', () => {
    expect(POLL_BUDGET_MS).toBe(30 * 60_000);
    expect(shouldKeepPolling('pending', 0, 300_000)).toBe(true);
    expect(shouldKeepPolling('running', 0, 30 * 60_000 - 1)).toBe(true);
    expect(shouldKeepPolling('running', 0, 30 * 60_000)).toBe(false);
  });

  it('polls every 2 s for a minute, then every 15 s', () => {
    expect(pollDelayMs(0)).toBe(POLL_INTERVAL_MS);
    expect(pollDelayMs(59_999)).toBe(2_000);
    expect(pollDelayMs(60_000)).toBe(POLL_SLOW_INTERVAL_MS);
    expect(POLL_SLOW_INTERVAL_MS).toBe(15_000);
  });

  it('calls a command past 5 minutes slow, and gives up at 30', () => {
    expect(pollPhase(299_999)).toBe('normal');
    expect(pollPhase(300_000)).toBe('slow');
    expect(pollPhase(30 * 60_000)).toBe('gaveUp');
  });

  it('stops on a 4xx answer but not on a network error or 5xx', () => {
    for (const status of [400, 401, 403, 404, 409]) expect(isFatalPollError(status)).toBe(true);
    for (const status of [undefined, null, 0, 408, 429, 500, 502, 503]) expect(isFatalPollError(status)).toBe(false);
  });

  it('stops on any final status', () => {
    for (const s of ['done', 'refused', 'failed'] as const) {
      expect(isFinal(s)).toBe(true);
      expect(shouldKeepPolling(s, 0, 1)).toBe(false);
    }
    expect(isFinal('pending')).toBe(false);
  });
});

describe('describeCommand', () => {
  it('shows refusals and failures plainly with the engine message', () => {
    expect(describeCommand(command({ status: 'refused', message: 'no proposal seeded' }))).toBe(
      'Save REFUSED by the engine: no proposal seeded',
    );
    expect(describeCommand(command({ status: 'failed' }))).toBe('Save FAILED (no reason given)');
    expect(describeCommand(command({ kind: 'publish', status: 'done' }))).toBe('Publish done');
  });

  it('says a slow command is still running on the engine, not failed', () => {
    expect(describeCommand(command({}), true)).toMatch(/still waiting/);
    expect(describeCommand(command({ status: 'running' }), 'slow')).toMatch(/still running on the engine after 5/);
    expect(describeCommand(command({ status: 'running' }), 'gaveUp')).toMatch(/after 30 minutes. Nothing failed/);
    expect(describeCommand(command({ status: 'pending' }))).toBe('Save sent; waiting for the engine');
    // A final row is described as final whatever the phase.
    expect(describeCommand(command({ status: 'done' }), 'gaveUp')).toBe('Save done');
  });
});

describe('publish', () => {
  const state = (over: Partial<DeskState>): DeskState => ({
    portfolioId: 'QT',
    deskEditable: true,
    date: '2026-10-08',
    seeded: true,
    books: { system: [], qt_proposal: [], qt: [] },
    comparison: [],
    latestSave: null,
    overrideRequests: [],
    publish: null,
    published: null,
    ...over,
  });

  it('is open every day, edited or not', () => {
    expect(publishBlockedReason(state({}))).toBeNull();
    expect(publishBlockedReason(state({ publish: command({ kind: 'publish', status: 'failed' }) }))).toBeNull();
  });

  it('is closed while one is queued or once done', () => {
    expect(publishBlockedReason(state({ publish: command({ kind: 'publish', status: 'pending' }) }))).toBe(
      'Publish in progress',
    );
    expect(publishBlockedReason(state({ publish: command({ kind: 'publish', status: 'done' }) }))).toBe('Published');
    expect(publishBlockedReason(state({ date: null }))).toBe('No book for today yet');
  });

  it('reads the published state from live_run_metadata, not only from command rows', () => {
    // The engine's own non-trading-day publish: no publish row at all.
    const published = state({ published: { published_by: 'system:non-trading-day', published_at: '2026-10-10T01:00:00Z' } });
    expect(deskLockedReason(published)).toBe('Published');
    expect(publishBlockedReason(published)).toBe('Published');
    expect(editBlockedReason(published)).toBe('Published');
    expect(overrideBlockedReason(published)).toBe('Published');
    expect(deskLockedReason(state({ locked: 'published' }))).toBe('Published');
  });

  it('closes edit and override while a publish is open', () => {
    const publishing = state({ publish: command({ kind: 'publish', status: 'running' }) });
    expect(editBlockedReason(publishing)).toBe('Publish in progress');
    expect(overrideBlockedReason(publishing)).toBe('Publish in progress');
    expect(editBlockedReason(state({ locked: 'publishing' }))).toBe('Publish in progress');
  });

  it('allows one open override request a day', () => {
    expect(overrideBlockedReason(state({}))).toBeNull();
    expect(overrideBlockedReason(state({ openOverrideRequestId: 7 }))).toBe('Override request #7 is still open');
    expect(overrideBlockedReason(state({ seeded: false }))).toMatch(/not seeded/);
    expect(editBlockedReason(state({}))).toBeNull();
  });
});

describe('the edit form follows the proposal', () => {
  it('keys the form on the proposal so a changed proposal resets the draft', () => {
    const before = proposalKey(proposal);
    expect(proposalKey([...proposal])).toBe(before);
    expect(proposalKey([{ ...proposal[0], quantity: 4 }, proposal[1]])).not.toBe(before);
    expect(proposalKey([proposal[0]])).not.toBe(before);
  });
});

describe('snapshotBySymbol', () => {
  it('nets the snapshot over sleeves', () => {
    const net = snapshotBySymbol([
      { strategy_name: 'A', symbol: 'ZC.v.0', quantity: 2 },
      { strategy_name: 'B', symbol: 'ZC.v.0', quantity: 1 },
      { strategy_name: 'A', symbol: 'ZS.v.0', quantity: 0 },
    ]);
    expect([...net.entries()]).toEqual([
      ['ZC.v.0', 3],
      ['ZS.v.0', 0],
    ]);
    expect(snapshotBySymbol(null).size).toBe(0);
  });
});

describe('approvalTokenFrom', () => {
  it('reads the token from the link', () => {
    expect(approvalTokenFrom('?token=abc%2Bdef')).toBe('abc+def');
    expect(approvalTokenFrom('?x=1')).toBeNull();
    expect(approvalTokenFrom('?token=')).toBeNull();
  });
});

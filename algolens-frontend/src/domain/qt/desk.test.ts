import { describe, expect, it } from 'vitest';
import {
  POLL_INTERVAL_MS,
  POLL_TIMEOUT_MS,
  approvalTokenFrom,
  describeCommand,
  isFinal,
  parseContracts,
  publishBlockedReason,
  shouldKeepPolling,
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
    for (const raw of ['1.5', 'abc', '', '1e3', '--1', '2,000']) {
      expect('error' in parseContracts(raw)).toBe(true);
    }
    expect('error' in parseContracts('100001')).toBe(true);
  });
});

describe('validateEdit', () => {
  it('sends only the symbols whose quantity changed, 0 = flatten', () => {
    const v = validateEdit(proposal, { 'ZC.v.0': '0', 'ZS.v.0': '-2' }, [], 'flatten corn');
    expect(v.ok).toBe(true);
    expect(v.changes).toEqual([{ symbol: 'ZC.v.0', quantity: 0 }]);
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
      { symbol: '6E.v.0', quantity: 2 },
    ]);
    expect(validateEdit(proposal, { '6E.v.0': '0' }, ['6E.v.0'], 'r').fieldErrors['6E.v.0']).toBeTruthy();
    expect(validateEdit(proposal, {}, ['6E.v.0'], 'r').fieldErrors['6E.v.0']).toBeTruthy();
  });

  it('ignores an added symbol already in the proposal', () => {
    const v = validateEdit(proposal, { 'ZC.v.0': '5' }, ['ZC.v.0'], 'r');
    expect(v.changes).toEqual([{ symbol: 'ZC.v.0', quantity: 5 }]);
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
  it('polls every 2 s for up to 5 minutes', () => {
    expect(POLL_INTERVAL_MS).toBe(2000);
    expect(POLL_TIMEOUT_MS).toBe(300000);
    expect(shouldKeepPolling('pending', 0, 299_999)).toBe(true);
    expect(shouldKeepPolling('running', 0, 300_000)).toBe(false);
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

  it('says a timed-out command stays queued', () => {
    expect(describeCommand(command({}), true)).toMatch(/still waiting/);
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
});

describe('approvalTokenFrom', () => {
  it('reads the token from the link', () => {
    expect(approvalTokenFrom('?token=abc%2Bdef')).toBe('abc+def');
    expect(approvalTokenFrom('?x=1')).toBeNull();
    expect(approvalTokenFrom('?token=')).toBeNull();
  });
});

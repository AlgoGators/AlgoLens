import { describe, expect, it } from 'vitest';
import {
  CUTOFF_RULE,
  LOCKED_APPROVED,
  LOCKED_APPROVING,
  LOCKED_ENGINE,
  LOCKED_FALLBACK,
  POLL_BUDGET_MS,
  POLL_INTERVAL_MS,
  POLL_SLOW_INTERVAL_MS,
  approvalTokenFrom,
  approveBlockedReason,
  deskDayStatus,
  deskLockedReason,
  describeCommand,
  editBlockedReason,
  formatCountdown,
  isFatalPollError,
  isFinal,
  newYorkTime,
  overrideBlockedReason,
  parseContracts,
  pollDelayMs,
  pollPhase,
  proposalKey,
  publishBlockedReason,
  publishSourceOf,
  rescindBlockedReason,
  rescindConfirmText,
  rescindOpen,
  serverClockOffsetMs,
  shouldKeepPolling,
  snapshotBySymbol,
  validateEdit,
  type BookPosition,
  type DeskCommand,
  type DeskDeadlines,
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
    expect(describeCommand(command({ kind: 'publish', status: 'done' }))).toBe('Approval done');
  });

  it('describes a rescind', () => {
    expect(describeCommand(command({ kind: 'rescind' }))).toBe('Rescind sent; waiting for the engine');
    expect(
      describeCommand(
        command({ kind: 'rescind', status: 'done', message: 'approval of 2026-10-08 rescinded' }),
      ),
    ).toBe('Rescind done: approval of 2026-10-08 rescinded');
    expect(describeCommand(command({ kind: 'rescind', status: 'refused', message: 'already sent' }))).toBe(
      'Rescind REFUSED by the engine: already sent',
    );
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

const deskState = (over: Partial<DeskState>): DeskState => ({
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

describe('approve (the publish command)', () => {
  const state = deskState;

  it('is open every day, edited or not', () => {
    expect(approveBlockedReason(state({}))).toBeNull();
    expect(approveBlockedReason(state({ publish: command({ kind: 'publish', status: 'failed' }) }))).toBeNull();
    expect(publishBlockedReason).toBe(approveBlockedReason);
  });

  it('is closed while one is queued or once done', () => {
    expect(approveBlockedReason(state({ publish: command({ kind: 'publish', status: 'pending' }) }))).toBe(
      LOCKED_APPROVING,
    );
    expect(
      approveBlockedReason(
        state({
          publish: command({ kind: 'publish', status: 'done' }),
          published: { published_by: 'd@x.com', published_at: '2026-10-13T10:24:24Z', publish_source: 'desk' },
        }),
      ),
    ).toBe(LOCKED_APPROVED);
    // A rescinded approval: the row stays done, live_run_metadata no longer says published.
    expect(approveBlockedReason(state({ publish: command({ kind: 'publish', status: 'done' }) }))).toBeNull();
    expect(approveBlockedReason(state({ date: null }))).toBe('No book for today yet');
  });

  it('reads the published state from live_run_metadata, not only from command rows', () => {
    // An engine publish: no publish row at all.
    const published = state({ published: { published_by: 'system:non-trading-day', published_at: '2026-10-10T01:00:00Z' } });
    expect(deskLockedReason(published)).toBe(LOCKED_ENGINE);
    expect(approveBlockedReason(published)).toBe(LOCKED_ENGINE);
    expect(editBlockedReason(published)).toBe(LOCKED_ENGINE);
    expect(overrideBlockedReason(published)).toBe(LOCKED_ENGINE);
    expect(deskLockedReason(state({ locked: 'published' }))).toBe(LOCKED_APPROVED);
    const fallback = state({
      published: { published_by: 'system:fallback-10am', published_at: '2026-10-08T14:00:30Z', publish_source: 'fallback' },
    });
    expect(approveBlockedReason(fallback)).toBe(LOCKED_FALLBACK);
  });

  it('closes edit and override while an approval is open', () => {
    const publishing = state({ publish: command({ kind: 'publish', status: 'running' }) });
    expect(editBlockedReason(publishing)).toBe(LOCKED_APPROVING);
    expect(overrideBlockedReason(publishing)).toBe(LOCKED_APPROVING);
    expect(editBlockedReason(state({ locked: 'publishing' }))).toBe(LOCKED_APPROVING);
  });

  it('allows one open override request a day', () => {
    expect(overrideBlockedReason(state({}))).toBeNull();
    expect(overrideBlockedReason(state({ openOverrideRequestId: 7 }))).toBe('Override request #7 is still open');
    expect(overrideBlockedReason(state({ seeded: false }))).toMatch(/not seeded/);
    expect(editBlockedReason(state({}))).toBeNull();
  });
});

describe('publishSourceOf', () => {
  it('prefers the 026 column and reads published_by without it', () => {
    expect(publishSourceOf(null)).toBeNull();
    expect(publishSourceOf({ published_by: 'x', published_at: 't', publish_source: 'fallback' })).toBe('fallback');
    expect(publishSourceOf({ published_by: 'system:fallback-catchup', published_at: 't' })).toBe('fallback');
    expect(publishSourceOf({ published_by: 'system:model-only', published_at: 't', publish_source: null })).toBe(
      'model-only',
    );
    expect(publishSourceOf({ published_by: 'system:non-trading-day', published_at: 't' })).toBe('system');
    expect(publishSourceOf({ published_by: 'desk@x.com', published_at: 't' })).toBe('desk');
  });
});

// The server's clock, as the API sends it (America/New_York deadlines).
const EDT = (day: string, hhmm: string) => `${day}T${hhmm}:00-04:00`;
const EST = (day: string, hhmm: string) => `${day}T${hhmm}:00-05:00`;
const deadlinesFor = (day: string, today = day, zone = EDT): DeskDeadlines => ({
  timezone: 'America/New_York',
  today,
  bookDate: day,
  approveBy: zone(day, '09:30'),
  fallbackAt: zone(day, '10:00'),
  todayApproveBy: zone(today, '09:30'),
  todayFallbackAt: zone(today, '10:00'),
  approvalClosed: false,
});
const at = (iso: string) => Date.parse(iso);
const D = '2026-10-08';

describe('the daily cutoff state machine', () => {
  const open = deskState({ deadlines: deadlinesFor(D), sendTracked: true });

  it('awaits the model run with no book, an unseeded day or a past day', () => {
    const now = at(EDT(D, '07:00'));
    for (const state of [
      deskState({ date: null, deadlines: deadlinesFor(D) }),
      deskState({ seeded: false, deadlines: deadlinesFor(D) }),
      // The desk still shows yesterday's (sent) book.
      deskState({
        date: '2026-10-07',
        deadlines: deadlinesFor('2026-10-07', D),
        published: { published_by: 'd@x.com', published_at: EDT('2026-10-07', '09:00'), sent_at: EDT('2026-10-07', '09:30') },
      }),
    ]) {
      const status = deskDayStatus(state, now);
      expect(status.phase).toBe('awaiting-model-run');
      expect(status.title).toBe('Awaiting model run');
      expect(status.countdownTo).toBe(at(EDT(D, '09:30')));
    }
    expect(approveBlockedReason(deskState({ date: '2026-10-07', deadlines: deadlinesFor('2026-10-07', D) }), now)).toMatch(
      /closed at 10:00 New York/,
    );
  });

  it('is open until 09:30 with a countdown to 09:30', () => {
    const status = deskDayStatus(open, at(EDT(D, '09:00')));
    expect(status.phase).toBe('open');
    expect(status.title).toBe('Open — approve by 09:30');
    expect(status.detail).toBe(CUTOFF_RULE);
    expect(status.countdownTo).toBe(at(EDT(D, '09:30')));
    expect(status.countdownLabel).toBe('left to approve');
    expect(approveBlockedReason(open, at(EDT(D, '09:29')))).toBeNull();
  });

  it('stays open from 09:30 to 10:00, counting down to the fallback', () => {
    const status = deskDayStatus(open, at(EDT(D, '09:45')));
    expect(status.phase).toBe('open');
    expect(status.detail).toMatch(/e-mailed at once/);
    expect(status.countdownTo).toBe(at(EDT(D, '10:00')));
    expect(approveBlockedReason(open, at(EDT(D, '09:59')))).toBeNull();
  });

  it('closes Approve, edits and overrides at 10:00 and awaits the fallback', () => {
    const now = at(EDT(D, '10:00'));
    expect(approveBlockedReason(open, now)).toMatch(/closed at 10:00 New York; the model's book is sent instead/);
    expect(editBlockedReason(open, now)).toMatch(/closed at 10:00/);
    expect(overrideBlockedReason(open, now)).toMatch(/closed at 10:00/);
    const status = deskDayStatus(open, now);
    expect(status.phase).toBe('fallback');
    expect(status.title).toBe('Not approved — model book sent at 10:00 (fallback)');
    expect(status.countdownTo).toBeNull();
    // Without a clock, the server's own view decides.
    expect(approveBlockedReason({ ...open, deadlines: { ...deadlinesFor(D), approvalClosed: true } })).toMatch(/closed/);
  });

  it('shows an approval waiting for 09:30, then sent', () => {
    const approved = { ...open, published: { published_by: 'd@x.com', published_at: EDT(D, '09:10'), publish_source: 'desk' as const, sent_at: null } };
    const waiting = deskDayStatus(approved, at(EDT(D, '09:12')));
    expect(waiting.phase).toBe('approved');
    expect(waiting.title).toBe('Approved — sends at 09:30');
    expect(waiting.countdownTo).toBe(at(EDT(D, '09:30')));
    expect(approveBlockedReason(approved, at(EDT(D, '09:12')))).toBe(LOCKED_APPROVED);

    const sent = { ...approved, published: { ...approved.published, sent_at: '2026-10-08T13:30:04Z' } };
    const done = deskDayStatus(sent, at(EDT(D, '09:31')));
    expect(done.phase).toBe('sent');
    expect(done.title).toBe('Approved and sent at 09:30');
    expect(done.countdownTo).toBeNull();
  });

  it('shows an approval between 09:30 and 10:00 sent at once', () => {
    const state = {
      ...open,
      published: { published_by: 'd@x.com', published_at: EDT(D, '09:47'), publish_source: 'desk' as const, sent_at: EDT(D, '09:48') },
    };
    expect(deskDayStatus(state, at(EDT(D, '09:50'))).title).toBe('Approved and sent at 09:48');
  });

  it('shows the fallback once the engine published the model book', () => {
    const state = {
      ...open,
      published: { published_by: 'system:fallback-10am', published_at: EDT(D, '10:00'), publish_source: 'fallback' as const, sent_at: EDT(D, '10:01') },
    };
    const status = deskDayStatus(state, at(EDT(D, '10:05')));
    expect(status.phase).toBe('fallback');
    expect(status.title).toBe('Not approved — model book sent at 10:00 (fallback)');
    expect(status.detail).toMatch(/at 10:01/);
  });

  it('shows an approval in progress, even if the engine answers after 10:00', () => {
    const state = { ...open, publish: command({ kind: 'publish', status: 'running' }) };
    expect(deskDayStatus(state, at(EDT(D, '09:59'))).phase).toBe('approving');
    expect(deskDayStatus(state, at(EDT(D, '10:00'))).phase).toBe('approving');
  });

  it('follows the server clock across a DST change', () => {
    // 2026-11-01: New York is on EST (UTC-5) by 09:30.
    const day = '2026-11-01';
    const state = deskState({ date: day, deadlines: deadlinesFor(day, day, EST) });
    expect(approveBlockedReason(state, at('2026-11-01T14:59:00Z'))).toBeNull(); // 09:59 EST
    expect(approveBlockedReason(state, at('2026-11-01T15:00:00Z'))).toMatch(/closed/); // 10:00 EST
    expect(deskDayStatus(state, at('2026-11-01T14:00:00Z')).countdownTo).toBe(at('2026-11-01T14:30:00Z'));
  });

  it('applies on weekends like any day', () => {
    const saturday = '2026-10-10';
    const state = deskState({ date: saturday, deadlines: deadlinesFor(saturday) });
    expect(deskDayStatus(state, at(EDT(saturday, '09:00'))).title).toBe('Open — approve by 09:30');
    expect(deskDayStatus(state, at(EDT(saturday, '10:30'))).phase).toBe('fallback');
  });

  it('says plainly when the database does not record the send (before migration 026)', () => {
    const state = {
      ...open,
      sendTracked: false,
      published: { published_by: 'd@x.com', published_at: EDT(D, '09:10') },
    };
    expect(deskDayStatus(state, at(EDT(D, '09:40'))).title).toBe('Approved');
    expect(deskDayStatus(state, at(EDT(D, '09:20'))).title).toBe('Approved — sends at 09:30');
  });
});

describe('rescind (the desk takes back its approval, C8)', () => {
  const approved = deskState({
    deadlines: deadlinesFor(D),
    sendTracked: true,
    publish: command({ kind: 'publish', status: 'done' }),
    published: { published_by: 'd@x.com', published_at: EDT(D, '09:10'), publish_source: 'desk', sent_at: null },
  });

  it('is open on an unsent desk approval until 09:30 New York', () => {
    expect(rescindBlockedReason(approved, at(EDT(D, '09:12')))).toBeNull();
    expect(rescindBlockedReason(approved, at(EDT(D, '09:29')) + 59_999)).toBeNull();
    expect(rescindBlockedReason(approved, at(EDT(D, '09:30')))).toMatch(/can no longer be taken back/);
    expect(rescindBlockedReason(approved, at(EDT(D, '09:45')))).toMatch(/e-mailed at 09:30 New York/);
  });

  it('follows the server clock across a DST change', () => {
    const day = '2026-11-01';
    const state = {
      ...approved,
      date: day,
      deadlines: deadlinesFor(day, day, EST),
      published: { ...approved.published!, published_at: EST(day, '09:00') },
    };
    expect(rescindBlockedReason(state, at('2026-11-01T14:29:00Z'))).toBeNull(); // 09:29 EST
    expect(rescindBlockedReason(state, at('2026-11-01T14:30:00Z'))).not.toBeNull(); // 09:30 EST
  });

  it('is closed on a day that is not a desk approval', () => {
    const now = at(EDT(D, '09:00'));
    expect(rescindBlockedReason(deskState({ deadlines: deadlinesFor(D) }), now)).toBe('The day is not approved');
    expect(rescindBlockedReason({ ...approved, date: null }, now)).toBe('No book for today yet');
    const engine = {
      ...approved,
      published: { published_by: 'system:non-trading-day', published_at: EDT(D, '01:00') },
    };
    expect(rescindBlockedReason(engine, now)).toBe('Only a desk approval can be taken back');
    const fallback = {
      ...approved,
      published: { published_by: 'system:fallback-10am', published_at: EDT(D, '10:00'), publish_source: 'fallback' as const },
    };
    expect(rescindBlockedReason(fallback, now)).toBe('Only a desk approval can be taken back');
    // An approval still in progress is not yet an approval to take back.
    const publishing = deskState({ deadlines: deadlinesFor(D), publish: command({ kind: 'publish', status: 'running' }) });
    expect(rescindBlockedReason(publishing, now)).toBe('The day is not approved');
  });

  it('is closed once sent, without send tracking, on a past day and while one is open', () => {
    const now = at(EDT(D, '09:00'));
    const sent = { ...approved, published: { ...approved.published!, sent_at: EDT(D, '09:05') } };
    expect(rescindBlockedReason(sent, now)).toBe('The book has already been e-mailed');
    expect(rescindBlockedReason({ ...approved, sendTracked: false }, now)).toMatch(/migration 026/);
    const pastDay = { ...approved, date: '2026-10-07', deadlines: deadlinesFor('2026-10-07', D) };
    expect(rescindBlockedReason(pastDay, now)).toMatch(/can no longer be taken back/);
    expect(rescindBlockedReason({ ...approved, deadlines: undefined }, now)).toMatch(/can no longer be taken back/);
    const rescinding = { ...approved, rescind: command({ kind: 'rescind', status: 'pending' }) };
    expect(rescindOpen(rescinding)).toBe(true);
    expect(rescindBlockedReason(rescinding, now)).toBe('Taking the approval back is in progress');
    // A refused rescind leaves the approval in place: it may be tried again.
    const refused = { ...approved, rescind: command({ kind: 'rescind', status: 'refused' }) };
    expect(rescindOpen(refused)).toBe(false);
    expect(rescindBlockedReason(refused, now)).toBeNull();
  });

  it('shows the rescind in the banner and reopens the day once the engine cleared the approval', () => {
    const now = at(EDT(D, '09:12'));
    expect(deskDayStatus(approved, now).detail).toMatch(/can be taken back/);
    const rescinding = { ...approved, rescind: command({ kind: 'rescind', status: 'running' }) };
    const status = deskDayStatus(rescinding, now);
    expect(status.phase).toBe('rescinding');
    expect(status.title).toBe('Rescinding — waiting for the engine');
    expect(status.countdownTo).toBe(at(EDT(D, '09:30')));
    // The engine cleared published_at: the publish row stays done, the day is open again.
    const reopened = { ...approved, published: null, rescind: command({ kind: 'rescind', status: 'done' }) };
    expect(deskDayStatus(reopened, now).phase).toBe('open');
    expect(approveBlockedReason(reopened, now)).toBeNull();
    expect(editBlockedReason(reopened, now)).toBeNull();
    expect(rescindBlockedReason(reopened, now)).toBe('The day is not approved');
  });

  it('asks for confirmation in plain words', () => {
    expect(rescindConfirmText('2026-10-08')).toBe(
      "Take back the approval of 2026-10-08? The day reopens for edits and must be approved again by 09:30, or the model's book is sent at 10:00.",
    );
  });
});

describe('the countdown', () => {
  it('formats what is left, never below zero', () => {
    expect(formatCountdown(0)).toBe('0m 00s');
    expect(formatCountdown(-5_000)).toBe('0m 00s');
    expect(formatCountdown(9_999)).toBe('0m 09s');
    expect(formatCountdown(29 * 60_000 + 59_000)).toBe('29m 59s');
    expect(formatCountdown(3_600_000 + 2 * 60_000 + 5_000)).toBe('1h 02m 05s');
  });

  it('runs on the server clock, not the browser clock', () => {
    // The browser is 7 minutes fast.
    const browserNow = at('2026-10-08T13:07:00Z');
    const offset = serverClockOffsetMs('2026-10-08T13:00:00+00:00', browserNow);
    expect(offset).toBe(-7 * 60_000);
    const status = deskDayStatus(deskState({ deadlines: deadlinesFor(D) }), browserNow + offset);
    expect(formatCountdown(status.countdownTo! - (browserNow + offset))).toBe('30m 00s');
    expect(serverClockOffsetMs(undefined, browserNow)).toBe(0);
    expect(serverClockOffsetMs('garbage', browserNow)).toBe(0);
  });

  it('prints New York wall-clock times', () => {
    expect(newYorkTime('2026-10-08T13:30:04Z')).toBe('09:30');
    expect(newYorkTime('2026-11-02T14:30:00Z')).toBe('09:30');
    expect(newYorkTime(null)).toBe('');
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

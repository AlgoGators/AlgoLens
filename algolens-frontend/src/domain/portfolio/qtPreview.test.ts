import { describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import fixtures from '../../../../contracts/qt-workflow-v1.json';
import {
  canConfirmQt, decodeQtBookDecision, decodeQtDecision, decodeQtDraft, decodeQtPreview,
  decodeQtProposal, makeQtState, normalizeQtSelectionInput,
  qtComponentKey, qtContextKey, reduceQtState,
} from './qtPreview';

const copy = <T>(value: T): T => structuredClone(value);
const clean = () => decodeQtPreview(copy(fixtures.preview_clean));
const draft = () => decodeQtDraft(copy(fixtures.draft_saved));
const proposal = () => decodeQtProposal(copy(fixtures.proposal_ready));
const context = qtContextKey('101', 'synthetic-book-A', '2026-09-25');

describe('QT v1 wire values', () => {
  it('rejects the retired approver identity', () => {
    const decision = copy(fixtures.confirm_pending) as any;
    decision.approvals = [{ person_id: 'eric_shwartz', display_label: 'Eric Shwartz', user_id: '101',
      approved_at: '2026-09-25T16:00:00Z' }];
    decision.approvals_count = 1;
    expect(() => decodeQtDecision(decision)).toThrow();
  });

  it.each(['breach', 'clean'] as const)('does not admit a local %s confirmation contradicting the paired override semantics', mode => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'evaluation_started', context, generation: 0 });
    const preview = decodeQtPreview(copy(mode === 'breach' ? fixtures.preview_breach : fixtures.preview_clean));
    state = reduceQtState(state, { type: 'preview_loaded', context, generation: 1, preview });
    const approvals = [{ person_id: 'hemdutt_rao', display_label: 'Hemdutt Rao', user_id: '101',
      approved_at: '2026-09-25T16:00:00Z' }, { person_id: 'xander_robbins', display_label: 'Xander Robbins', user_id: '202',
      approved_at: '2026-09-25T16:01:00Z' }];
    const raw = mode === 'breach' ? { ...copy(fixtures.confirm_pending), status: 'confirmed_decision',
      can_approve: false, request_id: null } : { ...copy(fixtures.decision_pending),
      request_id: fixtures.confirm_pending.request_id, approvals, approvals_count: 2 };
    const decision = decodeQtDecision(raw);
    const rejected = reduceQtState(state, { type: 'decision_loaded', context, generation: 1, decision });
    expect(rejected).toBe(state);
    expect(rejected.decision).toBeNull();
  });

  it.each(['processing', 'processed'] as const)('rejects confirmed breach %s evidence without the override request/quorum', stage => {
    const preview = copy(fixtures.preview_breach);
    const decision = { ...copy(fixtures.confirm_pending), status: 'confirmed_decision', request_id: null,
      approvals: [], approvals_count: 0, can_approve: false,
      receipt: stage === 'processed' ? { ...copy(fixtures.decision_processed.receipt),
        published_book_digest: preview.selected_book_digest } : null,
      report_ready: stage === 'processed', report_blocked_reasons: stage === 'processed' ? [] : ['receipt_pending'] };
    expect(() => decodeQtDecision(decision)).not.toThrow();
    expect(() => decodeQtBookDecision({ schema_version: 'qt-workflow/v1', book_id: preview.book_id,
      source_day: preview.source_day, decision, preview })).toThrow();
  });

  it('rejects a clean confirmed pair with an invented override request while admitting an actual distinct-person breach quorum', () => {
    const approvals = [{ person_id: 'hemdutt_rao', display_label: 'Hemdutt Rao', user_id: '101',
      approved_at: '2026-09-25T16:00:00Z' }, { person_id: 'xander_robbins', display_label: 'Xander Robbins', user_id: '202',
      approved_at: '2026-09-25T16:01:00Z' }];
    const decision = { ...copy(fixtures.decision_pending), request_id: fixtures.confirm_pending.request_id,
      approvals, approvals_count: 2 };
    expect(() => decodeQtDecision(decision)).not.toThrow();
    expect(() => decodeQtBookDecision({ schema_version: 'qt-workflow/v1', book_id: fixtures.preview_clean.book_id,
      source_day: fixtures.preview_clean.source_day, decision, preview: copy(fixtures.preview_clean) })).toThrow();
    const breach = { ...copy(fixtures.confirm_pending), status: 'confirmed_decision', can_approve: false,
      approvals, approvals_count: 2 };
    expect(decodeQtBookDecision({ schema_version: 'qt-workflow/v1', book_id: fixtures.preview_breach.book_id,
      source_day: fixtures.preview_breach.source_day, decision: breach, preview: copy(fixtures.preview_breach) }).decision?.approvals_count).toBe(2);
  });

  it('admits verified previous QT choices outside MODEL seeds without inventing seed provenance', () => {
    const saved = copy(fixtures.draft_saved) as any;
    saved.selection_rows[0].origin = 'verified_qt_decision';
    expect(decodeQtDraft(saved).selection_rows[0].origin).toBe('verified_qt_decision');
    const preview = copy(fixtures.preview_clean) as any;
    preview.selection_rows[0].origin = 'verified_qt_decision';
    const sorted = (value: any): any => Array.isArray(value) ? value.map(sorted) :
      value && typeof value === 'object' ? Object.fromEntries(Object.keys(value).sort().map(k => [k, sorted(value[k])])) : value;
    const { payload_digest: _oldDigest, ...payload } = preview;
    preview.payload_digest = createHash('sha256').update(JSON.stringify(sorted(payload))).digest('hex');
    expect(decodeQtPreview(preview).selection_rows[0].origin).toBe('verified_qt_decision');
    const source = copy(fixtures.proposal_ready) as any;
    source.saved_qt_rows = copy(saved.selection_rows).map((row: any) => ({ ...row,
      key: { ...row.key, portfolio_type: 'qt' }, origin: 'verified_qt_decision' }));
    expect(decodeQtProposal(source).saved_qt_rows[0].origin).toBe('verified_qt_decision');
    source.seed_rows[0].origin = 'verified_qt_decision';
    expect(() => decodeQtProposal(source)).toThrow();
  });

  it('strictly discovers one immutable linked book/day decision or explicit absence', () => {
    const envelope = { schema_version: 'qt-workflow/v1', book_id: 'synthetic-book-A', source_day: '2026-09-25',
      decision: copy(fixtures.confirm_pending), preview: copy(fixtures.preview_breach) };
    expect(decodeQtBookDecision(envelope).decision?.decision_id).toBe(fixtures.confirm_pending.decision_id);
    expect(decodeQtBookDecision({ ...envelope, decision: null, preview: null }).decision).toBeNull();
    for (const change of [
      (x: any) => { x.browser_grant = true; },
      (x: any) => { x.decision = null; },
      (x: any) => { x.preview = null; },
      (x: any) => { x.book_id = 'other-book'; },
      (x: any) => { x.source_day = '2026-09-26'; },
      (x: any) => { x.decision.preview_id = '30000000-0000-4000-8000-000000000099'; },
      (x: any) => { x.decision.selected_book_digest = 'e'.repeat(64); },
      (x: any) => { x.decision.read_set_digest = 'e'.repeat(64); },
      (x: any) => { x.preview.selection_rows[0].quantity_exact = '6'; },
      (x: any) => { x.preview.selection_rows[0].key.strategy_id = 'other-owner'; },
    ]) { const invalid = copy(envelope); change(invalid); expect(() => decodeQtBookDecision(invalid)).toThrow(); }
  });
  it('accepts every named public success example with distinct optimizer and selected scopes', () => {
    expect(proposal().seed_rows.map(row => row.quantity_exact)).toEqual(['4', '2']);
    expect(draft().selection_rows.map(row => row.quantity_exact)).toEqual(['5', '1']);
    expect(clean().evaluation.optimizer.evaluated_book_digest).toBe(fixtures.preview_clean.optimizer_book_digest);
    expect(clean().evaluation.selected_risk.evaluated_book_digest).toBe(fixtures.preview_clean.selected_book_digest);
    expect(decodeQtPreview(copy(fixtures.preview_breach)).requires_override).toBe(true);
    expect(decodeQtDecision(copy(fixtures.confirm_pending)).status).toBe('pending_override');
    expect(decodeQtDecision(copy(fixtures.decision_pending)).report_ready).toBe(false);
    expect(decodeQtDecision(copy(fixtures.decision_processed)).report_ready).toBe(true);
  });

  it('uses all six key fields and keeps owner and actor contexts separate', () => {
    const a = fixtures.proposal_ready.seed_rows[0].key;
    const b = fixtures.proposal_ready.seed_rows[1].key;
    expect(qtComponentKey(a)).not.toBe(qtComponentKey(b));
    expect(qtComponentKey({ ...a, portfolio_type: 'qt' })).not.toBe(qtComponentKey(a));
    expect(qtContextKey('101', 'book', a.date)).not.toBe(qtContextKey('102', 'book', a.date));
    expect(qtContextKey('101', 'book', a.date)).not.toBe(qtContextKey('101', 'other', a.date));
  });

  it('admits signed/zero/fractional exact quantities without rounding but rejects fractional futures', () => {
    expect(normalizeQtSelectionInput('+5', 'EQUITY')).toBe('5');
    expect(normalizeQtSelectionInput('-5', 'EQUITY')).toBe('-5');
    expect(normalizeQtSelectionInput('0', 'EQUITY')).toBe('0');
    expect(normalizeQtSelectionInput('2.5', 'EQUITY')).toBe('2.5');
    expect(normalizeQtSelectionInput('-3', 'FUTURE')).toBe('-3');
    expect(() => normalizeQtSelectionInput('2.5', 'FUTURE')).toThrow();
    expect(() => normalizeQtSelectionInput('0.000000001', 'EQUITY')).toThrow();
  });

  it('rejects malformed source and draft authority and key collisions', () => {
    const p = copy(fixtures.proposal_ready) as any;
    p.seed_rows.push(copy(p.seed_rows[0]));
    expect(() => decodeQtProposal(p)).toThrow();
    const d = copy(fixtures.draft_saved) as any;
    d.selection_rows[1].key.portfolio_id = 'other-book';
    expect(() => decodeQtDraft(d)).toThrow();
    for (const change of [
      (x: any) => { x.schema_version = 'qt-workflow/v2'; },
      (x: any) => { x.draft_revision = undefined; },
      (x: any) => { x.selection_rows[0].quantity_exact = 5; },
      (x: any) => { x.selection_rows[0].quantity_exact = '5.000000000'; },
      (x: any) => { x.selection_rows[0].asset_type = 'FUTURE'; x.selection_rows[0].quantity_exact = '2.5'; },
      (x: any) => { x.selection_rows[0].average_price_exact = null; },
      (x: any) => { x.selection_rows[0].key.date = '2026-09-26'; },
    ]) {
      const broken = copy(fixtures.draft_saved) as any;
      change(broken);
      expect(() => decodeQtDraft(broken)).toThrow();
    }
  });

  it('rejects partial, wrong-scope or forged ready preview evidence', () => {
    const changes = [
      (x: any) => { x.payload_digest = undefined; },
      (x: any) => { x.draft_revision = 0; },
      (x: any) => { x.availability = 'other'; },
      (x: any) => { x.selection_rows[0].key.portfolio_id = 'other-book'; },
      (x: any) => { x.selection_rows.push(copy(x.selection_rows[0])); },
      (x: any) => { x.evaluation.selected_risk = null; },
      (x: any) => { x.evaluation.selected_risk.status = 'unavailable'; },
      (x: any) => { x.evaluation.selected_risk.evaluated_book_digest = x.optimizer_book_digest; },
      (x: any) => { x.evaluation.selected_costs.evaluated_book_digest = x.optimizer_book_digest; },
      (x: any) => { x.evaluation.optimizer.evaluated_book_digest = x.selected_book_digest; },
      (x: any) => { x.evaluation.selected_costs.by_component.pop(); },
      (x: any) => { x.evaluation.selected_costs.total_exact = '0.03'; },
      (x: any) => { x.evaluation.selected_costs.by_component[0].selected_quantity_exact = '3'; },
      (x: any) => { x.evaluation.selected_risk.passed = false; },
      (x: any) => { x.confirmable = false; },
      (x: any) => { x.availability = 'unavailable'; },
    ];
    for (const change of changes) {
      const broken = copy(fixtures.preview_clean) as any;
      change(broken);
      expect(() => decodeQtPreview(broken)).toThrow();
    }
  });

  it('keeps finite double diagnostics separate from exact cash and quantity fields', () => {
    expect(clean().evaluation.selected_risk.metrics[0].value_diagnostic).toBe('0.12345678901234566');
    for (const bad of ['NaN', 'Infinity', '1e9999', '1e-9999', '0.10000000000000001x']) {
      const broken = copy(fixtures.preview_clean) as any;
      broken.evaluation.selected_risk.metrics[0].value_diagnostic = bad;
      expect(() => decodeQtPreview(broken)).toThrow();
    }
    for (const legacy of ['value_exact', 'limit_exact', 'actual_exact']) {
      const broken = copy(fixtures.preview_breach) as any;
      const target = legacy === 'value_exact' ? broken.evaluation.selected_risk.metrics[0] : broken.evaluation.selected_risk.breaches[0];
      target[legacy] = '0.1';
      expect(() => decodeQtPreview(broken)).toThrow();
    }
    const badCash = copy(fixtures.preview_clean) as any;
    badCash.evaluation.selected_costs.total_exact = '0.12345678901234566';
    expect(() => decodeQtPreview(badCash)).toThrow();
  });

  it('rejects report success without the matching processed receipt and complete eligibility', () => {
    const changes = [
      (x: any) => { x.receipt = null; },
      (x: any) => { x.receipt.status = 'pending'; },
      (x: any) => { x.receipt.published_book_digest = 'a'.repeat(64); },
      (x: any) => { x.receipt.report_eligibility.status = 'blocked'; },
      (x: any) => { x.receipt.report_eligibility.row_manifest_digest = null; },
      (x: any) => { x.status = 'other'; },
      (x: any) => { x.approvals_count = 1; },
      (x: any) => { x.report_blocked_reasons = ['not_ready']; },
    ];
    for (const change of changes) {
      const broken = copy(fixtures.decision_processed) as any;
      change(broken);
      expect(() => decodeQtDecision(broken)).toThrow();
    }
    const pending = copy(fixtures.confirm_pending) as any;
    pending.report_ready = true;
    expect(() => decodeQtDecision(pending)).toThrow();
    const wrongPublished = copy(fixtures.decision_processed) as any;
    wrongPublished.report_ready = false;
    wrongPublished.report_blocked_reasons = ['render_mapping_unavailable'];
    wrongPublished.receipt.published_book_digest = 'a'.repeat(64);
    expect(() => decodeQtDecision(wrongPublished)).toThrow();
  });

  it('accepts a pending receipt without a published digest while keeping report output blocked', () => {
    const pending = copy(fixtures.decision_pending) as any;
    pending.receipt = { status: 'pending', published_book_digest: null,
      report_eligibility: { status: 'unavailable', reason_codes: ['receipt_pending'], row_manifest_digest: null } };
    const decoded = decodeQtDecision(pending);
    expect(decoded.receipt?.status).toBe('pending');
    expect(decoded.receipt?.published_book_digest).toBeNull();
    expect(decoded.report_ready).toBe(false);
  });

  it('rejects malformed UTC approval time and invalid Unicode text', () => {
    const approved = copy(fixtures.confirm_pending) as any;
    approved.approvals = [{ person_id: 'dominick_dupuy', display_label: 'Dominick Dupuy',
      user_id: '101', approved_at: '2026-02-30T12:00:00Z' }];
    approved.approvals_count = 1;
    expect(() => decodeQtDecision(approved)).toThrow();
    const text = copy(fixtures.proposal_ready) as any;
    text.seed_rows[0].key.symbol = '\ud800';
    expect(() => decodeQtProposal(text)).toThrow();
  });
});

describe('QT context-owned state', () => {
  it('allows a new edit after unavailable preview evidence only while the saved source remains authorized', () => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'evaluation_started', context, generation: 0 });
    const unavailable = { ...clean(), availability: 'unavailable' as const, confirmable: false,
      unavailable_reasons: ['risk_evidence_unavailable'] };
    state = reduceQtState(state, { type: 'preview_loaded', context, generation: 1, preview: unavailable });
    expect(state.phase).toBe('unavailable');
    const generation = state.generation;
    const selection = { ...state.selection, [qtComponentKey(draft().selection_rows[0].key)]: '2.5' };
    state = reduceQtState(state, { type: 'edited', context, selection });
    expect(state.phase).toBe('editing');
    expect(state.generation).toBe(generation + 1);
    expect(state.selection).toEqual(selection);
    expect(state.preview).toBeNull();
    expect(canConfirmQt(state)).toBe(false);

    let blocked = makeQtState(context);
    blocked = reduceQtState(blocked, { type: 'proposal_loaded', context, generation: 0,
      proposal: { ...proposal(), capability: { required: true, available: false, version: 1 },
        workflow_state: 'workflow_unavailable' } });
    blocked = reduceQtState(blocked, { type: 'edited', context, selection });
    expect(blocked.phase).toBe('unavailable');
    expect(blocked.selection).toEqual({});
    const absent = reduceQtState(makeQtState(context), { type: 'edited', context, selection });
    expect(absent.phase).toBe('loading');
    expect(absent.selection).toEqual({});
  });

  it('keeps an edit made during saving and rejects the older save response', () => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'save_started', context, generation: 0 });
    expect(state.phase).toBe('saving');
    expect(state.generation).toBe(1);
    const editedSelection = { ...state.selection, [qtComponentKey(draft().selection_rows[0].key)]: '7' };
    state = reduceQtState(state, { type: 'edited', context, selection: editedSelection });
    expect(state.phase).toBe('editing');
    expect(state.generation).toBe(2);
    const savedA = { ...draft(), draft_revision: 2, draft_digest: 'd'.repeat(64) };
    state = reduceQtState(state, { type: 'draft_saved', context, generation: 1, draft: savedA });
    expect(state.selection).toEqual(editedSelection);
    expect(state.draft?.draft_revision).toBe(1);
    expect(canConfirmQt(state)).toBe(false);
  });

  it('rejects prior A responses after switching A to B and back to A', () => {
    const other = qtContextKey('101', 'other-book', '2026-09-25');
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'context_changed', context: other });
    state = reduceQtState(state, { type: 'context_changed', context });
    expect(state.generation).toBe(2);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    expect(state.proposal).toBeNull();
    expect(state.draft).toBeNull();
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 2, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 2, draft: draft() });
    state = reduceQtState(state, { type: 'evaluation_started', context, generation: 2 });
    state = reduceQtState(state, { type: 'preview_loaded', context, generation: 1, preview: clean() });
    expect(state.preview).toBeNull();
    expect(canConfirmQt(state)).toBe(false);
  });

  it('distinguishes desk publication from report projection eligibility', () => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'evaluation_started', context, generation: 0 });
    state = reduceQtState(state, { type: 'preview_loaded', context, generation: 1, preview: clean() });
    const blocked = copy(fixtures.decision_processed) as any;
    blocked.report_ready = false;
    blocked.report_blocked_reasons = ['row_mapping_ambiguous'];
    blocked.receipt.report_eligibility = { status: 'unavailable', reason_codes: ['row_mapping_ambiguous'], row_manifest_digest: null };
    state = reduceQtState(state, { type: 'decision_loaded', context, generation: 1, decision: decodeQtDecision(blocked) });
    expect(state.phase).toBe('report_blocked');
    expect(state.decision?.receipt?.status).toBe('processed');
    expect(state.decision?.report_ready).toBe(false);
  });

  it('clears unsaved selection when the source identity changes', () => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'edited', context, selection: { ...state.selection, [qtComponentKey(draft().selection_rows[0].key)]: '7' } });
    const changed = { ...proposal(), source_digest: 'd'.repeat(64) };
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 1, proposal: changed });
    expect(state.selection).toEqual({});
    expect(state.draft).toBeNull();
    expect(state.phase).toBe('loading');
    state = reduceQtState(state, { type: 'edited', context, selection: { [qtComponentKey(draft().selection_rows[0].key)]: '7' } });
    expect(state.selection).toEqual({});
    state = reduceQtState(state, { type: 'save_started', context, generation: state.generation });
    expect(state.phase).toBe('loading');
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: state.generation, draft: draft() });
    expect(state.phase).toBe('loading');
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: state.generation,
      draft: { ...draft(), source_digest: changed.source_digest } });
    expect(state.phase).toBe('editing');
    expect(canConfirmQt(state)).toBe(false);
  });

  it('ignores evaluation A after edit B and keeps confirmation disabled', () => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'evaluation_started', context, generation: 0 });
    expect(state.generation).toBe(1);
    state = reduceQtState(state, { type: 'edited', context, selection: { ...state.selection, [qtComponentKey(draft().selection_rows[0].key)]: '2.5' } });
    state = reduceQtState(state, { type: 'preview_loaded', context, generation: 1, preview: clean() });
    expect(state.phase).toBe('editing');
    expect(state.preview).toBeNull();
    expect(canConfirmQt(state)).toBe(false);
  });

  it('ignores a prior book decision and older draft revision', () => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'evaluation_started', context, generation: 0 });
    state = reduceQtState(state, { type: 'preview_loaded', context, generation: 1, preview: clean() });
    expect(canConfirmQt(state)).toBe(true);
    state = reduceQtState(state, { type: 'context_changed', context: qtContextKey('101', 'other-book', '2026-09-25') });
    state = reduceQtState(state, { type: 'decision_loaded', context, generation: 1, decision: decodeQtDecision(copy(fixtures.decision_processed)) });
    expect(state.phase).toBe('loading');
    expect(state.decision).toBeNull();
    expect(canConfirmQt(state)).toBe(false);
  });

  it('rejects a preview for a different saved revision or selection', () => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'evaluation_started', context, generation: 0 });
    const wrong = { ...clean(), draft_revision: 2 };
    state = reduceQtState(state, { type: 'preview_loaded', context, generation: 1, preview: wrong });
    expect(canConfirmQt(state)).toBe(false);
  });

  it('invalidates reviewed authority when the source or saved draft changes', () => {
    let state = makeQtState(context);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 0, proposal: proposal() });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: draft() });
    state = reduceQtState(state, { type: 'evaluation_started', context, generation: 0 });
    state = reduceQtState(state, { type: 'preview_loaded', context, generation: 1, preview: clean() });
    expect(canConfirmQt(state)).toBe(true);
    state = reduceQtState(state, { type: 'proposal_loaded', context, generation: 1,
      proposal: { ...proposal(), source_digest: 'd'.repeat(64) } });
    expect(state.preview).toBeNull();
    expect(canConfirmQt(state)).toBe(false);
  });
});

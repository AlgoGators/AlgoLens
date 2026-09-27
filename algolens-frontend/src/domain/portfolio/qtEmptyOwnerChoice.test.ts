import { describe, expect, it } from 'vitest';
import fixtures from '../../../../contracts/qt-workflow-v1.json';
import { decodeQtDraft, decodeQtProposal, makeQtState, qtContextKey, reduceQtState } from './qtPreview';

const marker = () => ({ schema_version: 'qt-empty-owner-choice/v2',
  model_publication_id: fixtures.proposal_ready.seed_publication_id,
  owner_document_digest: 'a'.repeat(64), configured_owner_names: ['EQUITY_MEAN_REVERSION'] });
const proposal = () => ({ ...structuredClone(fixtures.proposal_ready), schema_version: 'qt-workflow/v2',
  seed_rows: [], saved_qt_rows: [], empty_owner: marker() });
const draft = () => ({ ...structuredClone(fixtures.draft_saved), schema_version: 'qt-workflow/v2',
  selection_rows: [], empty_owner: marker() });
const consumed = () => ({ ...draft(), state: 'consumed', successor: {
  decision_id: '10000000-0000-4000-8000-000000000001',
  attempt_id: '20000000-0000-4000-8000-000000000001',
  preview_id: '30000000-0000-4000-8000-000000000001', publication_digest: 'c'.repeat(64),
} });
const context = qtContextKey('101', fixtures.proposal_ready.book_id, fixtures.proposal_ready.source_day);

describe('explicit empty-owner choice evidence', () => {
  it('admits the closed v2 current proposal and saved or absent draft without inventing a row', () => {
    expect(decodeQtProposal(proposal())).toEqual(proposal());
    expect(decodeQtDraft(draft())).toEqual(draft());
    const absent = { ...draft(), state: 'absent', draft_id: null, draft_revision: 0, draft_digest: null };
    expect(decodeQtDraft(absent)).toEqual(absent);
  });

  it.each(['publication', 'extra', 'digest', 'owners', 'nonempty', 'legacy_marker', 'missing_marker', 'unready'])(
    'refuses %s proposal evidence', mutation => {
      const value = proposal();
      if (mutation === 'publication') value.empty_owner.model_publication_id = '99999999-9999-4999-8999-999999999999';
      if (mutation === 'extra') Object.assign(value.empty_owner, { ready: true });
      if (mutation === 'digest') value.empty_owner.owner_document_digest = 'unverified';
      if (mutation === 'owners') value.empty_owner.configured_owner_names.push('SECOND_OWNER');
      if (mutation === 'nonempty') Object.assign(value, { saved_qt_rows: fixtures.proposal_ready.seed_rows });
      if (mutation === 'legacy_marker') value.schema_version = 'qt-workflow/v1';
      if (mutation === 'missing_marker') Reflect.deleteProperty(value, 'empty_owner');
      if (mutation === 'unready') { value.workflow_state = 'workflow_unavailable';
        value.action_grants.can_save_draft = false; value.action_grants.can_confirm = false; }
      expect(() => decodeQtProposal(value)).toThrow('invalid_qt_payload');
    });

  it.each(['stale', 'provenance_unresolved', 'missing_source', 'nonempty'])(
    'refuses a %s draft claiming empty-owner permission', mutation => {
      const value = draft();
      if (mutation === 'stale' || mutation === 'provenance_unresolved') value.state = mutation;
      if (mutation === 'missing_source') Object.assign(value, { source_digest: null });
      if (mutation === 'nonempty') Object.assign(value, { selection_rows: fixtures.draft_saved.selection_rows });
      expect(() => decodeQtDraft(value)).toThrow('invalid_qt_payload');
    });

  it.each(['publication', 'document', 'owner', 'source', 'provenance', 'legacy'])(
    'does not accept a draft with different %s authority into the current empty choice', mutation => {
      let state = reduceQtState(makeQtState(context), { type: 'proposal_loaded', context, generation: 0,
        proposal: decodeQtProposal(proposal()) });
      const value = draft();
      if (mutation === 'publication') value.empty_owner.model_publication_id = '99999999-9999-4999-8999-999999999999';
      if (mutation === 'document') value.empty_owner.owner_document_digest = 'b'.repeat(64);
      if (mutation === 'owner') value.empty_owner.configured_owner_names = ['OTHER_OWNER'];
      if (mutation === 'source') value.source_digest = 'b'.repeat(64);
      if (mutation === 'provenance') value.provenance_digest = 'f'.repeat(64);
      if (mutation === 'legacy') { value.schema_version = 'qt-workflow/v1'; Reflect.deleteProperty(value, 'empty_owner'); }
      state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: decodeQtDraft(value) });
      expect(state.draft).toBeNull();
      expect(state.phase).toBe('unavailable');
    });

  it('preserves the existing v1 proposal and draft bytes and shapes', () => {
    expect(decodeQtProposal(fixtures.proposal_ready)).toEqual(fixtures.proposal_ready);
    expect(decodeQtDraft(fixtures.draft_saved)).toEqual(fixtures.draft_saved);
  });

  it('keeps a verified consumed draft identity while allowing an explicit successor save', () => {
    const value = consumed();
    expect(decodeQtDraft(value)).toEqual(value);
    let state = reduceQtState(makeQtState(context), { type: 'proposal_loaded', context, generation: 0,
      proposal: decodeQtProposal(proposal()) });
    state = reduceQtState(state, { type: 'draft_loaded', context, generation: 0, draft: decodeQtDraft(value) });
    expect(state.phase).toBe('editing');
    expect(state.draft?.draft_id).toBe(value.draft_id);
    expect(state.draft?.draft_revision).toBe(value.draft_revision);
    expect(state.preview).toBeNull();
    expect(state.decision).toBeNull();
  });

  it.each(['missing', 'extra', 'invalid_digest', 'nil_identity', 'saved', 'stale', 'legacy', 'absent_identity'])(
    'refuses %s consumed-draft evidence', mutation => {
      const value = consumed();
      if (mutation === 'missing') Reflect.deleteProperty(value, 'successor');
      if (mutation === 'extra') Object.assign(value.successor, { processed: true });
      if (mutation === 'invalid_digest') value.successor.publication_digest = 'unverified';
      if (mutation === 'nil_identity') value.successor.attempt_id = '00000000-0000-0000-0000-000000000000';
      if (mutation === 'saved' || mutation === 'stale') value.state = mutation;
      if (mutation === 'legacy') value.schema_version = 'qt-workflow/v1';
      if (mutation === 'absent_identity') Object.assign(value, { draft_id: null, draft_revision: 0, draft_digest: null });
      expect(() => decodeQtDraft(value)).toThrow('invalid_qt_payload');
    });

  it.each(['nil_publication', 'blank_owner', 'long_owner', 'unicode_owner'])(
    'refuses marker-local %s invalidity in both DTOs', mutation => {
      const p = proposal(); const d = draft();
      for (const item of [p, d]) {
        if (mutation === 'nil_publication') item.empty_owner.model_publication_id = '00000000-0000-0000-0000-000000000000';
        if (mutation === 'blank_owner') item.empty_owner.configured_owner_names = ['   '];
        if (mutation === 'long_owner') item.empty_owner.configured_owner_names = ['a'.repeat(257)];
        if (mutation === 'unicode_owner') item.empty_owner.configured_owner_names = ['\u00e9'.repeat(129)];
      }
      p.seed_publication_id = p.empty_owner.model_publication_id;
      expect(() => decodeQtProposal(p)).toThrow('invalid_qt_payload');
      expect(() => decodeQtDraft(d)).toThrow('invalid_qt_payload');
    });
});

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import examples from './__fixtures__/qtEmptyOwnerContract.synthetic.json';
import { decodeQtDraft, decodeQtProposal, qtEmptyOwnerMatches } from '../../domain/portfolio/qtPreview';

describe('staged API to UI empty-owner contract (synthetic examples)', () => {
  it('uses the unchanged server-produced sample and preserves its evidence limits', () => {
    const raw = readFileSync(new URL('./__fixtures__/qtEmptyOwnerContract.synthetic.json', import.meta.url));
    expect(createHash('sha256').update(raw).digest('hex')).toBe('7ac3da4f1cf183b7c7da23e7ebbf8fbde2b2ac7df24a1e2b8696f4c1f831dea1');
    expect(examples.evidence_scope).toBe('synthetic_contract_examples_only');
    expect(examples.native_or_sql_acceptance).toBe(false);
  });

  it.each(['draft_absent', 'draft_saved'] as const)('decodes and matches the actual %s serialization', name => {
    const proposal = decodeQtProposal(examples.proposal);
    const draft = decodeQtDraft(examples[name]);
    expect(proposal).toEqual(examples.proposal);
    expect(draft).toEqual({ ...examples[name], rationale: null });
    expect(qtEmptyOwnerMatches(proposal, draft)).toBe(true);
  });

  it('matches the consumed draft only to its new current source authority', () => {
    const draft = decodeQtDraft(examples.draft_consumed);
    const current = decodeQtProposal(examples.proposal_consumed);
    expect(draft).toEqual({ ...examples.draft_consumed, rationale: null });
    expect(current).toEqual(examples.proposal_consumed);
    expect(qtEmptyOwnerMatches(current, draft)).toBe(true);
    expect(qtEmptyOwnerMatches(decodeQtProposal(examples.proposal), draft)).toBe(false);
  });
});

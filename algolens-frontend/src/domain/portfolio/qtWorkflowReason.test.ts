import { describe, expect, it } from 'vitest';
import { qtWorkflowReasonText } from './qtWorkflowReason';

describe('qtWorkflowReasonText', () => {
  it('turns workflow_unavailable into an instruction the reader can act on', () => {
    expect(qtWorkflowReasonText('workflow_unavailable')).toBe(
      'QT editing is not turned on for this book yet, so its positions cannot be changed here. '
      + 'Ask an admin to enable the QT desk workflow for this book. Position changes are disabled.');
  });

  it('turns provenance_unresolved into plain words about the missing MODEL source', () => {
    expect(qtWorkflowReasonText('provenance_unresolved')).toBe(
      'This book has no verified MODEL source for the selected day yet, so QT cannot propose or edit quantities. '
      + 'Position changes are disabled.');
  });

  it('never shows a raw backend code for the known states', () => {
    for (const code of ['workflow_unavailable', 'provenance_unresolved']) {
      expect(qtWorkflowReasonText(code)).not.toContain('_');
    }
  });

  it('passes an unknown reason through unchanged, so nothing is hidden', () => {
    expect(qtWorkflowReasonText('Synthetic workflow unavailable')).toBe('Synthetic workflow unavailable');
    expect(qtWorkflowReasonText('some_new_backend_code')).toBe('some_new_backend_code');
  });

  it('falls back to the generic unavailable sentence for null, undefined, empty or blank input', () => {
    const fallback = 'QT workflow is unavailable. Position changes are disabled.';
    expect(qtWorkflowReasonText(null)).toBe(fallback);
    expect(qtWorkflowReasonText(undefined)).toBe(fallback);
    expect(qtWorkflowReasonText('')).toBe(fallback);
    expect(qtWorkflowReasonText('   ')).toBe(fallback);
  });

  it('does not map "ready", which carries no reason; it passes through', () => {
    expect(qtWorkflowReasonText('ready')).toBe('ready');
  });
});

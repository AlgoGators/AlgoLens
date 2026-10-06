/**
 * Plain-language text for the QT workflow's read-only reasons.
 *
 * The API sets `read_only_reason` to the book's `workflow_state` whenever the
 * workflow is not ready (qt_decision_read.get_proposal):
 *   workflow_unavailable   the QT capability is missing or not enabled for the
 *                          book, or its prerequisites are not met
 *   provenance_unresolved  the capability is on, but the book's QT source could
 *                          not be traced to a verified MODEL publication
 *   ready                  no reason is sent
 * Readers cannot act on a raw code, so the known states become sentences.
 * Anything else is passed through unchanged: an unfamiliar reason is never hidden.
 */
const FALLBACK = 'QT workflow is unavailable. Position changes are disabled.';

const KNOWN: Readonly<Record<string, string>> = {
  workflow_unavailable:
    'QT editing is not turned on for this book yet, so its positions cannot be changed here. '
    + 'Ask an admin to enable the QT desk workflow for this book. Position changes are disabled.',
  provenance_unresolved:
    'This book has no verified MODEL source for the selected day yet, so QT cannot propose or edit quantities. '
    + 'Position changes are disabled.',
};

export function qtWorkflowReasonText(code: string | null | undefined): string {
  if (code == null || code.trim() === '') return FALLBACK;
  return Object.prototype.hasOwnProperty.call(KNOWN, code) ? KNOWN[code] : code;
}

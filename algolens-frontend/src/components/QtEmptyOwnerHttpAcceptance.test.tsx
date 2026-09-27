// Install only after the actual seven-case owned PostgreSQL gate succeeds.
// @vitest-environment jsdom
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { QtPreviewApi } from '../infrastructure/api/qtPreviewApi';
import { decodeQtDecision, decodeQtDraft, decodeQtPreview, decodeQtProposal } from '../domain/portfolio/qtPreview';
import { QtDecisionStatus } from './qt-proposal/QtDecisionStatus';
import { QtPreviewEvidence } from './qt-proposal/QtPreviewEvidence';

type Captured = { route: string; request_method: string; http_status: number;
  response_body: string; response_sha256: string };
const directory = 'src/infrastructure/api/__fixtures__/qtEmptyOwnerConnected/';
const digest = (bytes: Uint8Array | string) => createHash('sha256').update(bytes).digest('hex');
function captures(): Captured[] {
  const pins = JSON.parse(readFileSync(directory + 'capture-pins.json', 'utf8'));
  const bytes = readFileSync(directory + 'responses.json');
  expect(digest(bytes)).toBe(pins.responses_sha256);
  expect(pins.runtime_exit_code).toBe(0);
  expect(pins.owned_cleanup_verified).toBe(true);
  expect(pins.source_unchanged).toBe(true);
  expect(pins.native_unchanged).toBe(true);
  expect(pins.api_unchanged).toBe(true);
  expect(pins.actual_model_invoked).toBe(false);
  const rows: Captured[] = JSON.parse(bytes.toString('utf8'));
  expect(rows).toHaveLength(7);
  expect(rows.map(row => row.request_method)).toEqual(['GET', 'GET', 'PUT', 'POST', 'POST', 'GET', 'GET']);
  const proposal = JSON.parse(rows[0].response_body);
  const preview = JSON.parse(rows[3].response_body);
  const decision = JSON.parse(rows[4].response_body);
  const book = '/portfolio/qt-books/' + proposal.book_id;
  expect(rows.map(row => row.route)).toEqual([book + '/proposal', book + '/draft', book + '/draft',
    '/portfolio/qt-previews', '/portfolio/qt-previews/' + preview.preview_id + '/confirm',
    '/portfolio/qt-decisions/' + decision.decision_id, book + '/draft']);
  expect(decision.preview_id).toBe(preview.preview_id);
  for (const row of rows) {
    expect(digest(row.response_body)).toBe(row.response_sha256);
    expect(row.http_status).toBe(200);
  }
  return rows;
}
const parsed = (row: Captured) => JSON.parse(row.response_body);
afterEach(() => vi.restoreAllMocks());

describe('actual empty-owner native, PostgreSQL and HTTP evidence in the frontend', () => {
  it('accepts every captured response through its production decoder', () => {
    const rows = captures();
    for (const row of rows) {
      const body = parsed(row);
      if (row.route.endsWith('/proposal')) expect(decodeQtProposal(body).seed_rows).toEqual([]);
      else if (row.route.endsWith('/draft')) expect(decodeQtDraft(body).selection_rows).toEqual([]);
      else if (row.route === '/portfolio/qt-previews') expect(decodeQtPreview(body).selection_rows).toEqual([]);
      else expect(decodeQtDecision(body).decision_id).toBe(body.decision_id);
    }
    expect(rows.some(row => row.request_method === 'PUT')).toBe(true);
    expect(rows.some(row => row.route.endsWith('/draft') && parsed(row).state === 'consumed')).toBe(true);
  });

  it('loads captured GET responses through the production authenticated API and decoder', async () => {
    const rows = captures().filter(row => row.request_method === 'GET');
    const fetch = vi.spyOn(globalThis, 'fetch');
    for (const row of rows) {
      const body = parsed(row);
      fetch.mockResolvedValueOnce(new Response(row.response_body, {
        status: row.http_status, headers: { 'Content-Type': 'application/json' },
      }));
      let result;
      if (row.route.endsWith('/proposal')) result = await QtPreviewApi.getProposal(body.book_id);
      else if (row.route.endsWith('/draft')) result = await QtPreviewApi.getDraft(body.book_id);
      else result = await QtPreviewApi.getDecision(body.decision_id);
      expect(result).toEqual(body);
      expect(String(fetch.mock.calls.at(-1)?.[0])).toContain(row.route);
    }
    expect(fetch).toHaveBeenCalledTimes(rows.length);
  });

  it('shows real empty risk evidence and withholds readiness until the matching processed receipt', () => {
    const rows = captures();
    const confirmedRaw = rows.find(row => row.route.endsWith('/confirm'))!;
    expect(confirmedRaw).toBeDefined();
    const confirmed = decodeQtDecision(parsed(confirmedRaw));
    const previewRaw = rows.find(row => row.route === '/portfolio/qt-previews' &&
      parsed(row).preview_id === confirmed.preview_id)!;
    const preview = decodeQtPreview(parsed(previewRaw));
    const processedRaw = rows.find(row => row.route === '/portfolio/qt-decisions/' + confirmed.decision_id)!;
    const processed = decodeQtDecision(parsed(processedRaw));
    expect(confirmed.receipt).toBeNull();
    expect(confirmed.report_ready).toBe(false);
    expect(processed.receipt?.status).toBe('processed');
    expect(processed.report_ready).toBe(true);
    expect(processed.preview_id).toBe(preview.preview_id);
    render(<QtPreviewEvidence preview={preview} />);
    expect(within(screen.getByRole('region', { name: 'Selected book risk' })).getByText(
      'This selection has no instruments; price and correlation history are not applicable.')).toBeTruthy();
    const view = render(<QtDecisionStatus decision={confirmed} phase="processing"
      verifiedContext onRefresh={vi.fn()} onApprove={vi.fn()} busy={false} />);
    expect(screen.queryByRole('heading', { name: 'Report ready' })).toBeNull();
    view.rerender(<QtDecisionStatus decision={processed} phase="processed"
      verifiedContext onRefresh={vi.fn()} onApprove={vi.fn()} busy={false} />);
    expect(screen.getByRole('heading', { name: 'Report ready' })).toBeTruthy();
  });
});

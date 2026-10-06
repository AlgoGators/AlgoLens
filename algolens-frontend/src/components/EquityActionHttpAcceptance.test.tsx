// Install only with independently reviewed, actual action-matrix HTTP bytes.
// @vitest-environment jsdom
import React from 'react';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfigurationInspectionPanel } from './ConfigurationInspectionPanel';
import { getConfigurationInspection } from '../infrastructure/api/configurationInspectionApi';

vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));
const directory = 'src/infrastructure/api/__fixtures__/equityActionActual/';
const digest = (raw: Uint8Array) => createHash('sha256').update(raw).digest('hex');
function captured() {
  const pins = JSON.parse(readFileSync(`${directory}capture-pins.json`, 'utf8'));
  const bytes = readFileSync(`${directory}response.json`);
  const manifestBytes = readFileSync(`${directory}manifest.json`);
  const indexBytes = readFileSync(`${directory}case-index.json`);
  expect(digest(bytes)).toBe(pins.response_sha256);
  expect(digest(manifestBytes)).toBe(pins.manifest_sha256);
  expect(digest(indexBytes)).toBe(pins.case_index_sha256);
  expect(pins.actual_model_invoked).toBe(true);
  expect(pins.source_closure_verified).toBe(true);
  expect(pins.owned_cleanup_verified).toBe(true);
  expect(pins.authentic_runtime_certification).toBe('unavailable');
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  const body = JSON.parse(bytes.toString('utf8'));
  expect(manifest.response.status).toBe(200);
  expect(manifest.response.body_sha256).toBe(digest(bytes));
  expect(body.publication.identity).toEqual(manifest.publication_identity);
  expect(body.publication.equity_run_consumption.schema_version).toBe('qt-equity-run-consumption/v2');
  const reads = body.publication.equity_run_consumption.stages.corporate_actions.reads;
  const frame = manifest.prior.reference.action_frame;
  for (const field of ['original_action_count', 'successor_action_count', 'original_action_digest', 'successor_action_digest']) {
    expect(reads[field]).toBe(frame[field]);
  }
  expect(reads.basis_frame_digest).toBe(manifest.prior.reference.action_frame_digest);
  expect(reads.effective_event_count).toBe(0);
  return { manifest, body, bytes, reads };
}
afterEach(cleanup);
describe('actual action-adjusted MODEL publication to HTTP and inspection', () => {
  beforeEach(() => vi.restoreAllMocks());
  it('accepts the exact actual response through production fetch and parser', async () => {
    const { manifest, bytes } = captured();
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(bytes, {
      status: 200, headers: { 'Content-Type': manifest.response.content_type },
    }));
    const parsed = await getConfigurationInspection(manifest.request.registry_id, manifest.request.portfolio_id);
    expect(parsed.status).toBe('available');
    expect(parsed.publication?.identity).toEqual(manifest.publication_identity);
    expect(String(fetch.mock.calls[0][0])).toContain(manifest.request.url);
  });
  it('shows recorded action counts and digests without implying reapplication', async () => {
    const { manifest, bytes, reads } = captured();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(bytes, {
      headers: { 'Content-Type': manifest.response.content_type },
    }));
    render(<ConfigurationInspectionPanel registryId={manifest.request.registry_id}
      portfolioId={manifest.request.portfolio_id} userId="synthetic-capture-reader" role="general_member" />);
    fireEvent.click(screen.getByRole('button', { name: /Published configuration/ }));
    const region = await screen.findByRole('region', { name: 'Equity settings recorded for this run' });
    fireEvent.click(within(region).getByRole('button', { name: /Show corporate actions observations/ }));
    expect(within(region).getByText('These actions were recorded in the proved prior and next MODEL seed. This MODEL run did not reapply them.')).toBeTruthy();
    for (const field of ['original_action_count', 'successor_action_count', 'original_action_digest', 'successor_action_digest', 'basis_frame_digest']) {
      expect(within(region).getByText(field).nextElementSibling?.textContent).toBe(String(reads[field]));
    }
    expect(screen.queryByRole('button', { name: /save|activate|approve|propose/i })).toBeNull();
  });
  it('blocks an altered action-field shape instead of displaying recorded success', async () => {
    const { manifest, body } = captured();
    delete body.publication.equity_run_consumption.stages.corporate_actions.reads.basis_frame_digest;
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(body), {
      headers: { 'Content-Type': manifest.response.content_type },
    }));
    render(<ConfigurationInspectionPanel registryId={manifest.request.registry_id}
      portfolioId={manifest.request.portfolio_id} userId="synthetic-capture-reader" role="general_member" />);
    fireEvent.click(screen.getByRole('button', { name: /Published configuration/ }));
    expect(await screen.findByText('Published configuration could not be loaded.')).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Equity settings recorded for this run' })).toBeNull();
  });
});

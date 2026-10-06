// Staged connected acceptance. Install only with the reviewed actual MR HTTP capture.
// @vitest-environment jsdom
import React from 'react';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfigurationInspectionPanel } from './ConfigurationInspectionPanel';
import { getConfigurationInspection } from '../infrastructure/api/configurationInspectionApi';

vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));

const directory = 'src/infrastructure/api/__fixtures__/equityModelFullRun/';
const digest = (bytes: Uint8Array) => createHash('sha256').update(bytes).digest('hex');
function captured() {
  // This index is created by root only after reviewing native/SQL/HTTP gate evidence.
  // A fixture label or self-declared hash alone is not acceptance of that evidence.
  const pins = JSON.parse(readFileSync(`${directory}capture-pins.json`, 'utf8'));
  const manifestBytes = readFileSync(`${directory}manifest.json`);
  const bytes = readFileSync(`${directory}response.json`);
  expect(digest(manifestBytes)).toBe(pins.manifest_sha256);
  expect(digest(bytes)).toBe(pins.response_sha256);
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  const body = JSON.parse(bytes.toString('utf8'));
  expect(manifest.artifact_schema_version).toBe(1);
  expect(manifest.evidence_scope).toBe('mean_reversion_full_run');
  expect(manifest.request.method).toBe('GET');
  expect(manifest.response.status).toBe(200);
  expect(manifest.response.body_path).toBe('response.json');
  expect(manifest.response.body_bytes).toBe(bytes.byteLength);
  expect(manifest.response.body_sha256).toBe(digest(bytes));
  expect(manifest.native).toEqual(pins.native);
  expect(body.scope).toEqual({ registry_id: manifest.request.registry_id, portfolio_id: manifest.request.portfolio_id });
  expect(body.publication.identity).toEqual(manifest.publication_identity);
  expect(body.publication.publication_schema_version).toBe(3);
  expect(body.publication.identity.publication_id).toBe(manifest.model_publication.publication_id);
  expect(body.publication.identity.portfolio_id).toBe(manifest.model_publication.portfolio_id);
  expect(body.publication.identity.run_date).toBe(manifest.model_publication.source_day);
  expect(body.publication.identity.engine_strategy_id).toBe('LIVE_EQUITY_MEAN_REVERSION');
  expect(body.publication.equity_run_consumption.available).toBe(true);
  expect(body.publication.equity_run_consumption.complete).toBe(true);
  return { manifest, body, bytes };
}

describe('actual equity MODEL publication to protected HTTP to frontend', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('accepts the exact captured protected response through the production fetch and parser', async () => {
    const { manifest, bytes } = captured();
    const fetch = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(bytes, {
      status: manifest.response.status, headers: { 'Content-Type': manifest.response.content_type },
    }));
    const response = await getConfigurationInspection(manifest.request.registry_id, manifest.request.portfolio_id);
    expect(response.status).toBe('available');
    expect(response.publication?.identity).toEqual(manifest.publication_identity);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(fetch.mock.calls[0][0])).toContain(manifest.request.url);
  });

  it('renders actual stage observations and exact accounting strings without mutation controls', async () => {
    const { manifest, body, bytes } = captured();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(bytes, {
      headers: { 'Content-Type': manifest.response.content_type },
    }));
    render(<ConfigurationInspectionPanel registryId={manifest.request.registry_id}
      portfolioId={manifest.request.portfolio_id} userId="synthetic-capture-reader" allowed />);
    fireEvent.click(screen.getByRole('button', { name: /Published configuration/ }));
    const region = await screen.findByRole('region', { name: 'Equity settings recorded for this run' });
    expect(within(region).getByText('Read coverage: complete')).toBeTruthy();
    expect(within(region).getAllByRole('heading', { level: 4 })).toHaveLength(10);
    fireEvent.click(within(region).getByRole('button', { name: /Show result assembly observations/ }));
    const values = body.publication.equity_run_consumption.stages.result_assembly.reads;
    for (const field of ['current_portfolio_value_exact', 'total_realized_pnl_exact',
      'total_unrealized_pnl_exact', 'total_transaction_costs_exact']) {
      const term = within(region).getByText(field);
      expect(term.nextElementSibling?.textContent).toBe(values[field]);
    }
    fireEvent.click(within(region).getByRole('button', { name: /Show primary observations/ }));
    expect(within(region).getByRole('region', { name: 'Strategy internal cost calls' })).toBeTruthy();
    expect(within(region).getByRole('region', { name: 'Compatibility internal cost calls' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /save|activate|approve|propose/i })).toBeNull();
  });

  it('refuses an altered publication identity instead of displaying the captured success', async () => {
    const { manifest, body } = captured();
    // Deliberate negative mutation of real captured bytes; not another native run.
    body.publication.identity.capture_id = '99999999-9999-4999-8999-999999999999';
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(body), {
      headers: { 'Content-Type': manifest.response.content_type },
    }));
    render(<ConfigurationInspectionPanel registryId={manifest.request.registry_id}
      portfolioId={manifest.request.portfolio_id} userId="synthetic-capture-reader" allowed />);
    fireEvent.click(screen.getByRole('button', { name: /Published configuration/ }));
    expect(await screen.findByText('Published configuration could not be loaded.')).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Equity settings recorded for this run' })).toBeNull();
  });
});

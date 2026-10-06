// @vitest-environment jsdom
import React from 'react';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConfigurationInspectionPanel } from './ConfigurationInspectionPanel';

vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));

const fixture = JSON.parse(readFileSync('../algolens-api/tests/fixtures/configuration_inspection_v1.json', 'utf8'));
const authenticatedHttpBody = readFileSync('src/infrastructure/api/__fixtures__/configurationInspectionHttp.json', 'utf8');
const completeV2HttpBody = readFileSync(
  'src/infrastructure/api/__fixtures__/configurationInspectionV2Http/publish_required_complete-5bcf79c0c445.http.json', 'utf8');
const v2FixtureDir = 'src/infrastructure/api/__fixtures__/configurationInspectionV2Http/';
const v2Index = JSON.parse(readFileSync(`${v2FixtureDir}index.json`, 'utf8')) as {
  responses: Array<{ stem: string; bytes: number; sha256: string; kind: string }>;
};
const capturedV2 = (stem: string, kind: string) => {
  const bytes = readFileSync(`${v2FixtureDir}${stem}.http.json`);
  const entry = v2Index.responses.find(row => row.stem === stem);
  expect(entry?.kind).toBe(kind);
  expect(bytes.byteLength).toBe(entry?.bytes);
  expect(createHash('sha256').update(bytes).digest('hex')).toBe(entry?.sha256);
  return new Response(bytes, { headers: { 'Content-Type': 'application/json' } });
};
const reply = (book = 'BOOK', status: 'available' | 'unavailable' = 'available') => new Response(JSON.stringify({
  api_version: 1, scope: { registry_id: 'trend', portfolio_id: book },
  read_at: '2026-09-22T15:02:00Z', status,
  reason: status === 'available' ? 'none' : 'not_published',
  publication: status === 'available'
    ? { ...fixture, identity: { ...fixture.identity, portfolio_id: book } } : null,
}), { headers: { 'Content-Type': 'application/json' } });
const panel = (book = 'BOOK', userId = 'u1', allowed = true) =>
  <ConfigurationInspectionPanel registryId="trend" portfolioId={book} userId={userId} allowed={allowed} />;
const openPublishedConfiguration = () =>
  fireEvent.click(screen.getByRole('button', { name: /Published configuration/ }));

describe('read-only published configuration panel', () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it('starts collapsed and opens the published configuration from its disclosure control', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    render(panel());

    const disclosure = screen.getByRole('button', { name: /Published configuration/ });
    expect(disclosure.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByRole('button', { name: 'Refresh published configuration' })).toBeNull();

    fireEvent.click(disclosure);

    expect(disclosure.getAttribute('aria-expanded')).toBe('true');
    expect(await screen.findByText('synthetic.test-1')).toBeTruthy();
  });

  it.each(['available', 'unavailable'])('binds the synthetic equity %s response through the real HTTP parser and panel', async status => {
    const bytes = readFileSync(`../contracts/equity-inspection-v3-synthetic-${status}.json`, 'utf8');
    const sample = JSON.parse(bytes);
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(bytes, { headers: { 'Content-Type': 'application/json' } }));
    render(<ConfigurationInspectionPanel registryId={sample.scope.registry_id} portfolioId={sample.scope.portfolio_id} userId="u1" allowed />);
    openPublishedConfiguration();
    const region = await screen.findByRole('region', { name: 'Equity settings recorded for this run' });
    expect(within(region).getByText(`Read coverage: ${status === 'available' ? 'complete' : 'unavailable'}`)).toBeTruthy();
    expect(within(region).getAllByRole('heading', { level: 4 })).toHaveLength(10);
    expect(screen.queryByRole('table', { name: 'Supplied inputs' })).toBeNull();
  });

  it('shows actual recorded use from a validated v2 HTTP publication', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(completeV2HttpBody, {
      headers: { 'Content-Type': 'application/json' },
    }));
    render(panel());
    openPublishedConfiguration();
    expect(await screen.findByText('local-test')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Settings actually used' })).toBeTruthy();
  });

  it.each([
    ['publish_required_complete-5bcf79c0c445', 'available', 'complete', 'none', 'Uncontrolled publication', 16],
    ['publish_required_complete_controlled-0e2623f596ae', 'available', 'complete', 'none', 'Controlled publication', 18],
    ['publish_required_partial-0a62072ce366', 'available', 'partial', 'nonfatal_error', 'Uncontrolled publication', 16],
    ['publish_required_partial_controlled-e2aa4e09194b', 'available', 'partial', 'nonfatal_error', 'Controlled publication', 18],
    ['publish_required_unavailable-8568faf3d85d', 'available', 'unavailable', 'instrumentation_missing', 'Uncontrolled publication', 0],
    ['publish_required_unavailable_controlled-94e729d78eab', 'available', 'unavailable', 'instrumentation_missing', 'Controlled publication', 0],
    ['publish_required_bad_capture_complete-cacaaeacf2f5', 'unavailable', 'complete', 'none', 'Uncontrolled publication', 16],
    ['publish_required_bad_capture_complete_controlled-b5b8278979fe', 'unavailable', 'complete', 'none', 'Controlled publication', 18],
    ['publish_required_early_unavailable_complete-d5324353f082', 'unavailable', 'complete', 'none', 'Uncontrolled publication', 16],
    ['publish_required_early_unavailable_complete_controlled-5a257484e45c', 'unavailable', 'complete', 'none', 'Controlled publication', 18],
  ] as const)('renders captured v2 %s with its own capture and consumption outcomes', async (
    stem, captureStatus, status, reason, control, nodeCount,
  ) => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(capturedV2(stem, 'generated'));
    render(panel());
    openPublishedConfiguration();
    expect(await screen.findByText('local-test')).toBeTruthy();
    const used = screen.getByRole('region', { name: 'Settings actually used' });
    expect(within(used).getByText(`Coverage: ${status}; reason: ${reason}`)).toBeTruthy();
    expect(screen.getByText(control)).toBeTruthy();
    expect(within(used).getByText(`Recorded observations: ${nodeCount}`)).toBeTruthy();
    expect(within(used).getAllByRole('heading', { level: 4 })).toHaveLength(8);
    if (status === 'complete') expect(within(used).getAllByRole('heading', { level: 4 })
      .every(heading => heading.textContent?.includes('complete (reason: none)'))).toBe(true);
    if (status === 'partial') expect(within(used).getByRole('heading', {
      name: /control flow observations — partial \(reason: nonfatal_error\)/,
    })).toBeTruthy();
    if (status === 'unavailable') expect(within(used).getAllByRole('heading', { level: 4 })
      .every(heading => heading.textContent?.includes('unavailable (reason: instrumentation_missing)'))).toBe(true);
    expect(screen.queryByText(/Consumption not collected/)).toBeNull();
    if (captureStatus === 'unavailable') {
      expect(screen.getByText(/Configuration capture was unavailable|Supplied configuration inspection was unavailable/)).toBeTruthy();
      expect(screen.queryByRole('table', { name: 'Supplied inputs' })).toBeNull();
    } else {
      expect(screen.getByRole('table', { name: 'Supplied inputs' })).toBeTruthy();
    }
    if (nodeCount === 0) expect(within(used).getByText(/No setting reads were recorded because consumption evidence is unavailable/)).toBeTruthy();
    else {
      fireEvent.click(within(used).getByRole('button', { name: /Show setup observations/ }));
      fireEvent.click(within(used).getByRole('button', { name: /Observation #2: setup.selection_entry/ }));
      expect(within(used).getByRole('rowheader', { name: 'setup.selection.enabled_live' }).closest('tr')?.textContent)
        .toContain('trueboolconfigured_strategy_leaf');
    }
  });

  it.each([
    ['mutation-malformed-newest-publish_required_complete-5bcf79c0c445', 'This publication could not be inspected.'],
    ['mutation-malformed-newest-publish_required_bad_capture_complete_controlled-b5b8278979fe', 'This publication could not be inspected.'],
    ['mutation-mismatched-attempt', 'This publication could not be inspected.'],
    ['mutation-scope-changed', 'This publication no longer matches the selected scope.'],
  ] as const)('refuses captured synthetic negative %s without stale evidence', async (stem, message) => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(capturedV2(stem, 'synthetic-negative-mutation'));
    render(panel());
    openPublishedConfiguration();
    expect(await screen.findByText(message)).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Settings actually used' })).toBeNull();
    expect(screen.queryByText('local-test')).toBeNull();
  });

  it('clears v2 expansion on refresh, an invalid publication, and role loss', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(async () => capturedV2('publish_required_complete-5bcf79c0c445', 'generated'))
      .mockImplementationOnce(async () => capturedV2('mutation-mismatched-attempt', 'synthetic-negative-mutation'));
    const view = render(panel());
    openPublishedConfiguration();
    await screen.findByRole('region', { name: 'Settings actually used' });
    fireEvent.click(screen.getByRole('button', { name: /Show setup observations/ }));
    expect(screen.getByRole('button', { name: /Observation #0: setup.selector/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Refresh published configuration' }));
    expect(screen.queryByRole('region', { name: 'Settings actually used' })).toBeNull();
    expect(await screen.findByText('This publication could not be inspected.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Observation #0: setup.selector/ })).toBeNull();
    view.rerender(panel('BOOK', 'u1', false));
    expect(screen.queryByRole('region', { name: 'Settings actually used' })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('drops expanded v2 evidence immediately when book or user identity changes', async () => {
    let release: ((response: Response) => void) | undefined;
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(async () => capturedV2('publish_required_complete-5bcf79c0c445', 'generated'))
      .mockImplementationOnce(() => new Promise<Response>(resolve => { release = resolve; }))
      .mockImplementationOnce(async () => capturedV2('publish_required_complete-5bcf79c0c445', 'generated'));
    const view = render(panel());
    openPublishedConfiguration();
    await screen.findByRole('region', { name: 'Settings actually used' });
    fireEvent.click(screen.getByRole('button', { name: /Show setup observations/ }));
    expect(screen.getByRole('button', { name: /Observation #0: setup.selector/ })).toBeTruthy();
    view.rerender(panel('OTHER'));
    expect(screen.queryByRole('region', { name: 'Settings actually used' })).toBeNull();
    view.rerender(panel('BOOK', 'u2'));
    release?.(capturedV2('publish_required_complete-5bcf79c0c445', 'generated'));
    openPublishedConfiguration();
    await screen.findByRole('region', { name: 'Settings actually used' });
    expect(screen.queryByRole('button', { name: /Observation #0: setup.selector/ })).toBeNull();
    expect(screen.getByRole('button', { name: /Show setup observations/ }).getAttribute('aria-expanded')).toBe('false');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('aborts a pending v2 observation when the panel unmounts', () => {
    let requestSignal: AbortSignal | undefined;
    let release: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, 'fetch').mockImplementation((_url, init) => {
      requestSignal = init?.signal ?? undefined;
      return new Promise<Response>(resolve => { release = resolve; });
    });
    const view = render(panel());
    openPublishedConfiguration();
    expect(screen.getByText(/Loading published configuration/)).toBeTruthy();
    view.unmount();
    expect(requestSignal?.aborted).toBe(true);
    release?.(capturedV2('publish_required_complete-5bcf79c0c445', 'generated'));
    expect(screen.queryByRole('region', { name: 'Settings actually used' })).toBeNull();
  });

  it('renders the exact authenticated C++ to SQL to API HTTP publication without edit actions', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(authenticatedHttpBody, {
      headers: { 'Content-Type': 'application/json' },
    }));
    render(panel());
    openPublishedConfiguration();
    expect(await screen.findByText('local-test')).toBeTruthy();
    expect(screen.getByRole('table', { name: 'Supplied inputs' }).querySelectorAll('tbody tr')).toHaveLength(57);
    expect(screen.getByText(/#1 TREND/)).toBeTruthy();
    expect(screen.getByRole('table', { name: 'Factory-resolved trend inputs' })).toBeTruthy();
    expect(screen.getByRole('table', { name: 'Constructor-normalized trend inputs' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /save|activate|approve|propose/i })).toBeNull();
  });

  it('shows publication context, all supplied states, distinct stages and no mutation controls', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    render(panel());
    openPublishedConfiguration();
    expect(await screen.findByText('synthetic.test-1')).toBeTruthy();
    expect(screen.getByText(/Run date: 2026-09-22/)).toBeTruthy();
    expect(screen.getByText(/Controlled publication/)).toBeTruthy();
    expect(screen.getByText(/Consumption not collected/)).toBeTruthy();
    expect(screen.getByText(/2026-09-22T15:00:00Z/)).toBeTruthy();
    expect(screen.getByText(/2026-09-22T15:01:00Z/)).toBeTruthy();
    expect(screen.getByText(/Observation age/)).toBeTruthy();
    expect(screen.getByRole('table', { name: 'Supplied inputs' }).textContent).toContain('absent_in_input');
    expect(screen.getByRole('table', { name: 'Supplied inputs' }).textContent).toContain('omitted');
    expect(screen.getByRole('table', { name: 'Supplied inputs' }).textContent).toContain('unsupported_in_profile');
    expect(screen.getByRole('table', { name: 'Factory-resolved trend inputs' }).textContent).toContain('60');
    expect(screen.getByRole('table', { name: 'Constructor-normalized trend inputs' }).textContent).toContain('64');
    expect(screen.queryByRole('button', { name: /save|activate|approve|propose/i })).toBeNull();
  });

  it('offers keyboard-focusable named scrolling regions with intact table headers', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    render(panel());
    openPublishedConfiguration();
    await screen.findByText('synthetic.test-1');
    const names = ['Supplied inputs', 'Factory-resolved trend inputs', 'Constructor-normalized trend inputs'];
    for (const name of names) {
      const region = screen.getByRole('region', { name: `${name} table` });
      expect(region.tabIndex).toBe(0);
      region.focus();
      expect(document.activeElement).toBe(region);
      const table = within(region).getByRole('table', { name });
      expect(within(table).getAllByRole('columnheader').length).toBeGreaterThan(0);
      expect(within(table).getAllByRole('rowheader').length).toBeGreaterThan(0);
    }
  });

  it('uses singular age grammar for one captured day', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-09-23T15:00:00Z'));
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(reply());
    render(panel());
    openPublishedConfiguration();
    expect(await screen.findByText(/Observation age: 1 day\./)).toBeTruthy();
  });

  it('clears old values immediately on book and user changes, ignoring late responses', async () => {
    let release: ((response: Response) => void) | undefined;
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(reply())
      .mockImplementationOnce(() => new Promise<Response>(resolve => { release = resolve; }))
      .mockResolvedValueOnce(reply('BOOK'));
    const view = render(panel());
    openPublishedConfiguration();
    await screen.findByText('synthetic.test-1');
    view.rerender(panel('OTHER'));
    expect(screen.queryByText('synthetic.test-1')).toBeNull();
    expect(screen.getByText('Registry: trend')).toBeTruthy();
    expect(screen.getByText('Book: OTHER')).toBeTruthy();
    view.rerender(panel('BOOK', 'u2'));
    expect(screen.queryByText('synthetic.test-1')).toBeNull();
    release?.(reply('OTHER'));
    openPublishedConfiguration();
    await screen.findByText('synthetic.test-1');
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('clears a successful observation on refresh, unavailable result, error and role loss', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(reply())
      .mockResolvedValueOnce(reply('BOOK', 'unavailable'))
      .mockResolvedValueOnce(new Response('PRIVATE-SECRET', { status: 503 }));
    const view = render(panel());
    openPublishedConfiguration();
    await screen.findByText('synthetic.test-1');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh published configuration' }));
    expect(screen.queryByText('synthetic.test-1')).toBeNull();
    await screen.findByText(/No published configuration/);
    fireEvent.click(screen.getByRole('button', { name: 'Refresh published configuration' }));
    await screen.findByText(/could not be loaded/i);
    expect(screen.queryByText('PRIVATE-SECRET')).toBeNull();
    view.rerender(panel('BOOK', 'u1', false));
    expect(screen.queryByText(/Published configuration/)).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('keeps dated publication context visible when capture was unavailable', async () => {
    const unavailableCapture = { ...fixture, status: 'unavailable', reason: 'capture_failed',
      supplied: null, selected_trend: null };
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      api_version: 1, scope: { registry_id: 'trend', portfolio_id: 'BOOK' },
      read_at: '2026-09-22T15:02:00Z', status: 'unavailable',
      reason: 'capture_failed', publication: unavailableCapture,
    }), { headers: { 'Content-Type': 'application/json' } }));
    render(panel());
    openPublishedConfiguration();
    expect(await screen.findByText(/Configuration capture was unavailable/)).toBeTruthy();
    expect(screen.getByText('synthetic.test-1')).toBeTruthy();
    expect(screen.getByText(/Run date: 2026-09-22/)).toBeTruthy();
    expect(screen.queryByRole('table', { name: 'Supplied inputs' })).toBeNull();
  });
});

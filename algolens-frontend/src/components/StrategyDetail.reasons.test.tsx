// @vitest-environment jsdom
//
// The disabled "Edit positions" button used to show the backend's raw workflow
// state ("workflow_unavailable") as its reason. It now shows a plain sentence
// that says what is wrong and what to do; unknown reasons still pass through.

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { StrategyDetail } from './StrategyDetail';
import type { Strategy } from '../domain/portfolio/portfolioData';
import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtProposal, type QtProposal } from '../domain/portfolio/qtPreview';

const qtApi = vi.hoisted(() => ({ getProposal: vi.fn() }));
vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(), QtPreviewApi: qtApi,
}));
vi.mock('./QtProposalWorkspace', () => ({
  QtProposalWorkspace: () => <section aria-label="QT proposal workspace" />,
}));
vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));
vi.mock('../adapters/react/useAuth', () => ({
  useAuth: () => ({ user: { id: '101', role: 'admin' } }),
}));
vi.mock('./FinancialAnalysis', () => ({ FinancialAnalysis: () => null }));
vi.mock('./TradingActivity', () => ({ TradingActivity: () => null }));
vi.mock('./AlphaAttribution', () => ({ AlphaAttribution: () => null }));
vi.mock('./OverrideHistory', () => ({ OverrideHistory: () => null }));
vi.mock('./ConfigurationInspectionPanel', () => ({ ConfigurationInspectionPanel: () => null }));
vi.mock('recharts', () => {
  const Stub = () => null;
  return { LineChart: Stub, Line: Stub, XAxis: Stub, YAxis: Stub, Tooltip: Stub, ResponsiveContainer: Stub };
});

type Impl = (id: string, book?: string, stream?: 'system' | 'qt') => Promise<Strategy>;
let getStrategyImpl: Impl = async () => { throw new Error('getStrategy not set'); };
vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: {
    getStrategy: (id: string, book?: string, stream?: 'system' | 'qt') => getStrategyImpl(id, book, stream),
    getPositionOverrides: async () => [],
    savePosition: async () => ({ outcome: 'saved' as const }),
  },
}));

const READ_ONLY = 'Model/system positions are read-only. Select QT to edit its current snapshot.';
const WORKFLOW_UNAVAILABLE_TEXT =
  'QT editing is not turned on for this book yet, so its positions cannot be changed here. '
  + 'Ask an admin to enable the QT desk workflow for this book. Position changes are disabled.';
const PROVENANCE_TEXT =
  'This book has no verified MODEL source for the selected day yet, so QT cannot propose or edit quantities. '
  + 'Position changes are disabled.';

function strategy(over: Partial<Strategy> = {}): Strategy {
  return {
    id: 'trendfollowing', name: 'Trend Following', description: 'Systematic trend following',
    invested: 500000, currentValue: 523681.65, return: 23681.65, returnPercent: 4.74,
    positions: [{ symbol: 'ES.v.0', name: 'ES', shares: 5, quantity: 5, quantity_exact: '5', costBasis: 100,
      average_price_exact: '100', marketPrice: null, notional: null, currentValue: null, strategyName: 'Engine A' }],
    positionStream: 'system', positionStrategyNames: ['Engine A'], positionDate: '2026-09-23',
    positionsEditable: false, historicalData: [], bestDay: null, worstDay: null, metrics: {},
    executions: [], finalizedPositions: [], activityStream: 'qt', finalizedPositionsAvailable: true,
    managers: [], lastUpdate: '2026-09-15', portfolio_id: 'CONSERVATIVE_PORTFOLIO',
    books: ['CONSERVATIVE_PORTFOLIO'], ...over,
  } as unknown as Strategy;
}
function unavailableProposal(state: string, reason: string | null): QtProposal {
  const raw = structuredClone(fixtures.proposal_ready);
  raw.book_id = 'CONSERVATIVE_PORTFOLIO'; raw.source_day = '2026-09-23';
  raw.capability.required = true;
  raw.seed_rows.forEach(row => { row.key.portfolio_id = 'CONSERVATIVE_PORTFOLIO'; row.key.date = '2026-09-23'; });
  const decoded = decodeQtProposal(raw);
  decoded.capability.available = false;
  decoded.workflow_state = state as QtProposal['workflow_state'];
  decoded.read_only_reason = reason;
  return decoded;
}

const editButton = () => screen.getByRole('button', { name: 'Edit positions' }) as HTMLButtonElement;
function describedBy(button: HTMLElement): string {
  const ids = (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
  return ids.map(id => document.getElementById(id)?.textContent ?? '').join(' ').trim();
}
async function openOnQtWith(reply: () => Promise<QtProposal>) {
  qtApi.getProposal.mockImplementation(reply);
  render(<StrategyDetail strategy={strategy()} onBack={() => {}} />);
  await screen.findByText(/Model \/ System positions snapshot/i);
  fireEvent.change(screen.getByRole('combobox', { name: 'Position stream' }), { target: { value: 'qt' } });
  await screen.findByText(/QT positions snapshot/i);
  return screen.findByRole('status', { name: 'QT workflow availability' });
}

beforeEach(() => {
  sessionStorage.clear();
  qtApi.getProposal.mockReset();
  getStrategyImpl = async (_id, book, stream) => stream === 'qt'
    ? strategy({ portfolio_id: book, positionStream: 'qt' })
    : strategy({ portfolio_id: book, positionStream: 'system', positionEditUnavailableReason: READ_ONLY });
});
afterEach(() => sessionStorage.clear());

describe('the disabled Edit positions button explains itself in plain words', () => {
  it('shows the plain sentence, not the raw code, for workflow_unavailable', async () => {
    const status = await openOnQtWith(async () => unavailableProposal('workflow_unavailable', 'workflow_unavailable'));
    expect(status.textContent?.trim()).toBe(WORKFLOW_UNAVAILABLE_TEXT);
    const button = editButton();
    expect(button.disabled).toBe(true);
    expect(describedBy(button)).toBe(WORKFLOW_UNAVAILABLE_TEXT);
    expect(screen.queryByText('workflow_unavailable')).toBeNull();
    expect(document.body.textContent ?? '').not.toContain('workflow_unavailable');
    expect(screen.queryByRole('region', { name: 'QT proposal workspace' })).toBeNull();
  });

  it('shows the plain sentence for provenance_unresolved', async () => {
    const status = await openOnQtWith(async () => unavailableProposal('provenance_unresolved', 'provenance_unresolved'));
    expect(status.textContent?.trim()).toBe(PROVENANCE_TEXT);
    expect(describedBy(editButton())).toBe(PROVENANCE_TEXT);
    expect(document.body.textContent ?? '').not.toContain('provenance_unresolved');
  });

  it('keeps an unknown backend reason exactly as sent', async () => {
    const status = await openOnQtWith(async () => unavailableProposal('workflow_unavailable', 'Synthetic workflow unavailable'));
    expect(status.textContent?.trim()).toBe('Synthetic workflow unavailable');
    expect(describedBy(editButton())).toBe('Synthetic workflow unavailable');
  });

  it('uses the generic sentence when the backend gives no reason', async () => {
    const status = await openOnQtWith(async () => unavailableProposal('workflow_unavailable', null));
    expect(status.textContent?.trim()).toBe('QT workflow is unavailable. Position changes are disabled.');
    expect(editButton().disabled).toBe(true);
  });

  it('keeps the capability-request-failed sentence unchanged', async () => {
    const status = await openOnQtWith(async () => { throw new Error('synthetic failure'); });
    expect(status.textContent?.trim()).toBe('QT workflow capability is unavailable. Position changes are disabled.');
  });
});

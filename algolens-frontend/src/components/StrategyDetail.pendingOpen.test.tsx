// @vitest-environment jsdom
//
// A request to open the QT editing window must not outlive the moment that made
// it. "Edit positions" on Model / System selects QT and remembers the request
// until the QT workspace can mount. If the QT snapshot that arrives is NOT a QT
// snapshot (its stream is unknown), the workspace can never mount for it, so the
// request has to be dropped there and then. Left alive, it survived leaving the
// strategy and coming back, and the window then opened by itself, unasked, as
// soon as the workflow became available.

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { StrategyDetail } from './StrategyDetail';
import type { Strategy } from '../domain/portfolio/portfolioData';
import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtProposal, type QtProposal } from '../domain/portfolio/qtPreview';

const qtApi = vi.hoisted(() => ({ getProposal: vi.fn() }));
vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(), QtPreviewApi: qtApi,
}));
let mountCount = 0;
vi.mock('./QtProposalWorkspace', () => ({
  QtProposalWorkspace: (p: { actorId: string; bookId: string; sourceDay: string; embedded?: boolean; onPublished: () => void }) => {
    React.useEffect(() => { mountCount += 1; }, []);
    return <section aria-label="QT proposal workspace">
      <div data-testid="qt-workspace-context">{p.actorId}:{p.bookId}:{p.sourceDay}</div>
      <input aria-label="Chosen quantity ES.v.0" defaultValue="5" />
      <button type="button" onClick={p.onPublished}>Simulate publish</button>
    </section>;
  },
}));
vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));
let role = 'admin';
let userId = '101';
vi.mock('../adapters/react/useAuth', () => ({
  useAuth: () => ({ user: { id: userId, role } }),
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
const getStrategyCalls: unknown[][] = [];
vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: {
    getStrategy: (id: string, book?: string, stream?: 'system' | 'qt') => {
      getStrategyCalls.push([id, book, stream]);
      return getStrategyImpl(id, book, stream);
    },
    getPositionOverrides: async () => [],
    savePosition: async () => ({ outcome: 'saved' as const }),
  },
}));

const READ_ONLY = 'Model/system positions are read-only. Select QT to edit its current snapshot.';

function strategy(id: string, over: Partial<Strategy> = {}): Strategy {
  return {
    id, name: `Strategy ${id}`, description: 'Synthetic strategy',
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
function proposal(): QtProposal {
  const raw = structuredClone(fixtures.proposal_ready);
  raw.book_id = 'CONSERVATIVE_PORTFOLIO'; raw.source_day = '2026-09-23'; raw.capability.required = true;
  raw.seed_rows.forEach(row => { row.key.portfolio_id = 'CONSERVATIVE_PORTFOLIO'; row.key.date = '2026-09-23'; });
  return decodeQtProposal(raw);
}

const editButton = () => screen.queryByRole('button', { name: 'Edit positions' }) as HTMLButtonElement | null;
const editorWindow = () => screen.queryByRole('dialog');

beforeEach(() => {
  sessionStorage.clear();
  role = 'admin'; userId = '101';
  getStrategyCalls.length = 0;
  qtApi.getProposal.mockReset();
  qtApi.getProposal.mockResolvedValue(proposal());
});
afterEach(() => sessionStorage.clear());

describe('the pending request to open the editing window', () => {
  it('is dropped when the QT request returns a snapshot of unknown stream, and never revives', async () => {
    let qtRequestsForA = 0;
    getStrategyImpl = async (id, book, stream) => {
      if (id !== 'strategy-a') return strategy(id, { portfolio_id: book, positionStream: 'system', positionEditUnavailableReason: READ_ONLY });
      if (stream !== 'qt') return strategy(id, { portfolio_id: book, positionStream: 'system', positionEditUnavailableReason: READ_ONLY });
      qtRequestsForA += 1;
      // The first QT answer proves no stream at all; the second is a proper QT snapshot.
      return strategy(id, { portfolio_id: book, positionStream: qtRequestsForA === 1 ? null : 'qt' });
    };
    const view = render(<StrategyDetail strategy={strategy('strategy-a')} onBack={() => {}} />);
    await screen.findByText(/Model \/ System positions snapshot/i);
    fireEvent.click(editButton()!);
    await waitFor(() => expect(qtRequestsForA).toBe(1));
    await waitFor(() => expect(getStrategyCalls.some(call => call[0] === 'strategy-a' && call[2] === 'qt')).toBe(true));
    // Nothing mounts for a snapshot without a proven QT stream: no window.
    await waitFor(() => expect(screen.queryByText(/Loading/i)).toBeNull());
    expect(editorWindow()).toBeNull();

    // Leave the strategy, then come back to it: it is on QT again, now with a real QT snapshot.
    view.rerender(<StrategyDetail strategy={strategy('strategy-b')} onBack={() => {}} />);
    await screen.findByText(/Model \/ System positions snapshot/i);
    view.rerender(<StrategyDetail strategy={strategy('strategy-a')} onBack={() => {}} />);
    await screen.findByText(/QT positions snapshot/i);
    await waitFor(() => expect(qtRequestsForA).toBe(2));
    await waitFor(() => expect(editButton()!.disabled).toBe(false));
    // The workflow is available now; the old request must not open the window.
    await new Promise(resolve => setTimeout(resolve, 50));
    expect(editorWindow()).toBeNull();
    expect(mountCount).toBe(0);
  });
});

// @vitest-environment jsdom
//
// The QT editing window on a strategy page that shares its book. A book has one
// MODEL owner per day; the other strategies' saved QT rows are locked context.
// Someone opening the window from the Carry page saw Carry's rows locked and only
// the owners' rows editable, with no word about why. The page now tells the
// workspace which strategy the reader is on, and the workspace explains it.
// The real workspace is used here; only the network layer is stubbed.

import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { StrategyDetail } from './StrategyDetail';
import type { Strategy } from '../domain/portfolio/portfolioData';
import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtDraft, decodeQtProposal } from '../domain/portfolio/qtPreview';

const qtApi = vi.hoisted(() => ({ getProposal: vi.fn(), getDraft: vi.fn(), getBookDecision: vi.fn() }));
vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(), QtPreviewApi: qtApi,
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


const BOOK = 'CONSERVATIVE_PORTFOLIO';
const DAY = '2026-09-23';
const WINDOW = `Edit QT positions - ${BOOK}`;

function strategy(name: string, id: string): Strategy {
  return {
    id, name, description: 'Synthetic strategy',
    invested: 500000, currentValue: 523681.65, return: 23681.65, returnPercent: 4.74,
    positions: [{ symbol: 'ES.v.0', name: 'ES', shares: 5, quantity: 5, quantity_exact: '5', costBasis: 100,
      average_price_exact: '100', marketPrice: null, notional: null, currentValue: null, strategyName: 'Engine A' }],
    positionStream: 'system', positionStrategyNames: ['Engine A'], positionDate: DAY,
    positionsEditable: false, historicalData: [], bestDay: null, worstDay: null, metrics: {},
    executions: [], finalizedPositions: [], activityStream: 'qt', finalizedPositionsAvailable: true,
    managers: [], lastUpdate: '2026-09-15', portfolio_id: BOOK, books: [BOOK],
  } as unknown as Strategy;
}
function row(name: string, symbol: string, editable: boolean, origin: string) {
  return { key: { portfolio_id: BOOK, strategy_id: `id-${name}-${symbol}`, strategy_name: name, date: DAY,
    symbol, portfolio_type: editable ? 'qt_proposal' : 'qt' },
  quantity_exact: '3', basis_status: 'preserved_source', average_price_exact: '100', asset_type: 'EQUITY',
  editable, origin };
}
/** [strategy, symbol, editable] rows the workflow serves for the shared book. */
function serveWorkflow(rows: Array<[string, string, boolean]>) {
  const proposalRaw = { ...structuredClone(fixtures.proposal_ready), book_id: BOOK, source_day: DAY,
    seed_rows: rows.filter(r => r[2]).map(r => row(r[0], r[1], true, 'verified_model_seed')),
    saved_qt_rows: rows.filter(r => !r[2]).map(r => row(r[0], r[1], false, 'immutable')) };
  proposalRaw.capability.required = true;
  qtApi.getProposal.mockResolvedValue(decodeQtProposal(proposalRaw));
  qtApi.getDraft.mockResolvedValue(decodeQtDraft({ ...structuredClone(fixtures.draft_saved), book_id: BOOK, source_day: DAY,
    selection_rows: rows.map(r => row(r[0], r[1], r[2], r[2] ? 'qt_draft' : 'immutable')) }));
  qtApi.getBookDecision.mockResolvedValue({ schema_version: 'qt-workflow/v1', book_id: BOOK, source_day: DAY,
    decision: null, preview: null });
}
const carryRows: Array<[string, string, boolean]> = [['Carry', '6E', false], ['Carry', 'ZN', false], ['Carry', 'ZS', false],
  ['Trend Following', 'ES', true], ['Mean Reversion', 'NQ', true]];

async function openWindowFor(name: string, id: string) {
  getStrategyImpl = async (_id, book, stream) => ({ ...strategy(name, id), portfolio_id: book, positionStream: stream ?? 'system',
    ...(stream === 'qt' ? {} : { positionEditUnavailableReason: 'Model/system positions are read-only.' }) }) as Strategy;
  render(<StrategyDetail strategy={strategy(name, id)} onBack={() => {}} />);
  await screen.findByText(/Model \/ System positions snapshot/i);
  fireEvent.click(screen.getByRole('button', { name: 'Edit positions' }));
  const dialog = await screen.findByRole('dialog', { name: WINDOW });
  await within(dialog).findByRole('table', { name: 'QT component quantities' });
  await waitFor(() => expect(qtApi.getDraft).toHaveBeenCalled());
  return dialog;
}

beforeEach(() => {
  sessionStorage.clear();
  role = 'admin'; userId = '101';
  getStrategyCalls.length = 0;
  qtApi.getProposal.mockReset(); qtApi.getDraft.mockReset(); qtApi.getBookDecision.mockReset();
});
afterEach(() => sessionStorage.clear());

describe('the page tells the editing window which strategy the reader is on', () => {
  it('explains the locked rows in the window opened from the Carry page', async () => {
    serveWorkflow(carryRows);
    const dialog = await openWindowFor('Carry', 'carry');
    const note = await within(dialog).findByRole('note');
    expect(note.textContent).toBe("Carry cannot be changed in this window: this book's QT desk feed comes from " +
      "Trend Following and Mean Reversion, so Carry's positions are shown as locked holdings. " +
      "You can change Trend Following and Mean Reversion's quantities here.");
  });

  it('shows no such note in the window opened from a strategy whose rows are editable', async () => {
    serveWorkflow(carryRows);
    const dialog = await openWindowFor('Trend Following', 'trendfollowing');
    await within(dialog).findByRole('textbox', { name: /^Chosen quantity for Trend Following / });
    expect(within(dialog).queryByRole('note')).toBeNull();
  });
});

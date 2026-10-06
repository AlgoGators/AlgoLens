// @vitest-environment jsdom
//
// Closing the QT editing window puts the reader back on "Edit positions".
//
// From the QT view the button that opened the window is still on the page, so
// focus returns to it. From Model / System the click first switches the stream,
// which re-renders the button away; the window then has no opener to return to,
// so it asks the page for the button by its data-qt-edit-entry marker. Without
// that, focus was left on the page body (or on a box inside the hidden window).

import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  useAuth: () => ({ user: { id: userId, role, capabilities:
    role === 'admin' || role === 'general_member' ? ['view_internal', 'view_qt_platform', 'edit_qt_book'] : [] } }),
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
const NEW_SENTENCE = 'These are the saved QT positions. Use Edit positions to change a quantity: you will review, save, evaluate and confirm it in a window.';
const WINDOW = 'Edit QT positions - CONSERVATIVE_PORTFOLIO';

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
/** What the API serves: MODEL says it is read-only; QT is editable only if the test says so. */
function serve(qt: Partial<Strategy> = {}) {
  getStrategyImpl = async (_id, book, stream) => stream === 'qt'
    ? strategy({ portfolio_id: book, positionStream: 'qt', ...qt })
    : strategy({ portfolio_id: book, positionStream: 'system', positionEditUnavailableReason: READ_ONLY });
}
function proposal(required: boolean, available = true, reason: string | null = null,
  book = 'CONSERVATIVE_PORTFOLIO'): QtProposal {
  const raw = structuredClone(fixtures.proposal_ready);
  raw.book_id = book; raw.source_day = '2026-09-23';
  raw.capability.required = required;
  raw.seed_rows.forEach(row => { row.key.portfolio_id = book; row.key.date = '2026-09-23'; });
  const decoded = decodeQtProposal(raw);
  if (!available) { decoded.capability.available = false; decoded.workflow_state = 'workflow_unavailable'; decoded.read_only_reason = reason; }
  return decoded;
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}

const editButton = () => screen.queryByRole('button', { name: 'Edit positions' }) as HTMLButtonElement | null;
const streamBox = () => screen.getByRole('combobox', { name: 'Position stream' }) as HTMLSelectElement;
const editorWindow = () => screen.queryByRole('dialog');
const quantityBox = () => screen.queryByLabelText('Chosen quantity ES.v.0') as HTMLInputElement | null;
async function enabledButton() {
  await waitFor(() => expect(editButton()!.disabled).toBe(false));
  return editButton()!;
}
function describedBy(button: HTMLElement): string {
  const ids = (button.getAttribute('aria-describedby') ?? '').split(/\s+/).filter(Boolean);
  return ids.map(id => document.getElementById(id)?.textContent ?? '').join(' ').trim();
}
async function openOnSystem() {
  render(<StrategyDetail strategy={strategy()} onBack={() => {}} />);
  await screen.findByText(/Model \/ System positions snapshot/i);
}
async function openOnQt() {
  await openOnSystem();
  fireEvent.change(streamBox(), { target: { value: 'qt' } });
  await screen.findByText(/QT positions snapshot/i);
}

beforeEach(() => {
  sessionStorage.clear();
  role = 'admin'; userId = '101';
  getStrategyCalls.length = 0;
  qtApi.getProposal.mockReset();
  qtApi.getProposal.mockResolvedValue(proposal(true));
  serve();
});
afterEach(() => sessionStorage.clear());

describe('closing the QT editing window restores focus', () => {
  it('returns to the Edit positions button when it was opened from the QT view', async () => {
    await openOnQt();
    const button = await enabledButton(); button.focus();
    fireEvent.click(button);
    await screen.findByRole('dialog', { name: WINDOW });
    fireEvent.click(screen.getByRole('button', { name: 'Close QT editor' }));
    await waitFor(() => expect(document.activeElement).toBe(editButton()));
  });

  it('returns to the Edit positions button when it was opened from Model / System', async () => {
    await openOnSystem();
    const original = editButton()!; original.focus();
    fireEvent.click(original);
    await screen.findByRole('dialog', { name: WINDOW });
    fireEvent.click(screen.getByRole('button', { name: 'Close QT editor' }));
    await waitFor(() => expect(document.activeElement).toBe(editButton()));
    expect(editButton()!.hasAttribute('data-qt-edit-entry')).toBe(true);
  });

  it('does not leave focus on a box inside the hidden window', async () => {
    await openOnSystem();
    fireEvent.click(editButton()!);
    await screen.findByRole('dialog', { name: WINDOW });
    fireEvent.click(screen.getByRole('button', { name: 'Close QT editor' }));
    await waitFor(() => expect(editorWindow()).toBeNull());
    expect(document.activeElement).not.toBe(quantityBox());
  });
});

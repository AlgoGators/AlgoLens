// @vitest-environment jsdom
//
// "Edit positions" on every strategy page, for every internal reader.
//
// The button used to appear only when the book's QT workflow was required and
// available AND the Position stream was already on QT. A strategy that opens on
// Model / System (the default), or whose workflow is unavailable, showed no
// button and no clear way in. It is now always there for an internal reader:
//
//   QT + workflow required and available -> enabled; opens the editing window
//   Model / System                       -> enabled; switches to QT, then does the above
//   unavailable / loading / missing /
//   not signed in                        -> disabled, with the reason written on the page
//   legacy editing allowed               -> the old controls, no new button
//   anyone who is not internal           -> nothing
//
// The QT boxes are never on the page: they live in the window this button opens.
// The button only opens it. It never enables an action the server would refuse.

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
vi.mock('./QtProposalWorkspace', () => ({
  QtProposalWorkspace: (p: { actorId: string; bookId: string; sourceDay: string; embedded?: boolean }) => (
    <section aria-label="QT proposal workspace">
      <div data-testid="qt-workspace-context">{p.actorId}:{p.bookId}:{p.sourceDay}</div>
      <div data-testid="embedded">{String(!!p.embedded)}</div>
      <input aria-label="Chosen quantity ES.v.0" defaultValue="5" />
    </section>
  ),
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

describe('on the Model / System stream (the default view)', () => {
  it('shows an enabled Edit positions button beside the read-only sentence, and asks for nothing yet', async () => {
    await openOnSystem();
    const button = editButton()!;
    expect(button).toBeTruthy();
    expect(button.disabled).toBe(false);
    expect(screen.getByText(READ_ONLY)).toBeTruthy();
    // Looking is free: no QT capability request and no workspace until the reader asks.
    expect(qtApi.getProposal).not.toHaveBeenCalled();
    expect(screen.queryByRole('region', { name: 'QT proposal workspace' })).toBeNull();
    expect(editorWindow()).toBeNull();
    expect(getStrategyCalls).toEqual([['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'system']]);
  });

  it('switches to QT, waits for the workspace, and then opens the window with it', async () => {
    await openOnSystem();
    fireEvent.click(editButton()!);
    expect(streamBox().value).toBe('qt');
    const win = await screen.findByRole('dialog', { name: WINDOW });
    expect(getStrategyCalls.at(-1)).toEqual(['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'qt']);
    expect(within(win).getByTestId('qt-workspace-context').textContent).toBe('101:CONSERVATIVE_PORTFOLIO:2026-09-23');
    expect(within(win).getByTestId('embedded').textContent).toBe('true');
    expect(screen.getByText(/QT positions snapshot/i)).toBeTruthy();
  });

  it('does not open the window before the workspace can exist', async () => {
    const proposalReply = deferred<QtProposal>(); qtApi.getProposal.mockReturnValue(proposalReply.promise);
    await openOnSystem();
    fireEvent.click(editButton()!);
    await waitFor(() => expect(qtApi.getProposal).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    expect(editorWindow()).toBeNull();
    proposalReply.resolve(proposal(true));
    await screen.findByRole('dialog', { name: WINDOW });
    expect(screen.getByTestId('qt-workspace-context')).toBeTruthy();
  });

  it('leaves the visible reason, and opens no window, when the workflow turns out to be unavailable', async () => {
    qtApi.getProposal.mockResolvedValue(proposal(true, false, 'Synthetic workflow unavailable'));
    await openOnSystem();
    fireEvent.click(editButton()!);
    await screen.findByRole('status', { name: 'QT workflow availability' });
    expect(streamBox().value).toBe('qt');
    expect(screen.queryByRole('region', { name: 'QT proposal workspace' })).toBeNull();
    expect(editorWindow()).toBeNull();
    const button = editButton()!;
    expect(button.disabled).toBe(true);
    expect(describedBy(button)).toBe('Synthetic workflow unavailable');
    expect(screen.getAllByText('Synthetic workflow unavailable').length).toBeGreaterThan(0);
  });

  it('forgets the request if the reader goes back to Model / System before QT arrives', async () => {
    const qtReply = deferred<Strategy>();
    getStrategyImpl = async (_id, book, stream) => stream === 'qt' ? qtReply.promise
      : strategy({ portfolio_id: book, positionStream: 'system', positionEditUnavailableReason: READ_ONLY });
    await openOnSystem();
    fireEvent.click(editButton()!);
    fireEvent.change(streamBox(), { target: { value: 'system' } });
    await screen.findByText(/Model \/ System positions snapshot/i);
    // Later the reader picks QT themselves: the page must not open a window for a click they abandoned.
    serve();
    qtReply.resolve(strategy({ positionStream: 'qt' }));
    fireEvent.change(streamBox(), { target: { value: 'qt' } });
    await enabledButton();
    expect(editorWindow()).toBeNull();
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
  });

  it('forgets the request if the reader changes book before QT arrives', async () => {
    qtApi.getProposal.mockImplementation(async (book: string) => proposal(true, true, null, book));
    render(<StrategyDetail strategy={strategy({ books: ['CONSERVATIVE_PORTFOLIO', 'AGGRESSIVE_PORTFOLIO'] })}
      onBack={() => {}} />);
    await screen.findByText(/Model \/ System positions snapshot/i);
    fireEvent.click(editButton()!);
    fireEvent.change(screen.getByRole('combobox', { name: 'Which book to show' }), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    await waitFor(() => expect(getStrategyCalls.at(-1)).toEqual(['trendfollowing', 'AGGRESSIVE_PORTFOLIO', 'qt']));
    await enabledButton();
    expect(editorWindow()).toBeNull();
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
  });

  it('does not treat picking QT in the selector as a click on the button', async () => {
    await openOnSystem();
    fireEvent.change(streamBox(), { target: { value: 'qt' } });
    await enabledButton();
    expect(editorWindow()).toBeNull();
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
  });

  it('is disabled with a written reason when nobody is signed in', async () => {
    userId = '';
    await openOnSystem();
    const button = editButton()!;
    expect(button.disabled).toBe(true);
    expect(describedBy(button)).toBe('Sign in before changing QT positions.');
    expect(screen.getAllByText('Sign in before changing QT positions.').length).toBeGreaterThan(0);
    fireEvent.click(button);
    expect(streamBox().value).toBe('system');
    expect(editorWindow()).toBeNull();
  });

  it('is not offered to someone who is not internal', async () => {
    role = 'subscriber_individual';
    await openOnSystem();
    expect(editButton()).toBeNull();
    expect(editorWindow()).toBeNull();
    expect(screen.queryByText(READ_ONLY)).toBeNull();
  });
});

describe('on the QT stream, workflow required and available', () => {
  it('is enabled, sits beside the saved-positions sentence, and shows no QT boxes on the page until clicked', async () => {
    await openOnQt();
    const button = await enabledButton();
    expect(button.getAttribute('aria-describedby')).toBeNull();
    expect(screen.getByText(NEW_SENTENCE)).toBeTruthy();
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    expect(screen.queryByRole('region', { name: 'QT proposal workspace' })).toBeNull();
    expect(quantityBox()).toBeNull();
    expect(editorWindow()).toBeNull();
  });

  it('opens the window with the workspace on click, and again after it is closed', async () => {
    await openOnQt();
    fireEvent.click(await enabledButton());
    const win = await screen.findByRole('dialog', { name: WINDOW });
    expect(within(win).getByTestId('qt-workspace-context').textContent).toBe('101:CONSERVATIVE_PORTFOLIO:2026-09-23');
    expect(within(win).getByTestId('embedded').textContent).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: 'Close QT editor' }));
    expect(editorWindow()).toBeNull();
    fireEvent.click(editButton()!);
    expect(await screen.findByRole('dialog', { name: WINDOW })).toBeTruthy();
  });

  it('keeps an unsaved typed quantity when the window is closed and reopened', async () => {
    await openOnQt();
    fireEvent.click(await enabledButton());
    await screen.findByRole('dialog', { name: WINDOW });
    fireEvent.change(quantityBox()!, { target: { value: '9' } });
    fireEvent.click(screen.getByRole('button', { name: 'Close QT editor' }));
    expect(editorWindow()).toBeNull();
    fireEvent.click(editButton()!);
    await screen.findByRole('dialog', { name: WINDOW });
    expect(quantityBox()!.value).toBe('9');
  });

  it('closes and unmounts the window when the stream changes, so nothing stale lingers', async () => {
    await openOnQt();
    fireEvent.click(await enabledButton());
    await screen.findByRole('dialog', { name: WINDOW });
    fireEvent.change(quantityBox()!, { target: { value: '9' } });
    fireEvent.change(streamBox(), { target: { value: 'system' } });
    await screen.findByText(/Model \/ System positions snapshot/i);
    expect(editorWindow()).toBeNull();
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    expect(quantityBox()).toBeNull();
    // Coming back is a fresh start: the typed value did not survive.
    fireEvent.change(streamBox(), { target: { value: 'qt' } });
    await screen.findByText(/QT positions snapshot/i);
    expect(quantityBox()).toBeNull();
    fireEvent.click(await enabledButton());
    await screen.findByRole('dialog', { name: WINDOW });
    expect(quantityBox()!.value).toBe('5');
  });

  it('closes and unmounts the window when the book changes', async () => {
    qtApi.getProposal.mockImplementation(async (book: string) => proposal(true, true, null, book));
    render(<StrategyDetail strategy={strategy({ books: ['CONSERVATIVE_PORTFOLIO', 'AGGRESSIVE_PORTFOLIO'] })}
      onBack={() => {}} />);
    await screen.findByText(/Model \/ System positions snapshot/i);
    fireEvent.change(streamBox(), { target: { value: 'qt' } });
    await screen.findByText(/QT positions snapshot/i);
    fireEvent.click(await enabledButton());
    await screen.findByRole('dialog', { name: WINDOW });
    fireEvent.change(quantityBox()!, { target: { value: '9' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Which book to show' }), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    await waitFor(() => expect(getStrategyCalls.at(-1)).toEqual(['trendfollowing', 'AGGRESSIVE_PORTFOLIO', 'qt']));
    expect(editorWindow()).toBeNull();
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    expect(quantityBox()).toBeNull();
    fireEvent.click(await enabledButton());
    const win = await screen.findByRole('dialog', { name: 'Edit QT positions - AGGRESSIVE_PORTFOLIO' });
    expect(within(win).getByTestId('qt-workspace-context').textContent).toBe('101:AGGRESSIVE_PORTFOLIO:2026-09-23');
    expect(quantityBox()!.value).toBe('5');
  });

  it('is disabled with the loading reason while capability is unresolved, then enabled', async () => {
    const reply = deferred<QtProposal>(); qtApi.getProposal.mockReturnValue(reply.promise);
    await openOnQt();
    const button = editButton()!;
    expect(button.disabled).toBe(true);
    expect(describedBy(button)).toBe('Loading QT workflow capability. Position changes are disabled.');
    fireEvent.click(button);
    reply.resolve(proposal(true));
    await enabledButton();
    expect(editorWindow()).toBeNull();
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
  });
});

describe('on the QT stream, workflow not usable', () => {
  it.each(['unavailable', 'missing', 'wrong-book', 'wrong-day', 'network-failure'] as const)(
    'is disabled, and the page says why in words, for %s capability', async kind => {
      const p = proposal(true);
      if (kind === 'unavailable') {
        p.capability.available = false; p.workflow_state = 'workflow_unavailable';
        p.read_only_reason = 'Synthetic workflow unavailable';
      }
      if (kind === 'missing') delete (p as unknown as Record<string, unknown>).capability;
      if (kind === 'wrong-book') p.book_id = 'AGGRESSIVE_PORTFOLIO';
      if (kind === 'wrong-day') p.source_day = '2026-09-24';
      if (kind === 'network-failure') qtApi.getProposal.mockRejectedValue(new Error('synthetic failure'));
      else qtApi.getProposal.mockResolvedValue(p);
      await openOnQt();
      const status = await screen.findByRole('status', { name: 'QT workflow availability' });
      const reason = (status.textContent ?? '').trim();
      expect(reason).not.toBe('');
      if (kind === 'unavailable') expect(reason).toBe('Synthetic workflow unavailable');
      else expect(reason).toMatch(/Position changes are disabled\.$/);
      const button = editButton()!;
      expect(button.disabled).toBe(true);
      expect(describedBy(button)).toBe(reason);
      expect(screen.queryByRole('region', { name: 'QT proposal workspace' })).toBeNull();
      fireEvent.click(button);
      expect(streamBox().value).toBe('qt');
      expect(editorWindow()).toBeNull();
    });

  it('is disabled with the identity reason when the snapshot has no date', async () => {
    serve({ positionDate: null });
    await openOnQt();
    const button = editButton()!;
    expect(button.disabled).toBe(true);
    expect(describedBy(button)).toMatch(/^QT workflow source identity and date are unavailable\./);
  });
});

describe('legacy editing allowed', () => {
  it('shows the old controls and no second button', async () => {
    serve({ positionsEditable: true });
    qtApi.getProposal.mockResolvedValue(proposal(false));
    await openOnQt();
    await screen.findByRole('button', { name: /Adjust ES\.v\.0/ });
    expect(screen.getByRole('button', { name: 'Add position' })).toBeTruthy();
    expect(editButton()).toBeNull();
    expect(screen.queryByRole('region', { name: 'QT proposal workspace' })).toBeNull();
    expect(editorWindow()).toBeNull();
  });

  it('says why in words when the server does not make this snapshot editable', async () => {
    serve({ positionsEditable: false, positionEditUnavailableReason: 'Only the current server-date snapshot can be edited.' });
    qtApi.getProposal.mockResolvedValue(proposal(false));
    await openOnQt();
    await waitFor(() => expect(editButton()).not.toBeNull());
    const button = editButton()!;
    expect(button.disabled).toBe(true);
    expect(describedBy(button)).toBe('Only the current server-date snapshot can be edited.');
    expect(screen.getAllByText('Only the current server-date snapshot can be edited.')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: /Adjust ES\.v\.0/ })).toBeNull();
  });
});

describe('not internal', () => {
  it('shows nothing new on QT, whatever the workflow says', async () => {
    role = 'subscriber_individual';
    await openOnQt();
    expect(editButton()).toBeNull();
    expect(editorWindow()).toBeNull();
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    const view = within(document.body);
    expect(view.queryByText('Sign in before changing QT positions.')).toBeNull();
  });
});

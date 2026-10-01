// @vitest-environment jsdom
//
// Which book is this page about? Every number on a strategy's page -- value,
// history, metrics, executions, positions -- is read by (strategy, book). The
// page used to name the book only in small print above the positions table,
// and only the positions table followed the book picker; the value, the chart
// and the other two tabs stayed on the primary book with no label.
//
// Choosing a book the engine had not traded yet printed
//   API request failed: 404 NOT FOUND. Body: {"code":"no_data_for_book",...}
// and left the primary book's positions on screen under a picker naming the
// other book. Both found by driving the app, not by a test; these pin them.

import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { StrategyDetail } from './StrategyDetail';
import type { Strategy } from '../domain/portfolio/portfolioData';
import { ApiError } from '../infrastructure/api/httpClient';
import fixtures from '../../../contracts/qt-workflow-v1.json';
import { decodeQtProposal, type QtProposal } from '../domain/portfolio/qtPreview';
import { QtRecovery } from '../infrastructure/api/qtRecovery';
import { QtMutationUncertainError } from '../infrastructure/api/qtPreviewApi';

const qtApi = vi.hoisted(() => ({ getProposal: vi.fn(), confirmPreview: vi.fn() }));
vi.mock('../infrastructure/api/qtPreviewApi', async importOriginal => ({
  ...await importOriginal<typeof import('../infrastructure/api/qtPreviewApi')>(), QtPreviewApi: qtApi,
}));
const workspaceCallbacks: Array<() => void> = [];
vi.mock('./QtProposalWorkspace', () => ({
  QtProposalWorkspace: (p: { actorId: string; bookId: string; sourceDay: string; onPublished: () => void }) => {
    workspaceCallbacks.push(p.onPublished);
    return <section aria-label="QT proposal workspace">
      <div data-testid="qt-workspace-context">{p.actorId}:{p.bookId}:{p.sourceDay}</div>
      <button onClick={p.onPublished}>Simulate verified QT publication</button>
    </section>;
  },
}));

function qtProposal(book = 'CONSERVATIVE_PORTFOLIO', day = '2026-09-23', required = false): QtProposal {
  const raw = structuredClone(fixtures.proposal_ready);
  raw.book_id = book; raw.source_day = day; raw.capability.required = required;
  raw.seed_rows.forEach(row => { row.key.portfolio_id = book; row.key.date = day; });
  return decodeQtProposal(raw);
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(yes => { resolve = yes; });
  return { promise, resolve };
}

vi.mock('../adapters/react/ThemeContext', () => ({
  useTheme: () => ({ theme: 'light' }),
}));

let role = 'subscriber_individual';
let userId = 'reader-one';
vi.mock('../adapters/react/useAuth', () => ({
  useAuth: () => ({ user: { id: userId, role } }),
}));

// The children are stubbed down to the one thing these tests care about:
// which book's data each of them was handed.
// The save/refetch/reopen case renders the real table and editor through this parent.
let renderRealPositionBreakdown = false;
vi.mock('./PositionBreakdown', async importOriginal => {
  const actual = await importOriginal<typeof import('./PositionBreakdown')>();
  return { PositionBreakdown: (p: React.ComponentProps<typeof actual.PositionBreakdown>) =>
    renderRealPositionBreakdown ? <actual.PositionBreakdown {...p} /> : (
    <div>
      <div data-testid="positions">
        {p.portfolioId}:{p.positions.map(x => x.symbol).join(',')}
      </div>
      <div data-testid="position-identities">{p.positionStrategyNames?.join(',') ?? ''}</div>
      <div data-testid="positions-editable">{String(p.positionsEditable)}</div>
      <div data-testid="position-provenance">{p.positionStream ?? 'unknown'}</div>
      <div data-testid="position-edit-reason">{p.positionEditUnavailableReason ?? ''}</div>
      <button onClick={p.onEdited}>Simulate completed edit</button>
      <button disabled={!p.onEditInWorkspace} onClick={p.onEditInWorkspace}>Edit positions</button>
      {p.bookControl}
    </div>
  ) };
});
vi.mock('./FinancialAnalysis', () => ({
  FinancialAnalysis: (p: { metrics: { tag?: string } }) => (
    <div data-testid="analysis">{p.metrics.tag}</div>
  ),
}));
vi.mock('./TradingActivity', () => ({
  TradingActivity: (p: { executions: { tag?: string }[]; activityStream?: 'qt' | null;
    finalizedPositionsAvailable?: boolean }) => (
    <div data-testid="activity">
      {p.executions.map(e => e.tag).join(',')}:{p.activityStream ?? 'unknown'}:{String(p.finalizedPositionsAvailable)}
    </div>
  ),
}));
vi.mock('./AlphaAttribution', () => ({ AlphaAttribution: () => null }));
vi.mock('recharts', () => {
  const Stub = () => null;
  return {
    LineChart: Stub, Line: Stub, XAxis: Stub, YAxis: Stub, Tooltip: Stub,
    ResponsiveContainer: Stub,
  };
});

// A plain function rather than a vi.fn spy. The spy tracks every promise it
// returns, and a rejected one it has handed out fails the test even after the
// component has caught it -- which is exactly the path these tests exercise.
type Impl = (id: string, book?: string, stream?: 'system' | 'qt') => Promise<Strategy>;
let getStrategyImpl: Impl = async () => { throw new Error('getStrategy not set'); };
const getStrategyCalls: unknown[][] = [];
type OverridesImpl = (id: string, book: string) => Promise<unknown[]>;
let getPositionOverridesImpl: OverridesImpl = async () => [];
const getPositionOverridesCalls: [string, string][] = [];
const savePositionCalls: unknown[] = [];
vi.mock('../infrastructure/api/portfolioApi', () => ({
  PortfolioApiService: {
    getStrategy: (id: string, book?: string, stream?: 'system' | 'qt') => {
      getStrategyCalls.push([id, book, stream]);
      return getStrategyImpl(id, book, stream);
    },
    getPositionOverrides: (id: string, book: string) => {
      getPositionOverridesCalls.push([id, book]);
      return getPositionOverridesImpl(id, book);
    },
    savePosition: (input: unknown) => {
      savePositionCalls.push(input);
      return Promise.resolve({ outcome: 'saved' as const });
    },
  },
}));

function strategy(over: Partial<Strategy> & { tag: string }): Strategy {
  const { tag, ...rest } = over;
  return {
    id: 'trendfollowing',
    name: 'Trend Following',
    description: 'Systematic trend following',
    invested: 500000,
    currentValue: 523681.65,
    return: 23681.65,
    returnPercent: 4.74,
    positions: [{ symbol: `${tag}-POS` }],
    positionStream: 'system',
    positionStrategyNames: [],
    historicalData: [],
    bestDay: null,
    worstDay: null,
    metrics: { tag },
    executions: [{ tag }],
    finalizedPositions: [],
    activityStream: 'qt',
    finalizedPositionsAvailable: true,
    managers: [],
    lastUpdate: '2026-09-15',
    portfolio_id: 'CONSERVATIVE_PORTFOLIO',
    books: ['CONSERVATIVE_PORTFOLIO'],
    ...rest,
  } as unknown as Strategy;
}

/** The book box in the row at the top of the page. */
const topBox = () => screen.getByRole('combobox', { name: 'Which book to show' }) as HTMLSelectElement;
/** The book box beside "Today's Positions". */
const headingBox = () => screen.getByRole('combobox', { name: 'Book for these positions' }) as HTMLSelectElement;

function serveQtDetail(over: Partial<Strategy> & { tag: string }) {
  getStrategyImpl = async (_id, book, stream) => stream === 'qt'
    ? strategy({ ...over, portfolio_id: book, positionStream: 'qt' })
    : strategy({ tag: 'MODEL', portfolio_id: book, positionStream: 'system' });
}

/** The QT workspace lives in a window opened by "Edit positions"; wait until the button is usable, then click it. */
async function openEditor() {
  await waitFor(() => expect((screen.getByRole('button', { name: 'Edit positions' }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button', { name: 'Edit positions' }));
}

async function selectQt() {
  await waitFor(() => expect(screen.getByTestId('positions').textContent)
    .toContain('MODEL-POS'));
  fireEvent.change(screen.getByRole('combobox', { name: 'Position stream' }), {
    target: { value: 'qt' },
  });
}

beforeEach(() => {
  sessionStorage.clear();
  qtApi.confirmPreview.mockReset();
  qtApi.getProposal.mockReset();
  qtApi.getProposal.mockImplementation(async (book: string) => qtProposal(book));
  workspaceCallbacks.length = 0;
  role = 'subscriber_individual';
  userId = 'reader-one';
  renderRealPositionBreakdown = false;
  savePositionCalls.length = 0;
  getStrategyCalls.length = 0;
  getStrategyImpl = async (id, book, stream) => strategy({
    id, tag: 'C', portfolio_id: book, positionStream: stream,
  });
  getPositionOverridesCalls.length = 0;
  getPositionOverridesImpl = async () => [];
});
afterEach(() => sessionStorage.clear());

describe('model-default position selection', () => {
  it('fetches primary-book model positions before showing any cached QT prop', async () => {
    let release: (detail: Strategy) => void = () => {};
    getStrategyImpl = () => new Promise(resolve => { release = resolve; });
    render(<StrategyDetail strategy={strategy({ tag: 'QT', positionStream: 'qt' })} onBack={() => {}} />);

    expect(screen.queryByTestId('positions')).toBeNull();
    expect(getStrategyCalls).toEqual([
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'system'],
    ]);

    release(strategy({ tag: 'MODEL', positionStream: 'system' }));
    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:MODEL-POS'));
    expect(screen.getByRole('combobox', { name: 'Position stream' })).toBeTruthy();
  });

  it('switches the same book to explicitly fetched QT positions', async () => {
    getStrategyImpl = async (_id, _book, stream) => strategy({
      tag: stream === 'qt' ? 'QT' : 'MODEL', positionStream: stream,
    });
    render(<StrategyDetail strategy={strategy({ tag: 'QT', positionStream: 'qt' })} onBack={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:MODEL-POS'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Position stream' }), {
      target: { value: 'qt' },
    });

    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:QT-POS'));
    expect(getStrategyCalls).toEqual([
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'system'],
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'qt'],
    ]);
  });

  it('never lets a late model answer overwrite the selected QT stream', async () => {
    const pending: Partial<Record<'system' | 'qt', (detail: Strategy) => void>> = {};
    getStrategyImpl = (_id, _book, stream) => new Promise(resolve => {
      pending[stream as 'system' | 'qt'] = resolve;
    });
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Position stream' }), {
      target: { value: 'qt' },
    });
    expect(screen.queryByTestId('positions')).toBeNull();
    pending.qt?.(strategy({ tag: 'QT', positionStream: 'qt' }));
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('QT-POS'));
    pending.system?.(strategy({ tag: 'MODEL', positionStream: 'system' }));
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(screen.getByTestId('positions').textContent).toContain('QT-POS');
    expect(screen.getByTestId('position-provenance').textContent).toBe('qt');
  });

  it('does not substitute model data when the requested QT stream fails', async () => {
    getStrategyImpl = async (_id, _book, stream) => {
      if (stream === 'qt') throw new ApiError('HTTP 503', 503, undefined, 'QT positions unavailable');
      return strategy({ tag: 'MODEL', positionStream: 'system' });
    };
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    await selectQt();
    expect((await screen.findByRole('alert')).textContent).toBe('QT positions unavailable');
    expect(screen.queryByTestId('positions')).toBeNull();
    expect(screen.getByRole<HTMLSelectElement>('combobox', { name: 'Position stream' }).value).toBe('qt');
    expect(getStrategyCalls).toEqual([
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'system'],
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'qt'],
    ]);
  });

  it('rejects a response that explicitly names another stream or book', async () => {
    getStrategyImpl = async (_id, _book, stream) => stream === 'qt'
      ? strategy({ tag: 'WRONG', positionStream: 'system' })
      : strategy({ tag: 'MODEL', positionStream: 'system' });
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    await selectQt();
    expect((await screen.findByRole('alert')).textContent).toMatch(/does not match/i);
    expect(screen.queryByTestId('positions')).toBeNull();
  });

  it.each([null, undefined])('treats legacy provenance %s as unknown, not inferred from selection', async provenance => {
    getStrategyImpl = async (_id, _book, stream) => strategy({
      tag: stream === 'qt' ? 'QT' : 'MODEL', positionStream: provenance,
      activityStream: null, finalizedPositionsAvailable: false,
    });
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('MODEL-POS'));
    expect(screen.getByTestId('position-provenance').textContent).toBe('unknown');
    fireEvent.change(screen.getByRole('combobox', { name: 'Position stream' }), {
      target: { value: 'qt' },
    });
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('QT-POS'));
    expect(screen.getByTestId('position-provenance').textContent).toBe('unknown');
    fireEvent.click(screen.getByText('Trading Activity'));
    expect(screen.getByTestId('activity').textContent).toContain('unknown:false');
  });

  it('reloads the same QT scope after an edit and notifies dashboard aggregation', async () => {
    let qtCalls = 0;
    const onPositionsChanged = vi.fn();
    getStrategyImpl = async (_id, _book, stream) => stream === 'qt'
      ? strategy({ tag: `QT${++qtCalls}`, positionStream: 'qt' })
      : strategy({ tag: 'MODEL', positionStream: 'system' });
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}}
      onPositionsChanged={onPositionsChanged} />);
    await selectQt();
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('QT1-POS'));
    fireEvent.click(screen.getByText('Simulate completed edit'));
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('QT2-POS'));
    expect(onPositionsChanged).toHaveBeenCalledOnce();
    expect(getStrategyCalls.slice(-2)).toEqual([
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'qt'],
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'qt'],
    ]);
  });

  it('reopens the refreshed QT row with adjacent exact quantity and unchanged basis', async () => {
    role = 'admin';
    renderRealPositionBreakdown = true;
    const book = 'MACRO_BOOK';
    const before = '92233720368.12345678';
    const after = '92233720368.12345679';
    const exactPosition = (quantityExact: string): Strategy['positions'][number] => ({
      symbol: 'ES.v.0', strategyName: 'Engine A', name: 'ES',
      shares: 92233720368.12346, quantity_exact: quantityExact,
      costBasis: 92233720368.12346, average_price_exact: before,
      currentValue: null, marketPrice: null, notional: null,
    });
    getStrategyImpl = async (id, requestedBook, stream) => strategy({
      id, tag: stream === 'qt' ? 'QT' : 'MODEL',
      portfolio_id: requestedBook, positionStream: stream,
      positionDate: '2026-09-23', positionsEditable: stream === 'qt',
      positionStrategyNames: stream === 'qt' ? ['Engine A'] : [],
      positions: stream === 'qt'
        ? [exactPosition(savePositionCalls.length ? after : before)] : [],
    });
    const onPositionsChanged = vi.fn();
    render(<StrategyDetail strategy={strategy({ tag: 'C', portfolio_id: book,
      books: [book] })} onBack={() => {}} onPositionsChanged={onPositionsChanged} />);

    await screen.findByText(/Model \/ System positions snapshot 2026-09-23/i);
    fireEvent.change(screen.getByRole('combobox', { name: 'Position stream' }), {
      target: { value: 'qt' },
    });
    fireEvent.click(await screen.findByRole('button', { name: 'Adjust ES.v.0 (Engine A)' }));
    expect((screen.getByLabelText('Quantity') as HTMLInputElement).value).toBe(before);
    expect((screen.getByLabelText(/Average price/) as HTMLInputElement).value).toBe(before);

    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: after } });
    fireEvent.change(screen.getByLabelText('Reason (required)'), {
      target: { value: 'rebalance' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(savePositionCalls).toHaveLength(1));
    expect(savePositionCalls[0]).toEqual(expect.objectContaining({
      strategy_id: 'trendfollowing', strategy_name: 'Engine A', symbol: 'ES.v.0',
      portfolio_id: book, quantity: after, average_price: before,
    }));
    await waitFor(() => expect(getStrategyCalls).toEqual([
      ['trendfollowing', book, 'system'],
      ['trendfollowing', book, 'qt'],
      ['trendfollowing', book, 'qt'],
    ]));
    await waitFor(() => expect(screen.getByText('ES.v.0').closest('div.grid')
      ?.children[1].textContent).toBe(after));
    expect(onPositionsChanged).toHaveBeenCalledOnce();
    expect(screen.queryByRole('dialog')).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: 'Adjust ES.v.0 (Engine A)' }));
    expect((screen.getByLabelText('Quantity') as HTMLInputElement).value).toBe(after);
    expect((screen.getByLabelText(/Average price/) as HTMLInputElement).value).toBe(before);
  });

  it('clears selected QT data and defaults to model on a different reader', async () => {
    getStrategyImpl = async (_id, _book, stream) => strategy({
      tag: stream === 'qt' ? 'QT' : 'MODEL', positionStream: stream,
    });
    const view = render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    await selectQt();
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('QT-POS'));
    userId = 'reader-two';
    view.rerender(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    expect(screen.queryByTestId('positions')).toBeNull();
    expect(screen.getByRole<HTMLSelectElement>('combobox', { name: 'Position stream' }).value).toBe('system');
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('MODEL-POS'));
    expect(getStrategyCalls.at(-1)).toEqual(['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'system']);
  });
});

describe('QT proposal capability cutover', () => {
  const books = ['CONSERVATIVE_PORTFOLIO', 'AGGRESSIVE_PORTFOLIO'];
  const qtDetail = () => strategy({ tag: 'QT', positionDate: '2026-09-23', positionsEditable: true,
    positionStrategyNames: ['Engine A'], books });

  it('keeps MODEL read data unchanged without requesting QT capability or mounting a workspace', async () => {
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await screen.findByTestId('positions');
    expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS');
    expect(screen.getByTestId('position-provenance').textContent).toBe('system');
    expect(screen.queryByRole('region', { name: 'QT proposal workspace' })).toBeNull();
    expect(qtApi.getProposal).not.toHaveBeenCalled();
  });

  it('mounts a matching required workspace and disables the old editor while preserving read props', async () => {
    userId = '101';
    serveQtDetail({ ...qtDetail(), tag: 'QT' });
    qtApi.getProposal.mockResolvedValue(qtProposal('CONSERVATIVE_PORTFOLIO', '2026-09-23', true));
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await selectQt();
    await waitFor(() => expect((screen.getByRole('button', { name: 'Edit positions' }) as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    await openEditor();
    expect((await screen.findByTestId('qt-workspace-context')).textContent)
      .toBe('101:CONSERVATIVE_PORTFOLIO:2026-09-23');
    expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:QT-POS');
    expect(screen.getByTestId('position-identities').textContent).toBe('Engine A');
    expect(screen.getByTestId('positions-editable').textContent).toBe('false');
    expect(screen.getByTestId('position-edit-reason').textContent).toContain('Use Edit positions to change a quantity');
  });

  it('cannot mount the real old edit modal in a required book, even when the snapshot says editable', async () => {
    role = 'admin'; userId = '101'; renderRealPositionBreakdown = true;
    serveQtDetail({ ...qtDetail(), tag: 'QT', positions: [{ symbol: 'SYN', name: 'Synthetic',
      strategyName: 'Engine A', shares: 5, quantity_exact: '5', costBasis: 100,
      average_price_exact: '100', currentValue: null, marketPrice: null, notional: null }] });
    qtApi.getProposal.mockResolvedValue(qtProposal('CONSERVATIVE_PORTFOLIO', '2026-09-23', true));
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await screen.findByText(/Model \/ System positions snapshot/i);
    fireEvent.change(screen.getByRole('combobox', { name: 'Position stream' }), { target: { value: 'qt' } });
    await openEditor();
    await screen.findByTestId('qt-workspace-context');
    expect(screen.queryByRole('button', { name: /Adjust SYN/ })).toBeNull();
    // The QT window is itself a dialog now; the old position editor is the one that must not exist.
    expect(document.getElementById('position-editor-title')).toBeNull();
    expect(screen.queryByRole('dialog', { name: /Edit position|Adjust/i })).toBeNull();
    expect(savePositionCalls).toEqual([]);
  });

  it('keeps mutation disabled while capability is unresolved, then allows only explicit legacy capability', async () => {
    serveQtDetail({ ...qtDetail(), tag: 'QT' });
    const response = deferred<QtProposal>(); qtApi.getProposal.mockReturnValue(response.promise);
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await selectQt();
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('QT-POS'));
    expect(screen.getByTestId('positions-editable').textContent).toBe('false');
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    await act(async () => response.resolve(qtProposal()));
    await waitFor(() => expect(screen.getByTestId('positions-editable').textContent).toBe('true'));
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
  });

  it.each(['unavailable', 'missing', 'wrong-book', 'wrong-day', 'network-failure'] as const)
  ('fails closed for %s capability and shows an accessible read-only reason', async kind => {
    serveQtDetail({ ...qtDetail(), tag: 'QT' });
    const proposal = qtProposal();
    if (kind === 'unavailable') {
      proposal.capability.available = false; proposal.capability.required = true;
      proposal.workflow_state = 'workflow_unavailable'; proposal.read_only_reason = 'Synthetic workflow unavailable';
    }
    if (kind === 'missing') delete (proposal as unknown as Record<string, unknown>).capability;
    if (kind === 'wrong-book') proposal.book_id = 'AGGRESSIVE_PORTFOLIO';
    if (kind === 'wrong-day') proposal.source_day = '2026-09-24';
    if (kind === 'network-failure') qtApi.getProposal.mockRejectedValue(new Error('synthetic failure'));
    else qtApi.getProposal.mockResolvedValue(proposal);
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await selectQt();
    await waitFor(() => expect(qtApi.getProposal).toHaveBeenCalledTimes(1));
    await screen.findByRole('status', { name: 'QT workflow availability' });
    expect(screen.getByTestId('positions-editable').textContent).toBe('false');
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    expect(screen.getByTestId('position-edit-reason').textContent).not.toBe('');
  });

  it('never guesses a source day when the selected QT snapshot has no date', async () => {
    serveQtDetail({ ...qtDetail(), tag: 'QT', positionDate: null });
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await selectQt();
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('QT-POS'));
    expect(screen.getByTestId('positions-editable').textContent).toBe('false');
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    expect(qtApi.getProposal).not.toHaveBeenCalled();
  });

  it('ignores earlier book capability and attaches history only to the selected book', async () => {
    role = 'general_member'; userId = '101';
    serveQtDetail({ ...qtDetail(), tag: 'QT' });
    const previous = deferred<QtProposal>();
    qtApi.getProposal.mockImplementation((book: string) => book === 'CONSERVATIVE_PORTFOLIO'
      ? previous.promise : Promise.resolve(qtProposal(book, '2026-09-23', true)));
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await selectQt();
    await waitFor(() => expect(qtApi.getProposal).toHaveBeenCalledTimes(1));
    fireEvent.change(topBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    await openEditor();
    expect((await screen.findByTestId('qt-workspace-context')).textContent)
      .toBe('101:AGGRESSIVE_PORTFOLIO:2026-09-23');
    await act(async () => previous.resolve(qtProposal()));
    expect(screen.getByTestId('positions-editable').textContent).toBe('false');
    expect(screen.getByTestId('qt-workspace-context').textContent).toContain('AGGRESSIVE_PORTFOLIO');
    expect(getPositionOverridesCalls.at(-1)).toEqual(['trendfollowing', 'AGGRESSIVE_PORTFOLIO']);
  });

  it('removes prior workspace authority and ignores stale publication callbacks after a book change', async () => {
    userId = '101'; serveQtDetail({ ...qtDetail(), tag: 'QT' });
    qtApi.getProposal.mockImplementation(async (book: string) => qtProposal(book, '2026-09-23', true));
    const onPositionsChanged = vi.fn();
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} onPositionsChanged={onPositionsChanged} />);
    await selectQt(); await openEditor(); await screen.findByTestId('qt-workspace-context');
    const previousCallback = workspaceCallbacks.at(-1)!;
    fireEvent.change(topBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    await openEditor(); await screen.findByTestId('qt-workspace-context');
    const calls = getStrategyCalls.length;
    await act(async () => previousCallback());
    expect(getStrategyCalls).toHaveLength(calls);
    expect(onPositionsChanged).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText('Simulate verified QT publication'));
    await waitFor(() => expect(onPositionsChanged).toHaveBeenCalledOnce());
    expect(getStrategyCalls.at(-1)).toEqual(['trendfollowing', 'AGGRESSIVE_PORTFOLIO', 'qt']);
  });

  it('ignores capability from the prior authenticated actor after returning to QT', async () => {
    userId = '101'; serveQtDetail({ ...qtDetail(), tag: 'QT' });
    const previous = deferred<QtProposal>();
    qtApi.getProposal.mockReturnValueOnce(previous.promise).mockResolvedValue(qtProposal());
    const view = render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await selectQt(); await waitFor(() => expect(qtApi.getProposal).toHaveBeenCalledTimes(1));
    userId = '202'; view.rerender(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    await selectQt();
    await waitFor(() => expect(screen.getByTestId('positions-editable').textContent).toBe('true'));
    await act(async () => previous.resolve(qtProposal('CONSERVATIVE_PORTFOLIO', '2026-09-23', true)));
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    expect(screen.getByTestId('positions-editable').textContent).toBe('true');
  });

  it('does not reuse capability or publication authority when the book selection returns A to B to A', async () => {
    userId = '101'; serveQtDetail({ ...qtDetail(), tag: 'QT' });
    const nextCapability = deferred<QtProposal>();
    qtApi.getProposal.mockResolvedValueOnce(qtProposal('CONSERVATIVE_PORTFOLIO', '2026-09-23', true))
      .mockReturnValue(nextCapability.promise);
    const pendingBook = deferred<Strategy>();
    const originalGetStrategy = getStrategyImpl;
    getStrategyImpl = (id, book, stream) => book === 'AGGRESSIVE_PORTFOLIO'
      ? pendingBook.promise : originalGetStrategy(id, book, stream);
    const onPositionsChanged = vi.fn();
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} onPositionsChanged={onPositionsChanged} />);
    await selectQt(); await openEditor(); await screen.findByTestId('qt-workspace-context');
    const priorPublication = workspaceCallbacks.at(-1)!;
    fireEvent.change(topBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    fireEvent.change(topBox(), { target: { value: 'CONSERVATIVE_PORTFOLIO' } });
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('QT-POS'));
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    expect(screen.getByTestId('positions-editable').textContent).toBe('false');
    const calls = getStrategyCalls.length;
    await act(async () => priorPublication());
    expect(getStrategyCalls).toHaveLength(calls);
    expect(onPositionsChanged).not.toHaveBeenCalled();
    await act(async () => nextCapability.resolve(qtProposal()));
    await waitFor(() => expect(screen.getByTestId('positions-editable').textContent).toBe('true'));
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
  });

  it.each(['MODEL', 'legacy QT'] as const)
  ('clears A uncertain recovery through B %s and never restores it when A returns', async mode => {
    userId = '101'; serveQtDetail({ ...qtDetail(), tag: 'QT' });
    qtApi.getProposal.mockImplementation(async (book: string) => qtProposal(book, '2026-09-23', userId === '101'));
    qtApi.confirmPreview.mockRejectedValue(new QtMutationUncertainError());
    const view = render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await selectQt(); await openEditor(); await screen.findByTestId('qt-workspace-context');
    // The child is stubbed here; arrange its real recovery lifecycle/uncertain request.
    QtRecovery.activateActor(sessionStorage, '101');
    const intent = { actor_id: '101', book_id: 'CONSERVATIVE_PORTFOLIO',
      preview_id: fixtures.preview_clean.preview_id, expected_digest: fixtures.preview_clean.payload_digest,
      idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false };
    await expect(QtRecovery.submitConfirmation(sessionStorage, intent)).rejects.toBeInstanceOf(QtMutationUncertainError);
    QtRecovery.stageApproval(sessionStorage, { actor_id: '101', book_id: intent.book_id,
      request_id: fixtures.confirm_pending.request_id!, idempotency_key: intent.idempotency_key });
    expect(QtRecovery.loadConfirmation(sessionStorage, '101', intent.book_id)).toEqual(intent);
    expect(QtRecovery.loadApproval(sessionStorage, '101', intent.book_id)).not.toBeNull();

    userId = '202'; view.rerender(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('MODEL-POS'));
    expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    if (mode === 'legacy QT') {
      await selectQt();
      await waitFor(() => expect(screen.getByTestId('positions-editable').textContent).toBe('true'));
      expect(screen.queryByTestId('qt-workspace-context')).toBeNull();
    }
    expect(QtRecovery.loadConfirmation(sessionStorage, '101', intent.book_id)).toBeNull();
    expect(QtRecovery.loadApproval(sessionStorage, '101', intent.book_id)).toBeNull();

    userId = '101'; view.rerender(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    if ((screen.getByRole('combobox', { name: 'Position stream' }) as HTMLSelectElement).value === 'system') await selectQt();
    await openEditor();
    expect((await screen.findByTestId('qt-workspace-context')).textContent).toContain('101:');
    expect(QtRecovery.loadConfirmation(sessionStorage, '101', intent.book_id)).toBeNull();
    expect(QtRecovery.loadApproval(sessionStorage, '101', intent.book_id)).toBeNull();
    expect(qtApi.confirmPreview).toHaveBeenCalledTimes(1);
  });

  it('preserves same-actor uncertain recovery when only the selected book and stream change', async () => {
    userId = '101'; serveQtDetail({ ...qtDetail(), tag: 'QT' });
    qtApi.getProposal.mockImplementation(async (book: string) => qtProposal(book, '2026-09-23', true));
    qtApi.confirmPreview.mockRejectedValue(new QtMutationUncertainError());
    render(<StrategyDetail strategy={qtDetail()} onBack={() => {}} />);
    await selectQt(); await openEditor(); await screen.findByTestId('qt-workspace-context');
    QtRecovery.activateActor(sessionStorage, '101');
    const intent = { actor_id: '101', book_id: 'CONSERVATIVE_PORTFOLIO',
      preview_id: fixtures.preview_clean.preview_id, expected_digest: fixtures.preview_clean.payload_digest,
      idempotency_key: '22222222-2222-4222-8222-222222222222', acknowledge_warnings: false };
    await expect(QtRecovery.submitConfirmation(sessionStorage, intent)).rejects.toBeInstanceOf(QtMutationUncertainError);
    fireEvent.change(screen.getByRole('combobox', { name: 'Position stream' }), { target: { value: 'system' } });
    fireEvent.change(topBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toContain('AGGRESSIVE_PORTFOLIO'));
    expect(QtRecovery.loadConfirmation(sessionStorage, '101', intent.book_id)).toEqual(intent);
    expect(qtApi.confirmPreview).toHaveBeenCalledTimes(1);
  });
});

describe('position identity plumbing', () => {
  it('passes the server-owned flat-snapshot identities to the position editor', async () => {
    getStrategyImpl = async (_id, book, stream) => strategy({
      tag: 'MODEL', portfolio_id: book, positionStream: stream,
      positionStrategyNames: ['Engine A'],
    });
    render(
      <StrategyDetail
        strategy={strategy({ tag: 'C', positionStrategyNames: ['Engine A'] })}
        onBack={() => {}}
      />,
    );

    await waitFor(() => expect(screen.getByTestId('position-identities').textContent).toBe('Engine A'));
  });
});

describe('QT result availability beside a real position snapshot', () => {
  it('shows editable QT positions with unknown performance and no zero-value substitute', async () => {
    const qt = strategy({
      tag: 'QT', dataAvailable: false, resultSource: 'qt', resultDate: null,
      currentValue: null, return: null, returnPercent: null,
      positionDate: '2026-09-23', positionsEditable: true,
      positionStrategyNames: ['Engine A'],
      historicalData: [],
    });
    serveQtDetail({ ...qt, tag: 'QT' });
    render(<StrategyDetail strategy={qt} onBack={() => {}} />);
    await selectQt();

    await waitFor(() => expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:QT-POS'));
    expect(screen.getByTestId('position-identities').textContent).toBe('Engine A');
    await waitFor(() => expect(screen.getByTestId('positions-editable').textContent).toBe('true'));
    expect(screen.getByText(/System-model performance unavailable/i)).toBeTruthy();
    expect(screen.queryByText('$0.00')).toBeNull();
  });

  it('does not render an older zero placeholder as a measured portfolio value', async () => {
    const qt = strategy({
      tag: 'QT', dataAvailable: false, resultSource: 'qt', resultDate: null,
      currentValue: 0, return: null, returnPercent: null,
    });
    serveQtDetail({ ...qt, tag: 'QT' });
    render(<StrategyDetail strategy={qt} onBack={() => {}} />);
    await selectQt();
    await waitFor(() => expect(screen.getByText(/System-model performance unavailable/i)).toBeTruthy());
    expect(screen.queryByText('$0.00')).toBeNull();
  });

  it('states an older QT result date separately from the newer position snapshot', async () => {
    const qt = strategy({
      tag: 'QT', dataAvailable: true, resultSource: 'qt', resultDate: '2026-09-18',
      positionDate: '2026-09-23',
    });
    serveQtDetail({ ...qt, tag: 'QT' });
    render(<StrategyDetail strategy={qt} onBack={() => {}} />);
    await selectQt();

    await waitFor(() => expect(screen.getByText(/System-model performance as of 2026-09-18/i)).toBeTruthy());
    expect(screen.getAllByText(/positions snapshot 2026-09-23/i).length).toBeGreaterThan(0);
  });
});

describe('override history access and book scope', () => {
  it('does not render or request override history for a subscriber', async () => {
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);

    await new Promise(resolve => setTimeout(resolve, 0));

    expect(screen.queryByText('Loading…')).toBeNull();
    expect(screen.queryByRole('heading', { name: 'Manual edits' })).toBeNull();
    expect(getPositionOverridesCalls).toEqual([]);
  });

  it('renders override history and requests the shown book for an internal role', async () => {
    role = 'general_member';
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);

    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Manual edits' })).toBeTruthy(),
    );
    expect(getPositionOverridesCalls).toEqual([
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO'],
    ]);
  });

  it('requests override history for the newly selected book', async () => {
    role = 'general_member';
    getStrategyImpl = async (_id, book, stream) => book === 'AGGRESSIVE_PORTFOLIO' ?
      strategy({
        tag: 'A',
        portfolio_id: 'AGGRESSIVE_PORTFOLIO',
        positionStream: stream,
        books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
      }) : strategy({ tag: 'C', positionStream: stream,
        books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });
    render(
      <StrategyDetail
        strategy={strategy({
          tag: 'C',
          books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
        })}
        onBack={() => {}}
      />,
    );

    await waitFor(() =>
      expect(getPositionOverridesCalls).toEqual([
        ['trendfollowing', 'CONSERVATIVE_PORTFOLIO'],
      ]),
    );
    fireEvent.change(topBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });

    await waitFor(() =>
      expect(getPositionOverridesCalls).toEqual([
        ['trendfollowing', 'CONSERVATIVE_PORTFOLIO'],
        ['trendfollowing', 'AGGRESSIVE_PORTFOLIO'],
      ]),
    );
  });
});

describe('the page says which book it is about', () => {
  it('names the book even when there is only one', () => {
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    expect(screen.getByTestId('book-name').textContent).toBe('CONSERVATIVE_PORTFOLIO');
    expect(screen.queryByRole('combobox', { name: 'Which book to show' })).toBeNull();
    expect(screen.getByRole('combobox', { name: 'Position stream' })).toBeTruthy();
  });

  it('offers every book, marking the primary, when there are several', () => {
    render(
      <StrategyDetail
        strategy={strategy({
          tag: 'C',
          books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
        })}
        onBack={() => {}}
      />,
    );
    const picker = topBox();
    expect(picker.value).toBe('CONSERVATIVE_PORTFOLIO');
    expect(Array.from(picker.options).map(o => o.textContent)).toEqual([
      'CONSERVATIVE_PORTFOLIO (primary)',
      'AGGRESSIVE_PORTFOLIO',
    ]);
  });
});

describe('switching book switches the whole page', () => {
  const primary = () =>
    strategy({ tag: 'C', books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });

  it('re-reads value, positions, metrics and executions from the chosen book', async () => {
    getStrategyImpl = async (_id, book, stream) => book === 'AGGRESSIVE_PORTFOLIO' ?
      strategy({
        tag: 'A',
        currentValue: 111111,
        portfolio_id: 'AGGRESSIVE_PORTFOLIO',
        positionStream: stream,
        books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
      }) : strategy({ tag: 'C', positionStream: stream,
        books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:C-POS'));

    fireEvent.change(topBox(), {
      target: { value: 'AGGRESSIVE_PORTFOLIO' },
    });

    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('AGGRESSIVE_PORTFOLIO:A-POS'),
    );
    expect(getStrategyCalls).toEqual([
      ['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'system'],
      ['trendfollowing', 'AGGRESSIVE_PORTFOLIO', 'system'],
    ]);
    expect(screen.getByText('$111,111.00')).toBeTruthy();

    fireEvent.click(screen.getByText('Financial Analysis'));
    expect(screen.getByTestId('analysis').textContent).toBe('A');
    fireEvent.click(screen.getByText('Trading Activity'));
    expect(screen.getByTestId('activity').textContent).toBe('A:qt:true');
  });

  it('shows an empty book as empty, not as the primary book under its name', async () => {
    getStrategyImpl = async (_id, book, stream) => {
      if (book === 'CONSERVATIVE_PORTFOLIO') return strategy({ tag: 'C', positionStream: stream });
      throw new ApiError(
        'API request failed: 404 NOT FOUND. Body: {"code":"no_data_for_book"}',
        404,
        'no_data_for_book',
        'The engine has not published any results for this strategy in AGGRESSIVE_PORTFOLIO yet.',
      );
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:C-POS'));

    fireEvent.change(topBox(), {
      target: { value: 'AGGRESSIVE_PORTFOLIO' },
    });

    const status = (await screen.findByText(/Nothing published for Trend Following in/)).closest('[role=status]') as HTMLElement;
    expect(status.textContent).toContain('Nothing published for Trend Following in AGGRESSIVE_PORTFOLIO yet');
    // None of the primary book's numbers survive under the other book's name.
    expect(screen.queryByTestId('positions')).toBeNull();
    expect(screen.queryByText('$523,681.65')).toBeNull();
    // And no raw API text anywhere.
    expect(document.body.textContent).not.toContain('API request failed');
    expect(topBox().value).toBe('AGGRESSIVE_PORTFOLIO');
  });

  it('on any other failure, says so plainly and keeps the picker on the book shown', async () => {
    getStrategyImpl = async (_id, book, stream) => {
      if (book === 'CONSERVATIVE_PORTFOLIO') return strategy({ tag: 'C', positionStream: stream });
      throw new ApiError(
        'API request failed: 500 INTERNAL SERVER ERROR. Body: {...}',
        500,
        undefined,
        'Failed to fetch strategy',
      );
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);

    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:C-POS'));

    fireEvent.change(topBox(), {
      target: { value: 'AGGRESSIVE_PORTFOLIO' },
    });

    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toBe('Failed to fetch strategy');
    expect(document.body.textContent).not.toContain('API request failed');
    await waitFor(() => expect(topBox().value).toBe('CONSERVATIVE_PORTFOLIO'));
    expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS');
  });

  it('going back to the primary book clears an empty-book notice', async () => {
    getStrategyImpl = async (_id, book, stream) => {
      if (book === 'CONSERVATIVE_PORTFOLIO') return strategy({ tag: 'C', positionStream: stream });
      throw new ApiError('x', 404, 'no_data_for_book', 'none yet');
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    const picker = topBox();

    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:C-POS'));

    fireEvent.change(picker, { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    await screen.findByText(/Nothing published for/);

    fireEvent.change(picker, { target: { value: 'CONSERVATIVE_PORTFOLIO' } });
    await waitFor(() => expect(screen.queryByText(/Nothing published for/)).toBeNull());
    expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS');
  });
});

describe('opening straight onto a chosen book', () => {
  const primary = () =>
    strategy({ tag: 'C', books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });
  const aggressive = () =>
    strategy({
      tag: 'A',
      currentValue: 111111,
      portfolio_id: 'AGGRESSIVE_PORTFOLIO',
      books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
    });

  it('loads the chosen book and shows its positions', async () => {
    getStrategyImpl = async () => aggressive();
    render(
      <StrategyDetail strategy={primary()} initialBook="AGGRESSIVE_PORTFOLIO" onBack={() => {}} />,
    );

    expect(topBox().value).toBe('AGGRESSIVE_PORTFOLIO');
    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('AGGRESSIVE_PORTFOLIO:A-POS'),
    );
    expect(getStrategyCalls).toEqual([['trendfollowing', 'AGGRESSIVE_PORTFOLIO', 'system']]);
  });

  it('never shows the primary book while the chosen one is loading', async () => {
    let release: (s: Strategy) => void = () => {};
    getStrategyImpl = () => new Promise<Strategy>(r => { release = r; });
    render(
      <StrategyDetail strategy={primary()} initialBook="AGGRESSIVE_PORTFOLIO" onBack={() => {}} />,
    );

    expect(screen.getByRole('status').textContent).toContain('Loading Trend Following in AGGRESSIVE_PORTFOLIO');
    expect(screen.queryByTestId('positions')).toBeNull();
    expect(screen.queryByText('$523,681.65')).toBeNull();

    release(aggressive());
    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('AGGRESSIVE_PORTFOLIO:A-POS'),
    );
  });

  it('opening on the primary book fetches model positions instead of trusting the QT prop', async () => {
    render(
      <StrategyDetail strategy={primary()} initialBook="CONSERVATIVE_PORTFOLIO" onBack={() => {}} />,
    );
    await waitFor(() => expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS'));
    expect(getStrategyCalls).toEqual([['trendfollowing', 'CONSERVATIVE_PORTFOLIO', 'system']]);
  });

  it('a slow answer for an earlier choice does not overwrite a later one', async () => {
    const pending: Record<string, (s: Strategy) => void> = {};
    getStrategyImpl = (_id, book) => new Promise<Strategy>(r => { pending[book as string] = r; });
    const books = ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO', 'MACRO_BOOK'];
    render(
      <StrategyDetail strategy={strategy({ tag: 'C', books })} onBack={() => {}} />,
    );
    const picker = topBox();

    fireEvent.change(picker, { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    fireEvent.change(picker, { target: { value: 'MACRO_BOOK' } });

    pending.MACRO_BOOK(strategy({ tag: 'M', portfolio_id: 'MACRO_BOOK', books }));
    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('MACRO_BOOK:M-POS'),
    );

    // The first request comes back last. It must be ignored.
    pending.AGGRESSIVE_PORTFOLIO(strategy({ tag: 'A', portfolio_id: 'AGGRESSIVE_PORTFOLIO', books }));
    await new Promise(r => setTimeout(r, 0));
    expect(screen.getByTestId('positions').textContent).toBe('MACRO_BOOK:M-POS');
    expect((picker as HTMLSelectElement).value).toBe('MACRO_BOOK');
  });
});

describe('the book box beside the positions heading', () => {
  const primary = () =>
    strategy({ tag: 'C', books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });

  it('shows the book on screen and offers the others', async () => {
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:C-POS'));
    const box = headingBox();
    expect(box.value).toBe('CONSERVATIVE_PORTFOLIO');
    expect(Array.from(box.options).map(o => o.value)).toEqual([
      'CONSERVATIVE_PORTFOLIO',
      'AGGRESSIVE_PORTFOLIO',
    ]);
  });

  it('switches the whole page to the book chosen in it', async () => {
    getStrategyImpl = async (_id, book, stream) => book === 'AGGRESSIVE_PORTFOLIO' ?
      strategy({
        tag: 'A',
        currentValue: 111111,
        portfolio_id: 'AGGRESSIVE_PORTFOLIO',
        positionStream: stream,
        books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
      }) : strategy({ tag: 'C', positionStream: stream,
        books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:C-POS'));

    fireEvent.change(headingBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });

    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('AGGRESSIVE_PORTFOLIO:A-POS'),
    );
    expect(screen.getByText('$111,111.00')).toBeTruthy();
    // Both boxes read the same book: there is one choice, shown twice.
    expect(headingBox().value).toBe('AGGRESSIVE_PORTFOLIO');
    expect(topBox().value).toBe('AGGRESSIVE_PORTFOLIO');
  });

  it('is not offered for a strategy in one book', () => {
    render(<StrategyDetail strategy={strategy({ tag: 'C' })} onBack={() => {}} />);
    expect(screen.queryByRole('combobox', { name: 'Book for these positions' })).toBeNull();
  });

  it('an empty book offers a way back from inside its notice', async () => {
    getStrategyImpl = async (_id, book, stream) => {
      if (book === 'CONSERVATIVE_PORTFOLIO') return strategy({ tag: 'C', positionStream: stream });
      throw new ApiError('x', 404, 'no_data_for_book', 'none yet');
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:C-POS'));

    fireEvent.change(headingBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    const back = await screen.findByRole('combobox', { name: 'Choose another book' });

    fireEvent.change(back, { target: { value: 'CONSERVATIVE_PORTFOLIO' } });
    await waitFor(() =>
      expect(screen.getByTestId('positions').textContent).toBe('CONSERVATIVE_PORTFOLIO:C-POS'),
    );
  });
});

describe('published configuration follows the selected registry and book', () => {
  const primary = () =>
    strategy({ tag: 'C', books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'] });
  const unavailable = (book: string) => new Response(JSON.stringify({
    api_version: 1, scope: { registry_id: 'trendfollowing', portfolio_id: book },
    read_at: '2026-09-22T15:02:00Z', status: 'unavailable',
    reason: 'not_published', publication: null,
  }), { headers: { 'Content-Type': 'application/json' } });

  it('does not inspect configuration for a book with no portfolio publication', async () => {
    role = 'general_member';
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(unavailable('CONSERVATIVE_PORTFOLIO'));
    getStrategyImpl = async (_id, book, stream) => {
      if (book === 'CONSERVATIVE_PORTFOLIO') return strategy({ tag: 'C', positionStream: stream });
      throw new ApiError('x', 404, 'no_data_for_book', 'none yet');
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    await screen.findByText(/Registry: trendfollowing; book: CONSERVATIVE_PORTFOLIO/);
    fireEvent.change(topBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    await screen.findByText(/Nothing published for Trend Following in/);
    expect(screen.queryByRole('region', { name: 'Published configuration' })).toBeNull();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  });

  it('reverts failed selection and makes a fresh request for the on-screen book', async () => {
    role = 'general_member';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(unavailable('CONSERVATIVE_PORTFOLIO'));
    getStrategyImpl = async (_id, book, stream) => {
      if (book === 'CONSERVATIVE_PORTFOLIO') return strategy({ tag: 'C', positionStream: stream });
      throw new ApiError('x', 503);
    };
    render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    await screen.findByText(/No published configuration for this book/);
    fireEvent.change(topBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    await screen.findByRole('alert');
    expect(screen.getByText(/Registry: trendfollowing; book: CONSERVATIVE_PORTFOLIO/)).toBeTruthy();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(fetchMock.mock.calls[1][0]).toMatch(/configuration\?portfolio_id=CONSERVATIVE_PORTFOLIO$/);
  });

  it('never requests the previous strategy book under a newly supplied registry', async () => {
    role = 'general_member';
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(unavailable('CONSERVATIVE_PORTFOLIO'));
    getStrategyImpl = async (id, book, stream) => strategy({
      id, tag: book === 'AGGRESSIVE_PORTFOLIO' ? 'A' : 'C',
      portfolio_id: book, positionStream: stream,
      books: ['AGGRESSIVE_PORTFOLIO', 'CONSERVATIVE_PORTFOLIO'],
    });
    const view = render(<StrategyDetail strategy={primary()} onBack={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('positions').textContent)
      .toBe('CONSERVATIVE_PORTFOLIO:C-POS'));
    fireEvent.change(topBox(), { target: { value: 'AGGRESSIVE_PORTFOLIO' } });
    await waitFor(() => expect(screen.getByText(/Registry: trendfollowing; book: AGGRESSIVE_PORTFOLIO/)).toBeTruthy());
    view.rerender(<StrategyDetail strategy={strategy({ id: 'newregistry', tag: 'N' })} onBack={() => {}} />);
    expect(screen.queryByText(/Registry: newregistry; book: AGGRESSIVE_PORTFOLIO/)).toBeNull();
    await screen.findByText(/Registry: newregistry; book: CONSERVATIVE_PORTFOLIO/);
    expect(fetchMock.mock.calls.map(call => String(call[0])).some(url =>
      url.includes('/newregistry/configuration?portfolio_id=AGGRESSIVE_PORTFOLIO'))).toBe(false);
  });
});

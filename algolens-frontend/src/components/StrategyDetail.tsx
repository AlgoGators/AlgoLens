import React, { useState, useMemo, useEffect, useCallback, useRef } from 'react';
import { periodReturn } from '../domain/portfolio/periodReturn';
import { filterByPeriod } from '../domain/portfolio/filterByPeriod';
import { formatBarDate } from '../domain/portfolio/formatBarDate';
import {
  breaksWithin,
  latestSegment,
  withBreakGaps,
} from '../domain/portfolio/historySegments';
import { ArrowLeft, TrendingUp, TrendingDown } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts';
import type { PositionStream, Strategy } from '../domain/portfolio/portfolioData';
import { useTheme } from '../adapters/react/ThemeContext';
import { useAuth } from '../adapters/react/useAuth';
import { can } from '../domain/identity/user';
import { FinancialAnalysis } from './FinancialAnalysis';
import { PositionBreakdown } from './PositionBreakdown';
import { PortfolioApiService } from '../infrastructure/api/portfolioApi';
import { QtPreviewApi } from '../infrastructure/api/qtPreviewApi';
import { QtRecovery } from '../infrastructure/api/qtRecovery';
import type { QtProposal } from '../domain/portfolio/qtPreview';
import { qtWorkflowReasonText } from '../domain/portfolio/qtWorkflowReason';
import { QtProposalWorkspace } from './QtProposalWorkspace';
import { QtEditDialog } from './qt-proposal/QtEditDialog';
import { ApiError } from '../infrastructure/api/httpClient';
import { OverrideHistory } from './OverrideHistory';
import { TradingActivity } from './TradingActivity';
import { AlphaAttribution } from './AlphaAttribution';
import { BookSelect } from './BookSelect';
import { ConfigurationInspectionPanel } from './ConfigurationInspectionPanel';

interface StrategyDetailProps {
  strategy: Strategy;
  onBack: () => void;
  /** Re-fetch the book after a manual position edit. */
  onPositionsChanged?: () => void;
  /**
   * The book to open on, when the reader already chose one -- from the book
   * chooser, or a strategy row inside a book. Omitted means the primary.
   */
  initialBook?: string;
}

const sameBook = (a?: string | null, b?: string | null) =>
  (a ?? '').toUpperCase() === (b ?? '').toUpperCase();

export function StrategyDetail({
  strategy,
  onBack,
  onPositionsChanged,
  initialBook,
}: StrategyDetailProps) {
  // Which book is on screen. A strategy can trade a different universe, with
  // different limits, in each book it belongs to; the view used to show the
  // primary one and offer no way to reach the others, so the rest of a
  // strategy's positions were simply unreachable from the app.
  const { theme } = useTheme();
  const { user } = useAuth();
  const actorName = [user?.first_name, user?.last_name].filter(Boolean).join(' ').trim();
  const actorLabel = user ? actorName && user.email ? `${actorName} (${user.email})` :
    actorName || user.email || `Account ${user.id}` : '';
  useEffect(() => {
    if (!user?.id) return;
    try { QtRecovery.activateActor(sessionStorage, user.id); }
    catch { /* Required-workspace actions independently block when recovery storage is unavailable. */ }
  }, [user?.id]);
  const canReadOverrideHistory = can(user, 'view_qt_platform');
  const canViewInternal = can(user, 'view_internal');
  const books = strategy.books ?? (strategy.portfolio_id ? [strategy.portfolio_id] : []);
  const owner = JSON.stringify([strategy.id, strategy.portfolio_id, initialBook, user?.id, user?.capabilities]);
  const defaultBook = initialBook ?? strategy.portfolio_id;
  const [selection, setSelection] = useState<{ owner: string; book?: string; stream: PositionStream }>({
    owner, book: defaultBook, stream: 'system',
  });
  const book = selection.owner === owner ? selection.book : defaultBook;
  const positionStream = selection.owner === owner ? selection.stream : 'system';
  const [refreshKey, setRefreshKey] = useState(0);
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const scope = JSON.stringify([owner, book, positionStream, refreshKey]);
  const contextEpoch = useRef({ scope, epoch: 0 });
  if (contextEpoch.current.scope !== scope) {
    contextEpoch.current = { scope, epoch: contextEpoch.current.epoch + 1 };
  }
  const selectionEpoch = contextEpoch.current.epoch;
  const [loaded, setLoaded] = useState<{ scope: string; owner: string; book?: string;
    stream: PositionStream; refreshKey: number; detail: Strategy } | null>(null);
  const [empty, setEmpty] = useState<{ scope: string; book: string } | null>(null);
  const [failure, setFailure] = useState<{ scope: string; message: string } | null>(null);
  const [bookErrorState, setBookErrorState] = useState<{ owner: string; message: string } | null>(null);
  const [loadingScope, setLoadingScope] = useState<string | null>(null);
  const latestRequest = useRef(0);
  const latestScope = useRef(scope);
  const lastAccepted = useRef<typeof loaded>(null);
  const skipReloadScope = useRef<string | null>(null);
  latestScope.current = scope;

  // A prop from dashboard aggregation is system-scoped. Only a response that
  // proves this exact requested identity may supply page data.
  const shown = loaded?.scope === scope ? loaded.detail : null;
  const emptyBook = empty?.scope === scope ? empty.book : null;
  const requestError = failure?.scope === scope ? failure.message : null;
  const bookError = bookErrorState?.owner === owner ? bookErrorState.message : null;
  const bookLoading = loadingScope === scope;
  const shownPortfolioId = shown?.portfolio_id ?? book;
  const bookOnScreen = emptyBook ?? shown?.portfolio_id ?? book;
  const awaitingBook = !shown && !emptyBook && !requestError;
  const qtSnapshot = positionStream === 'qt' && shown?.positionStream === 'qt';
  const workflowBook = qtSnapshot ? shown?.portfolio_id : undefined;
  const sourceDay = qtSnapshot ? shown?.positionDate : undefined;
  const workflowScope = JSON.stringify([scope, selectionEpoch, workflowBook, sourceDay]);
  const latestWorkflowScope = useRef(workflowScope);
  latestWorkflowScope.current = workflowScope;
  const [workflow, setWorkflow] = useState<{
    scope: string; proposal: QtProposal | null; reason: string;
  } | null>(null);
  const matchingProposal = workflow?.scope === workflowScope ? workflow.proposal : null;
  const workflowRequired = matchingProposal?.capability?.required === true;
  const workflowAvailable = matchingProposal?.capability?.available === true;
  const legacyEditingAllowed = workflowAvailable && matchingProposal?.capability?.required === false;
  const mountWorkspace = canReadOverrideHistory && workflowRequired && workflowAvailable && !!user?.id && !!workflowBook && !!sourceDay;
  const workflowReason = positionStream !== 'qt' ? '' : !qtSnapshot || !workflowBook || !sourceDay
    ? 'QT workflow source identity and date are unavailable. Position changes are disabled.'
    : !user?.id ? 'Sign in before changing QT positions.'
    : workflow?.scope !== workflowScope ? 'Loading QT workflow capability. Position changes are disabled.'
    : workflow.reason;
  const positionEditReason = workflowRequired && workflowAvailable
    ? 'These are the saved QT positions. Use Edit positions to change a quantity: you will review, save, evaluate and confirm it in a window.'
    : workflowReason || shown?.positionEditUnavailableReason;

  // "Edit positions". It only opens the editing window: the QT proposal
  // workspace lives inside <QtEditDialog>, never on the page, and every write
  // stays behind the workspace's own server-checked controls. From Model /
  // System the button first selects QT (the same state the selector holds,
  // nothing else is persisted); the window is then opened only once the QT
  // workspace can actually mount, and the request is dropped if it never can,
  // so an unavailable workflow just leaves its visible reason.
  // The window belongs to one owner/book/stream: changing any of them closes it
  // and forgets that it was ever opened, so a stale workspace never lingers.
  // After a publication the page reloads its data: the window closes while the
  // page loads and opens again with a fresh workspace, which reloads the
  // server's decision review, so nothing from the published choice lingers.
  // The epoch makes leaving and coming back a fresh start, never a revival.
  const editorPlace = JSON.stringify([owner, book, positionStream]);
  const editorEpoch = useRef({ place: editorPlace, epoch: 0 });
  if (editorEpoch.current.place !== editorPlace) {
    editorEpoch.current = { place: editorPlace, epoch: editorEpoch.current.epoch + 1 };
  }
  const editorKey = JSON.stringify([editorPlace, editorEpoch.current.epoch]);
  const [editor, setEditor] = useState<{ key: string; open: boolean; everOpened: boolean } | null>(null);
  const editorOpen = editor?.key === editorKey && editor.open;
  const editorEverOpened = editor?.key === editorKey && editor.everOpened;
  const openEditor = useCallback(
    () => setEditor({ key: editorKey, open: true, everOpened: true }), [editorKey]);
  const closeEditor = useCallback(
    () => setEditor(prior => prior ? { ...prior, open: false } : prior), []);
  const [pendingOpenOwner, setPendingOpenOwner] = useState<string | null>(null);
  const pendingOpen = pendingOpenOwner === owner;
  const editInQt = () => {
    setPendingOpenOwner(owner);
    setSelection({ owner, book, stream: 'qt' });
    setBookErrorState(null);
  };
  useEffect(() => {
    if (!pendingOpen) return;
    if (positionStream !== 'qt') { setPendingOpenOwner(null); return; }
    if (mountWorkspace) { setPendingOpenOwner(null); openEditor(); return; }
    if (requestError || emptyBook || (!!shown && !qtSnapshot) || (workflow?.scope === workflowScope)) setPendingOpenOwner(null);
  }, [pendingOpen, positionStream, mountWorkspace, requestError, emptyBook, shown, qtSnapshot, workflow, workflowScope, openEditor]);
  // Everything the button needs to say, for an internal reader on any stream.
  // Legacy editing keeps its own controls, so nothing new is offered there.
  const legacyEditingOpen = legacyEditingAllowed && shown?.positionsEditable === true;
  const editEntryReason = legacyEditingOpen ? null
    : positionStream === 'system' ? (user?.id ? null : 'Sign in before changing QT positions.')
    : mountWorkspace ? null
    : workflowReason || shown?.positionEditUnavailableReason || 'QT position changes are unavailable for this book.';
  const editEntryAction = legacyEditingOpen || editEntryReason ? undefined
    : positionStream === 'system' ? editInQt : openEditor;

  useEffect(() => {
    if (!canReadOverrideHistory || !qtSnapshot || !workflowBook || !sourceDay || !user?.id) return;
    const controller = new AbortController();
    let live = true;
    void (async () => {
      try {
        const proposal = await QtPreviewApi.getProposal(workflowBook, controller.signal);
        if (!live || latestWorkflowScope.current !== workflowScope) return;
        if (proposal.book_id !== workflowBook || proposal.source_day !== sourceDay ||
            typeof proposal.capability?.available !== 'boolean' || typeof proposal.capability?.required !== 'boolean') {
          throw new Error('unmatched_workflow_capability');
        }
        setWorkflow({ scope: workflowScope, proposal,
          reason: proposal.capability.available ? '' :
            qtWorkflowReasonText(proposal.read_only_reason) });
      } catch (error) {
        if (!live || latestWorkflowScope.current !== workflowScope ||
            (error instanceof DOMException && error.name === 'AbortError')) return;
        setWorkflow({ scope: workflowScope, proposal: null,
          reason: 'QT workflow capability is unavailable. Position changes are disabled.' });
      }
    })();
    return () => { live = false; controller.abort(); };
  }, [canReadOverrideHistory, qtSnapshot, workflowBook, sourceDay, workflowScope, user?.id]);

  useEffect(() => {
    if (!book) {
      setFailure({ scope, message: 'No book is available for this strategy.' });
      return;
    }
    if (skipReloadScope.current === scope) {
      skipReloadScope.current = null;
      setLoadingScope(null);
      return;
    }
    const request = ++latestRequest.current;
    setLoadingScope(scope);
    setFailure(null);
    setEmpty(null);
    const load = async () => {
      try {
        const detail = await PortfolioApiService.getStrategy(strategy.id, book, positionStream);
        if (request !== latestRequest.current || latestScope.current !== scope) return;
        if (detail.id !== strategy.id || !sameBook(detail.portfolio_id, book)
          || (detail.positionStream != null && detail.positionStream !== positionStream)) {
          throw new Error('The strategy response does not match the requested book and position stream.');
        }
        const accepted = { scope, owner, book, stream: positionStream, refreshKey, detail };
        lastAccepted.current = accepted;
        setLoaded(accepted);
        setBookErrorState(null);
      } catch (err) {
        if (request !== latestRequest.current || latestScope.current !== scope) return;
        if (err instanceof ApiError && err.code === 'no_data_for_book') {
          setEmpty({ scope, book });
          setBookErrorState(null);
        } else {
          const message = (err instanceof ApiError && err.serverMessage)
            || (err instanceof Error && !(err instanceof ApiError) ? err.message : null)
            || `Could not load ${book}.`;
          const prior = lastAccepted.current;
          if (prior && prior.owner === owner && prior.stream === positionStream
            && prior.book && !sameBook(prior.book, book) && prior.refreshKey === refreshKey) {
            // A failed book change can return to the last proven book. A
            // failed stream change cannot show the other stream as a fallback.
            skipReloadScope.current = prior.scope;
            setSelection({ owner, book: prior.book, stream: positionStream });
            setBookErrorState({ owner, message });
          } else {
            setFailure({ scope, message });
          }
        }
      } finally {
        if (request === latestRequest.current && latestScope.current === scope) {
          setLoadingScope(null);
        }
      }
    };
    void load();
    return () => { latestRequest.current += 1; };
  }, [scope, owner, book, positionStream, strategy.id, refreshKey]);

  const selectBook = (target: string) => {
    setPendingOpenOwner(null);
    setSelection({ owner, book: target, stream: positionStream });
    setBookErrorState(null);
  };

  const selectStream = (stream: PositionStream) => {
    setPendingOpenOwner(null);
    setSelection({ owner, book, stream });
    setBookErrorState(null);
  };

  const hasSeveralBooks = books.length > 1;
  // The same box, wherever the reader is when they want to switch: beside the
  // positions heading, in the book row at the top (which the other two tabs
  // rely on), and inside the "nothing published" notice so an empty book is
  // never a dead end. One piece of state behind all three.
  const bookBox = (ariaLabel: string, id?: string) => (
    <BookSelect
      id={id}
      books={books}
      primary={strategy.portfolio_id}
      value={book}
      onChange={selectBook}
      ariaLabel={ariaLabel}
      theme={theme}
    />
  );

  // A QT edit landed. Re-read the explicit QT view; the dashboard refresh
  // remains independently pinned to Model / System.
  const handlePositionsChanged = useCallback(() => {
    if (positionStream !== 'qt' || latestScope.current !== scope || contextEpoch.current.epoch !== selectionEpoch) return;
    setHistoryRefreshKey(key => key + 1);
    setRefreshKey(key => key + 1);
    onPositionsChanged?.();
  }, [positionStream, scope, selectionEpoch, onPositionsChanged]);

  const [selectedPeriod, setSelectedPeriod] = useState('1M');
  const [selectedTab, setSelectedTab] = useState<'positions' | 'analysis' | 'activity'>('positions');
  const periods = ['1W', '1M', '3M', '1Y', 'ALL'];

  // Filter data based on selected period
  const filteredData = useMemo(
    () => filterByPeriod(shown?.historicalData ?? [], selectedPeriod),
    [selectedPeriod, shown?.historicalData]
  );

  // Where this window's curve changes book. Only breaks a reader can actually
  // see on the chart are worth drawing or naming.
  const visibleBreaks = useMemo(
    () => breaksWithin(filteredData, shown?.historyBreaks),
    [filteredData, shown?.historyBreaks]
  );

  // The plotted series lifts the pen at each break. `connectNulls` is
  // deliberately not set: connecting them is exactly what must not happen.
  const plotted = useMemo(
    () => withBreakGaps(filteredData, shown?.historyBreaks),
    [filteredData, shown?.historyBreaks]
  );

  // The window's return, measured over the newest unbroken stretch only. A
  // return that spans a book change adds up two different portfolios.
  const windowReturn = useMemo(() => {
    if (!shown || shown.dataAvailable === false) return null;
    return periodReturn(latestSegment(filteredData, shown.historyBreaks));
  }, [filteredData, shown]);
  // The window's direction, for chart colours. An unknown window is
  // drawn in the neutral-positive colour rather than not drawn at all.
  const gaining = (windowReturn?.value ?? 0) >= 0;

  const periodLabel = selectedPeriod === 'ALL' ? 'All Time' : selectedPeriod;

  return (
    <div>
      <button
        onClick={onBack}
        className={`flex items-center gap-2 mb-6 px-4 py-2 rounded-lg transition-colors ${theme === 'dark'
          ? 'text-gray-300 hover:text-white hover:bg-gray-900'
          : 'text-gray-700 hover:text-black hover:bg-gray-100'
          }`}
      >
        <ArrowLeft className="w-5 h-5" />
        <span>Back to Strategies</span>
      </button>

      <div className="mb-6">
        <div className="flex items-start justify-between">
          <div className="flex-1">
            <h1 className="text-2xl md:text-3xl mb-1">{strategy.name}</h1>
            <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}>
              {strategy.description}
            </p>
            <div className={`text-sm mt-2 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              {!shown ? (
                requestError ? <>Selected book and position stream unavailable.</> :
                emptyBook ? <>No result for the selected book and position stream.</> :
                <>System-model performance and positions loading for the selected book and stream.</>
              ) : shown.dataAvailable === false ? (
                <>System-model performance unavailable{shown.positionDate ? `; positions snapshot ${shown.positionDate}` : ''}.</>
              ) : shown.resultDate ? (
                <>System-model performance as of {shown.resultDate}{shown.positionDate && shown.positionDate !== shown.resultDate
                  ? `; positions snapshot ${shown.positionDate}` : ''}.</>
              ) : shown.lastUpdate}
            </div>
          </div>
        </div>

        {/* Which book every number on this page belongs to. Always stated, not
            only when there is a choice: a strategy's value, history, positions
            and limits are all per book, and a reader should never have to
            infer which one they are looking at. */}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <span className={`text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-500' : 'text-gray-500'}`}>
            Book
          </span>
          {hasSeveralBooks ? (
            bookBox('Which book to show', 'book-view')
          ) : (
            <span
              data-testid="book-name"
              className={`rounded-lg border px-2 py-1 text-sm font-mono ${
                theme === 'dark' ? 'border-gray-800 text-gray-200' : 'border-gray-200 text-gray-800'
              }`}
            >
              {bookOnScreen}
            </span>
          )}
          <span className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-500'}`}>
            {books.length > 1
              ? `In ${books.length} books. Everything below is for the one selected; each has its own positions, history and risk limits.`
              : 'Everything below is for this book.'}
          </span>
          <label className="flex items-center gap-2 text-sm" htmlFor="position-stream-view">
            <span>Position stream</span>
            <select
              id="position-stream-view"
              aria-label="Position stream"
              value={positionStream}
              onChange={event => selectStream(event.target.value as PositionStream)}
              className={`rounded-lg border px-2 py-1 ${theme === 'dark'
                ? 'border-gray-700 bg-gray-900 text-gray-200'
                : 'border-gray-300 bg-white text-gray-800'}`}
            >
              <option value="system">Model / System</option>
              <option value="qt">QT</option>
            </select>
          </label>
          <span className={`text-xs ${theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}`}>
            Selector changes positions only. Performance and trading activity remain Model / System.
          </span>
          {/* A refresh of the book already on screen. Loading a different
              book is announced below, in place of the numbers. */}
          {bookLoading && !awaitingBook && (
            <span className={`text-xs ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
              Loading…
            </span>
          )}
        </div>

        {bookError && (
          <div role="alert" className="mt-3 rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
            {bookError}
          </div>
        )}
      </div>

      {canReadOverrideHistory && shown && bookOnScreen && (
        <ConfigurationInspectionPanel
          registryId={strategy.id}
          portfolioId={bookOnScreen}
          userId={user?.id}
          allowed={canViewInternal}
        />
      )}

      {awaitingBook ? (
        <div
          role="status"
          aria-busy="true"
          className={`rounded-lg border px-6 py-10 text-center text-sm ${
            theme === 'dark' ? 'border-gray-800 text-gray-400' : 'border-gray-200 text-gray-500'
          }`}
        >
          Loading {strategy.name} in <span className="font-mono">{book}</span>…
        </div>
      ) : requestError ? (
        <div role="alert" className="rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm text-red-600 dark:text-red-400">
          {requestError}
        </div>
      ) : emptyBook ? (
        <div
          role="status"
          className={`rounded-lg border px-6 py-10 text-center ${
            theme === 'dark' ? 'border-gray-800 bg-gray-900 text-gray-300' : 'border-gray-200 bg-gray-50 text-gray-700'
          }`}
        >
          <p className="text-base mb-2">
            Nothing published for {strategy.name} in{' '}
            <span className="font-mono">{emptyBook}</span> yet.
          </p>
          <p className={`text-sm ${theme === 'dark' ? 'text-gray-500' : 'text-gray-500'}`}>
            It was added to this book, but the engine has not traded it here. Its
            positions, history and risk limits in this book start with the first
            run that includes it.
          </p>
          {hasSeveralBooks && (
            <div className="mt-4 flex items-center justify-center gap-2 text-sm">
              <span>See another book:</span>
              {bookBox('Choose another book')}
            </div>
          )}
        </div>
      ) : shown ? (
      <>
      <div className="mb-6">
        <div className="text-3xl md:text-4xl mb-2">
          {shown.dataAvailable === false || shown.currentValue === null ? '—' :
            `$${shown.currentValue.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
        </div>
        {/* Null means the window holds fewer than two points, so there is no
            return to state. This used to state "$0.00 (+0.00%)" -- a flat
            period, rather than a period nothing is known about. */}
        {windowReturn === null ? (
          <div className={`text-lg ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
            &mdash; no data for {periodLabel}
          </div>
        ) : (
          <div className={`flex items-center gap-2 text-lg ${gaining ? 'text-orange-500' : 'text-red-500'}`}>
            {gaining ? <TrendingUp className="w-5 h-5" /> : <TrendingDown className="w-5 h-5" />}
            <span>
              ${Math.abs(windowReturn.value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({windowReturn.percent >= 0 ? '+' : ''}{windowReturn.percent.toFixed(2)}%) {periodLabel}
            </span>
          </div>
        )}
      </div>

      <div className="mb-4">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={plotted}>
            <defs>
              <linearGradient id="stratLineGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={gaining ? "#f97316" : "#ef4444"} stopOpacity={theme === 'dark' ? 0.2 : 0.1} />
                <stop offset="100%" stopColor={gaining ? "#f97316" : "#ef4444"} stopOpacity={0} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="date"
              hide
            />
            <YAxis
              hide
              domain={['dataMin - 500', 'dataMax + 500']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                borderRadius: '8px',
                boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
                color: theme === 'dark' ? '#fff' : '#000'
              }}
              formatter={(value) =>
                typeof value === 'number'
                  ? [`$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`, 'Value']
                  : ['—', 'Value']
              }
              labelFormatter={(label) => formatBarDate(label as string)}
            />
            <Line
              type="linear"
              dataKey="value"
              stroke={gaining ? "#f97316" : "#ef4444"}
              strokeWidth={2}
              dot={false}
              fill="url(#stratLineGradient)"
            />
          </LineChart>
        </ResponsiveContainer>
        {visibleBreaks.map(brk => (
          <p
            key={brk.date}
            className={`mt-2 text-xs ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}
          >
            History restarts {formatBarDate(brk.date)}: moved from{' '}
            {brk.fromPortfolioId} to {brk.toPortfolioId}. The
            line breaks because the two sides are different portfolios, and the
            window return above measures only the stretch since the move.
          </p>
        ))}
      </div>

      {/* Is QT's judgement adding value? Renders an explanation instead of a
          chart until both streams exist. */}
      <div className="mb-8">
        <AlphaAttribution
          equityByStream={shown.equityByStream}
          historyBreaks={shown.historyBreaks}
          theme={theme}
        />
      </div>

      <div className={`flex items-center justify-between mb-8 border-b ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
        {periods.map((period) => (
          <button
            key={period}
            onClick={() => setSelectedPeriod(period)}
            className={`px-3 py-3 text-sm transition-colors relative ${selectedPeriod === period
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            {period}
            {selectedPeriod === period && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
        ))}
      </div>

      {/* Tab Navigation */}
      <div className={`flex flex-wrap items-start justify-between gap-3 mb-6 border-b ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <button
            onClick={() => setSelectedTab('positions')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'positions'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Positions
            {selectedTab === 'positions' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
          <button
            onClick={() => setSelectedTab('analysis')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'analysis'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Financial Analysis
            {selectedTab === 'analysis' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
          <button
            onClick={() => setSelectedTab('activity')}
            className={`pb-3 px-1 transition-colors relative ${selectedTab === 'activity'
              ? 'text-orange-500'
              : theme === 'dark'
                ? 'text-gray-400 hover:text-white'
                : 'text-gray-500 hover:text-gray-900'
              }`}
          >
            Trading Activity
            {selectedTab === 'activity' && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-500" />
            )}
          </button>
        </div>

        <button
          onClick={onBack}
          className={`flex shrink-0 items-center gap-2 px-4 py-2 rounded-lg transition-colors ${theme === 'dark'
              ? 'text-gray-300 hover:text-white hover:bg-gray-900'
              : 'text-gray-700 hover:text-black hover:bg-gray-100'
            }`}
        >
          <ArrowLeft className="w-5 h-5" />
          <span>Back to Strategies</span>
        </button>
      </div>

      {/* Tab Content */}
      {selectedTab === 'positions' && (
        <>
          <PositionBreakdown
            key={scope}
            positions={shown.positions}
            positionStream={shown.positionStream}
            positionStrategyNames={shown.positionStrategyNames}
            strategyId={strategy.id}
            portfolioId={shown.portfolio_id ?? book}
            positionDate={shown.positionDate}
            positionsEditable={legacyEditingAllowed && shown.positionsEditable === true}
            positionEditUnavailableReason={positionEditReason}
            onEditInWorkspace={editEntryAction}
            workspaceEditUnavailableReason={editEntryReason}
            books={books}
            bookControl={hasSeveralBooks ? bookBox('Book for these positions') : undefined}
            onEdited={handlePositionsChanged}
          />
          {workflowReason && <p role="status" aria-label="QT workflow availability"
            className={`mt-4 text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
            {workflowReason}
          </p>}
          {mountWorkspace && workflowBook && sourceDay && user?.id && (
            <QtEditDialog open={editorOpen} keepMounted={editorEverOpened}
              title={`Edit QT positions - ${workflowBook}`} onClose={closeEditor}
              returnFocusTo={() => document.querySelector<HTMLElement>('[data-qt-edit-entry]')}>
              <QtProposalWorkspace embedded key={workflowScope} actorId={user.id} actorLabel={actorLabel} bookId={workflowBook}
                sourceDay={sourceDay} focusStrategyName={strategy.name} onPublished={handlePositionsChanged} />
            </QtEditDialog>
          )}
          {/* The audit trail sits directly under the book it describes. It was
              being written on every edit and read by nobody. */}
          {canReadOverrideHistory && shownPortfolioId && (
            <div className="mt-8">
              <OverrideHistory
                strategyId={strategy.id}
                portfolioId={shownPortfolioId}
                refreshKey={historyRefreshKey}
              />
            </div>
          )}
        </>
      )}

      {selectedTab === 'analysis' && (
        <FinancialAnalysis
          metrics={shown.metrics}
          executionsAvailable={shown.executionsAvailable}
          executionUnavailableReason={shown.executionUnavailableReason}
          executionDate={shown.executionDate}
        />
      )}

      {selectedTab === 'activity' && (
        <TradingActivity
          executions={shown.executions}
          finalizedPositions={shown.finalizedPositions}
          activityStream={shown.activityStream}
          finalizedPositionsAvailable={shown.finalizedPositionsAvailable}
          executionsAvailable={shown.executionsAvailable}
          executionUnavailableReason={shown.executionUnavailableReason}
          executionDate={shown.executionDate}
        />
      )}
      </>
      ) : null}
    </div>
  );
}

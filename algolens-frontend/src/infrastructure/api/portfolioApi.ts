import type { Strategy, PortfolioData, HistoricalDataPoint, HeldCorrelations, PositionStream } from '../../domain/portfolio/portfolioData';
import type { IncubatingStrategy, IncubationPerformance } from '../../domain/portfolio/incubationData';
import type { RiskCheck } from '../../domain/portfolio/positionEdit';
import { aggregateCommonCoverage } from '../../domain/portfolio/commonCoverage';
import type {
  AssignmentCheck,
  PortfolioSummary,
} from '../../domain/portfolio/portfolioAssignment';
import { API_BASE_URL, ApiError, deleteWithAuth, fetchWithAuth, log, postWithAuth, putWithAuth } from './httpClient';

export function sanitizePositionStrategyNames(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  if (value.some(name => typeof name !== 'string' || name.trim().length === 0)) {
    return [];
  }
  // Engine names are opaque database keys. Validate with trim, but never
  // normalize the value into a different key; deduplicate only exact strings.
  return [...new Set(value as string[])];
}

type PortfolioTotalSource = Pick<Strategy, 'dataAvailable' | 'invested' | 'currentValue'>;

export function aggregatePortfolioTotals(strategies: PortfolioTotalSource[]): Pick<
  PortfolioData,
  'totalValue' | 'totalInvested' | 'totalReturn' | 'totalReturnPercent'
> {
  const included = strategies.filter(
    strategy => strategy.dataAvailable !== false && strategy.currentValue !== null,
  );
  const anyBasisUnknown = included.some(strategy => strategy.invested === null);
  const totalInvested = included.reduce(
    (sum, strategy) => sum + (strategy.invested ?? 0),
    0,
  );
  const totalValue = included.reduce((sum, strategy) => sum + (strategy.currentValue ?? 0), 0);
  const totalReturn = anyBasisUnknown ? null : totalValue - totalInvested;
  const totalReturnPercent = totalReturn === null || totalInvested <= 0
    ? null
    : (totalReturn / totalInvested) * 100;
  return { totalValue, totalInvested, totalReturn, totalReturnPercent };
}

/**
 * A strategy the engine has published nothing for.
 *
 * Every measured field is null and `dataAvailable` is false. It used to be
 * zeros, which relied on every caller remembering to check the flag -- and a
 * zero that leaks past that check reads as a measurement ("0.00x leverage",
 * "$0 margin posted"). A null renders as an em dash wherever it lands.
 */
function placeholderStrategy(summary: { id: string; name: string }): Strategy {
  return {
    id: summary.id,
    name: summary.name,
    description: '',
    dataAvailable: false,
    invested: null,
    currentValue: null,
    resultSource: 'qt',
    resultDate: null,
    return: null,
    returnPercent: null,
    positions: [],
    positionStream: null,
    positionStrategyNames: [],
    positionDate: null,
    positionsEditable: false,
    positionEditUnavailableReason: 'No dated QT snapshot is available.',
    historicalData: [],
    bestDay: null,
    worstDay: null,
    metrics: {
      volatility: null, sharpeRatio: null, sortinoRatio: null,
      downsideDeviation: null, maxDrawdown: null, winRate: null,
      executionsToday: null,
      avgWin: null, avgLoss: null, profitFactor: null, dailyReturn: null,
      cumulativeReturn: null, annualizedReturn: null, grossLeverage: null,
      netLeverage: null, portfolioLeverage: null, marginPosted: null,
      equityToMarginRatio: null, marginCushion: null, totalNotional: null,
      unrealizedPnL: null, realizedPnL: null, totalCommissions: null,
      netPnL: null, cashAvailable: null, currentPortfolioValue: null,
    },
    executions: [],
    executionsAvailable: false,
    executionDate: null,
    executionUnavailableReason: 'QT result date is unavailable; fills cannot be attributed to a reporting day.',
    finalizedPositions: [],
    activityStream: null,
    finalizedPositionsAvailable: false,
    managers: [],
    lastUpdate: '',
  };
}

export class PortfolioApiService {
  // Debug method to test backend connectivity (call from browser console)
  static async testConnectivity(): Promise<void> {
    log('info', '=== CONNECTIVITY TEST START ===');
    log('info', `Testing connection to: ${API_BASE_URL}`);

    // Test 1: Check if we can reach the backend at all (health endpoint)
    try {
      log('info', 'Test 1: Attempting health check...');
      const healthUrl = `${API_BASE_URL}/health`;
      const response = await fetch(healthUrl, { method: 'GET' });
      log('info', `Health check response: ${response.status} ${response.statusText}`);
      const data = await response.json();
      log('info', 'Health check data:', data);
    } catch (e) {
      log('error', 'Health check FAILED:', e);
    }

    // Test 2: Check auth endpoint
    try {
      log('info', 'Test 2: Testing auth endpoint (should get 401 without token)...');
      const authTestUrl = `${API_BASE_URL}/portfolio/strategies`;
      const response = await fetch(authTestUrl, { method: 'GET' });
      log('info', `Auth test response: ${response.status} - Expected 401 if no token, 200 if CORS misconfigured`);
    } catch (e) {
      log('error', 'Auth endpoint test FAILED (likely CORS issue):', e);
    }

    // Test 3: Check the authenticated request using the session cookie
    try {
      log('info', 'Test 3: Testing authenticated request with session cookie...');
      const authTestUrl = `${API_BASE_URL}/portfolio/strategies`;
      const response = await fetch(authTestUrl, {
        method: 'GET',
        credentials: 'include',
      });
      log('info', `Authenticated request response: ${response.status} ${response.statusText} (200 if logged in, 401 if not)`);
      if (response.ok) {
        const data = await response.json();
        log('info', 'Response data:', data);
      } else {
        const text = await response.text();
        log('error', 'Error response body:', text);
      }
    } catch (e) {
      log('error', 'Authenticated request FAILED:', e);
    }

    log('info', '=== CONNECTIVITY TEST COMPLETE ===');
  }


  /**
   * One strategy's detail, scoped to one book.
   *
   * Omitting `portfolioId` gets the primary book. The positions-only selector
   * defaults to model/system; dashboard aggregation asks for QT explicitly.
   */
  static async getStrategy(
    strategyId: string,
    portfolioId?: string,
    positionStream: PositionStream = 'system',
  ): Promise<Strategy> {
    log('info', `getStrategy(${strategyId}) called`);
    const query = new URLSearchParams({ position_stream: positionStream });
    if (portfolioId) query.set('portfolio_id', portfolioId);
    const url = `${API_BASE_URL}/portfolio/strategy/${strategyId}?${query.toString()}`;
    log('info', `Fetching strategy from: ${url}`);

    const response = await fetchWithAuth(url);
    const data = await response.json();

    log('info', `Strategy ${strategyId} response:`, {
      id: data.id,
      name: data.name,
      invested: data.invested,
      currentValue: data.currentValue,
      positionsCount: data.positions?.length,
      historicalDataCount: data.historicalData?.length,
    });

    return {
      ...data,
      positionStrategyNames: sanitizePositionStrategyNames(data.positionStrategyNames),
    };
  }

  static async getAllStrategies(): Promise<Strategy[]> {
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);
    const data = await response.json();
    return data.strategies;
  }

  /**
   * Correlations between the instruments the fund currently holds.
   *
   * Computed by the API from futures_data.ohlcv_1d -- the same table every
   * market price on the site comes from -- so a correlation and the price
   * beside it cannot disagree.
   */
  static async getCorrelations(): Promise<HeldCorrelations> {
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/correlations`);
    const data = await response.json();
    return {
      symbols: data.symbols ?? [],
      matrix: data.matrix ?? [],
      observations: data.observations ?? 0,
      symbolsWithoutPrices: data.symbolsWithoutPrices ?? [],
    };
  }

  static async getIncubationStrategies(): Promise<IncubatingStrategy[]> {
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/incubation`);
    const data = await response.json();
    return data.incubating_strategies || [];
  }

  static async getIncubationPerformance(strategyId: string): Promise<IncubationPerformance> {
    const encodedId = encodeURIComponent(strategyId);
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/incubation/${encodedId}/performance`);
    const data = await response.json();
    return {
      positions: data.positions || [],
      equity_curve: data.equity_curve || [],
    };
  }

  static async getPortfolioData(): Promise<PortfolioData> {
    log('info', '=== getPortfolioData() START ===');

    // Fetch all strategies
    log('info', `Fetching strategies from: ${API_BASE_URL}/portfolio/strategies`);
    const strategiesResponse = await fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);

    log('info', 'Parsing strategies response JSON...');
    const strategiesData = await strategiesResponse.json();
    log('info', 'Strategies data received:', strategiesData);

    const strategySummaries = strategiesData.strategies;
    log('info', `Found ${strategySummaries?.length || 0} strategy summaries`);

    if (!strategySummaries || strategySummaries.length === 0) {
      log('warn', 'No strategies found in response');
    }

    // Fetch detailed data for each strategy.
    //
    // A missing result can coexist with a real QT position snapshot. Ask for
    // detail regardless of the summary; only a genuinely empty book gets a
    // placeholder. Other API failures remain failures.
    log('info', 'Fetching detailed data for each strategy...');
    const strategies: Strategy[] = await Promise.all(
      strategySummaries.map(async (summary: any, index: number) => {
        log('info', `Fetching strategy ${index + 1}/${strategySummaries.length}: ${summary.id}`);
        try {
          const strategy = await this.getStrategy(summary.id, undefined, 'qt');
          log('info', `Strategy ${summary.id} fetched successfully`);
          return strategy;
        } catch (error) {
          if (error instanceof ApiError && error.code === 'no_data_for_book') {
            return placeholderStrategy(summary);
          }
          throw error;
        }
      })
    );
    log('info', `All ${strategies.length} strategies fetched`);

    // Portfolio totals cover only the strategies the engine has actually
    // published. The count of the rest is carried alongside so the headline can
    // say it is partial -- a total that quietly omits a strategy is the bug
    // this replaces.
    log('info', 'Calculating portfolio totals...');
    const priced = strategies.filter(s => s.dataAvailable !== false && s.currentValue !== null);
    const strategiesAwaitingData = strategies.length - priced.length;
    // The known bases may still be summed for disclosure, but a missing basis
    // makes aggregate return unknowable rather than turning that basis into $0.
    const { totalInvested, totalValue, totalReturn, totalReturnPercent } =
      aggregatePortfolioTotals(priced);

    // Aggregate historical data
    log('info', 'Aggregating historical data...');
    const { points: historicalData, coverage: historicalCoverage } = aggregateCommonCoverage(
      priced.map(strategy => ({
        id: strategy.id,
        points: strategy.historicalData,
        historyBreaks: strategy.historyBreaks,
      })),
    );

    const result = {
      totalValue,
      totalInvested,
      totalReturn,
      totalReturnPercent,
      strategies,
      historicalData,
      historicalCoverage,
      strategiesAwaitingData,
    };

    log('info', '=== getPortfolioData() SUCCESS ===', {
      totalValue,
      totalInvested,
      totalReturn,
      totalReturnPercent,
      strategiesCount: strategies.length,
      historicalDataPoints: historicalData.length,
    });

    return result;
  }

  /**
   * Write one position into the qt stream.
   *
   * Returns the outcome rather than throwing, because a 409 is not an error the
   * caller should swallow: it means the write breached a published risk limit
   * and needs a second, deliberate acknowledgement. Collapsing that into a
   * thrown Error is how a UI ends up silently retrying and disabling the gate.
   */
  static async savePosition(input: {
    strategy_id: string;
    /** Exact engine-owned identity from the selected QT snapshot row. */
    strategy_name: string;
    symbol: string;
    quantity: string | number;
    average_price?: string | number | null;
    reason: string;
    acknowledge_risk?: boolean;
    /**
     * Which book. Omitting it is only safe for a strategy in exactly one; the
     * server answers 409 ambiguous_book otherwise rather than guessing.
     */
    portfolio_id?: string;
  }): Promise<
    | { outcome: 'saved'; risk_check: RiskCheck }
    | { outcome: 'needs_acknowledgement'; risk_check: RiskCheck }
    | { outcome: 'needs_book'; books: string[] }
    | { outcome: 'rejected'; message: string }
  > {
    const response = await postWithAuth(`${API_BASE_URL}/portfolio/positions`, input);
    const data = await response.json().catch(() => ({}));

    if (response.status === 201) {
      return { outcome: 'saved', risk_check: data.risk_check };
    }
    // A 409 carrying risk_check is the acknowledgeable one. The other 409
    // (an unresolvable strategy_name) has no risk_check and is a flat refusal.
    if (response.status === 409 && data.risk_check) {
      return { outcome: 'needs_acknowledgement', risk_check: data.risk_check };
    }
    // The third 409: the strategy is in several books and the request did not
    // say which. Not a refusal -- the server hands back the choices so the
    // caller can ask, rather than guess and write into the wrong universe.
    if (response.status === 409 && data.code === 'ambiguous_book' && Array.isArray(data.books)) {
      return { outcome: 'needs_book', books: data.books as string[] };
    }
    return { outcome: 'rejected', message: data.error || `Request failed (${response.status})` };
  }

  /**
   * Move a strategy through the incubation lifecycle.
   *
   * All three transitions take a reason and are recorded in
   * trading.strategy_lifecycle_log. They existed on the API from the start with
   * nothing calling them, so the trial workflow could only be driven with curl.
   */
  static async changeIncubation(
    strategyId: string,
    action: 'start' | 'promote' | 'retire',
    body: { reason: string; mock_capital?: number },
  ): Promise<{ outcome: 'ok' } | { outcome: 'rejected'; message: string }> {
    const response = await postWithAuth(
      `${API_BASE_URL}/portfolio/incubation/${encodeURIComponent(strategyId)}/${action}`,
      body,
    );
    if (response.ok) return { outcome: 'ok' };
    const data = await response.json().catch(() => ({}));
    const messages: Record<string, string> = {
      open_positions: 'Close every effective position in every book before changing this lifecycle.',
      positions_unavailable: 'Reliable position evidence is unavailable, so this lifecycle change was blocked.',
    };
    return {
      outcome: 'rejected',
      message: messages[data.error] || 'The lifecycle change was rejected. Refresh and try again.',
    };
  }

  static async getBooks(): Promise<Book[]> {
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/books`);
    const data = await response.json();
    return data.books || [];
  }

  static async createBook(input: {
    portfolio_id: string;
    name?: string;
    description?: string;
  }): Promise<{ outcome: 'created'; book: Book } | { outcome: 'rejected'; message: string }> {
    const response = await postWithAuth(`${API_BASE_URL}/portfolio/books`, input);
    const data = await response.json().catch(() => ({}));
    if (response.ok) return { outcome: 'created', book: data };
    return { outcome: 'rejected', message: data.error || `Request failed (${response.status})` };
  }

  static async deleteBook(
    portfolioId: string,
  ): Promise<{ outcome: 'deleted' } | { outcome: 'rejected'; message: string }> {
    const response = await deleteWithAuth(
      `${API_BASE_URL}/portfolio/books/${encodeURIComponent(portfolioId)}`,
    );
    if (response.ok) return { outcome: 'deleted' };
    const data = await response.json().catch(() => ({}));
    return { outcome: 'rejected', message: data.error || `Request failed (${response.status})` };
  }

  /**
   * Put a strategy in a book. It keeps every book it is already in, so this
   * takes nothing away and needs no acknowledgement.
   */
  static async addStrategyToBook(input: {
    portfolio_id: string;
    strategy_id: string;
    reason?: string;
  }): Promise<{ outcome: 'saved' } | { outcome: 'rejected'; message: string }> {
    const response = await postWithAuth(
      `${API_BASE_URL}/portfolio/books/${encodeURIComponent(input.portfolio_id)}/strategies`,
      { strategy_id: input.strategy_id, reason: input.reason ?? '' },
    );
    if (response.ok) return { outcome: 'saved' };
    const data = await response.json().catch(() => ({}));
    return { outcome: 'rejected', message: data.error || `Request failed (${response.status})` };
  }

  /**
   * Take a strategy out of a book. A 409 carrying assignment_check is the
   * acknowledgeable one; last_book and a retired strategy are flat refusals.
   */
  static async removeStrategyFromBook(input: {
    portfolio_id: string;
    strategy_id: string;
    reason: string;
    acknowledge?: boolean;
  }): Promise<
    | { outcome: 'saved' }
    | { outcome: 'needs_acknowledgement'; assignment_check: AssignmentCheck }
    | { outcome: 'rejected'; message: string }
  > {
    const response = await deleteWithAuth(
      `${API_BASE_URL}/portfolio/books/${encodeURIComponent(input.portfolio_id)}` +
        `/strategies/${encodeURIComponent(input.strategy_id)}`,
      { reason: input.reason, acknowledge: Boolean(input.acknowledge) },
    );
    const data = await response.json().catch(() => ({}));
    if (response.ok) return { outcome: 'saved' };
    if (response.status === 409 && data.assignment_check) {
      return { outcome: 'needs_acknowledgement', assignment_check: data.assignment_check };
    }
    return { outcome: 'rejected', message: data.error || `Request failed (${response.status})` };
  }

  static async getPortfolios(): Promise<PortfolioSummary[]> {
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/portfolios`);
    const data = await response.json();
    return data.portfolios || [];
  }

  /**
   * Move a strategy to another portfolio.
   *
   * A 409 carrying assignment_check is the acknowledgeable one -- the move is
   * allowed but breaks history continuity. Every other failure is a flat
   * refusal (a retired strategy, a bad id) with nothing to override.
   */
  static async reassignPortfolio(input: {
    strategy_id: string;
    portfolio_id: string;
    reason: string;
    acknowledge?: boolean;
  }): Promise<
    | { outcome: 'saved'; assignment_check: AssignmentCheck }
    | { outcome: 'needs_acknowledgement'; assignment_check: AssignmentCheck }
    | { outcome: 'rejected'; message: string }
  > {
    const encodedId = encodeURIComponent(input.strategy_id);
    const response = await putWithAuth(
      `${API_BASE_URL}/portfolio/strategies/${encodedId}/portfolio`,
      {
        portfolio_id: input.portfolio_id,
        reason: input.reason,
        acknowledge: Boolean(input.acknowledge),
      },
    );
    const data = await response.json().catch(() => ({}));

    if (response.ok) {
      return { outcome: 'saved', assignment_check: data.assignment_check };
    }
    if (response.status === 409 && data.assignment_check) {
      return { outcome: 'needs_acknowledgement', assignment_check: data.assignment_check };
    }
    return { outcome: 'rejected', message: data.error || `Request failed (${response.status})` };
  }

  static async getAssignmentHistory(strategyId: string): Promise<AssignmentRecord[]> {
    const encodedId = encodeURIComponent(strategyId);
    const response = await fetchWithAuth(
      `${API_BASE_URL}/portfolio/strategies/${encodedId}/portfolio/history`,
    );
    const data = await response.json();
    return data.assignments || [];
  }

  static async getLifecycleHistory(strategyId: string): Promise<LifecycleRecord[]> {
    const encodedId = encodeURIComponent(strategyId);
    const response = await fetchWithAuth(
      `${API_BASE_URL}/portfolio/strategies/${encodedId}/lifecycle/history`,
    );
    const data = await response.json();
    return data.history || [];
  }

  static async getPositionOverrides(strategyId: string, portfolioId: string): Promise<PositionOverride[]> {
    const encodedId = encodeURIComponent(strategyId);
    const query = `?portfolio_id=${encodeURIComponent(portfolioId)}`;
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/overrides/${encodedId}${query}`);
    const data = await response.json();
    return data.overrides || [];
  }
}

export interface Book {
  portfolio_id: string;
  name: string;
  description: string;
  /** false when the book exists only because a strategy sits in it. */
  declared: boolean;
  strategy_count: number;
  strategies: {
    id: string;
    name: string;
    strategy_type: string;
    lifecycle: string;
    /** true for the book strategy_registry.portfolio_id names -- what the engine reads. */
    is_primary?: boolean;
  }[];
}

export interface AssignmentRecord {
  id: number;
  strategy_id: string;
  user_id: string | null;
  from_portfolio_id: string | null;
  to_portfolio_id: string | null;
  lifecycle_at_move: string | null;
  reason: string | null;
  consequences: { code: string; message: string }[] | null;
  acknowledged: boolean;
  created_at: string;
}

export interface LifecycleRecord {
  id: number;
  strategy_id: string;
  before_state: string;
  after_state: string;
  reason: string;
  user_id: string | null;
  created_at: string;
}

export type PositionOverride = {
  id: number;
  user_id: string;
  source_app: string;
  strategy_id: string;
  symbol: string;
  before_state: Record<string, unknown>;
  after_state: Record<string, unknown>;
  reason: string;
  risk_check_result: RiskCheck | null;
  overrode_risk: boolean;
  created_at: string;
};

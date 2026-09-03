import type { Strategy, PortfolioData, HistoricalDataPoint } from '../../domain/portfolio/portfolioData';
import type { IncubatingStrategy, IncubationPerformance } from '../../domain/portfolio/incubationData';
import type { RiskCheck } from '../../domain/portfolio/positionEdit';
import type {
  AssignmentCheck,
  PortfolioSummary,
} from '../../domain/portfolio/portfolioAssignment';
import { API_BASE_URL, deleteWithAuth, fetchWithAuth, log, postWithAuth, putWithAuth } from './httpClient';

/**
 * A strategy the engine has published nothing for.
 *
 * Every numeric field is zero and `dataAvailable` is false; nothing that reads
 * this should treat the zeros as measurements -- they exist so the shape stays
 * valid for components that index into it. Callers filter on dataAvailable.
 */
function placeholderStrategy(summary: { id: string; name: string }): Strategy {
  return {
    id: summary.id,
    name: summary.name,
    description: '',
    dataAvailable: false,
    invested: 0,
    currentValue: 0,
    return: 0,
    returnPercent: 0,
    positions: [],
    historicalData: [],
    bestDay: 0,
    worstDay: 0,
    metrics: {
      volatility: 0, sharpeRatio: 0, maxDrawdown: 0, winRate: 0, totalTrades: 0,
      avgWin: 0, avgLoss: 0, profitFactor: 0, dailyReturn: 0, cumulativeReturn: 0,
      annualizedReturn: 0, grossLeverage: 0, netLeverage: 0, portfolioLeverage: 0,
      marginPosted: 0, equityToMarginRatio: 0, marginCushion: 0, totalNotional: 0,
      unrealizedPnL: 0, realizedPnL: 0, totalCommissions: 0, netPnL: 0,
      cashAvailable: 0, currentPortfolioValue: 0,
    },
    executions: [],
    finalizedPositions: [],
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
   * Omitting `portfolioId` gets the primary book, which is what the dashboard
   * wants. Naming a book gets that book's positions, and its risk limits --
   * a strategy in several books has a separate ledger in each.
   */
  static async getStrategy(strategyId: string, portfolioId?: string): Promise<Strategy> {
    log('info', `getStrategy(${strategyId}) called`);
    const query = portfolioId ? `?portfolio_id=${encodeURIComponent(portfolioId)}` : '';
    const url = `${API_BASE_URL}/portfolio/strategy/${strategyId}${query}`;
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

    return data;
  }

  static async getAllStrategies(): Promise<Strategy[]> {
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/strategies`);
    const data = await response.json();
    return data.strategies;
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
    // A summary with dataAvailable === false has no live_results row for its
    // (strategy_type, portfolio_id) pairing -- the state right after a strategy
    // changes book. Its detail endpoint would 404, which inside Promise.all
    // would reject and take the whole dashboard down, so do not ask for it.
    // Carry a placeholder instead: the strategy is real and must stay visible.
    log('info', 'Fetching detailed data for each strategy...');
    const strategies: Strategy[] = await Promise.all(
      strategySummaries.map(async (summary: any, index: number) => {
        if (summary.dataAvailable === false) {
          log('warn', `Strategy ${summary.id} has no published results; showing it without numbers`);
          return placeholderStrategy(summary);
        }
        log('info', `Fetching strategy ${index + 1}/${strategySummaries.length}: ${summary.id}`);
        const strategy = await this.getStrategy(summary.id);
        log('info', `Strategy ${summary.id} fetched successfully`);
        return strategy;
      })
    );
    log('info', `All ${strategies.length} strategies fetched`);

    // Portfolio totals cover only the strategies the engine has actually
    // published. The count of the rest is carried alongside so the headline can
    // say it is partial -- a total that quietly omits a strategy is the bug
    // this replaces.
    log('info', 'Calculating portfolio totals...');
    const priced = strategies.filter(s => s.dataAvailable !== false);
    const strategiesAwaitingData = strategies.length - priced.length;
    const totalInvested = priced.reduce((sum, s) => sum + s.invested, 0);
    const totalValue = priced.reduce((sum, s) => sum + s.currentValue, 0);
    const totalReturn = totalValue - totalInvested;
    const totalReturnPercent = totalInvested > 0 ? (totalReturn / totalInvested) * 100 : 0;

    // Aggregate historical data
    log('info', 'Aggregating historical data...');
    const historicalData = this.aggregateHistoricalData(priced);

    const result = {
      totalValue,
      totalInvested,
      totalReturn,
      totalReturnPercent,
      strategies,
      historicalData,
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

  private static aggregateHistoricalData(strategies: Strategy[]): HistoricalDataPoint[] {
    if (strategies.length === 0) return [];

    // Create a map of dates to total values
    const dateMap = new Map<string, number>();

    // For each strategy, add its historical values to the corresponding dates
    strategies.forEach(strategy => {
      strategy.historicalData.forEach(point => {
        const currentValue = dateMap.get(point.date) || 0;
        dateMap.set(point.date, currentValue + point.value);
      });
    });

    // Convert map to array and sort by date
    const aggregated: HistoricalDataPoint[] = Array.from(dateMap.entries())
      .map(([date, value]) => ({ date, value }))
      .sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());

    return aggregated;
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
    symbol: string;
    quantity: number;
    average_price?: number | null;
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
    return { outcome: 'rejected', message: data.error || `Request failed (${response.status})` };
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

  static async getPositionOverrides(strategyId: string): Promise<PositionOverride[]> {
    const encodedId = encodeURIComponent(strategyId);
    const response = await fetchWithAuth(`${API_BASE_URL}/portfolio/overrides/${encodedId}`);
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

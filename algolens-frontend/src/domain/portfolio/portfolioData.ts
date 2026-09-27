import type { HistoryBreak } from './historySegments';
import type { AggregateCoverage } from './commonCoverage';
export interface Position {
  symbol: string;
  /** Engine-owned row identity. Required when writing this exact position. */
  strategyName: string;
  /** Snapshot containing this row, when supplied by the API. */
  positionDate?: string | null;
  name: string;
  shares: number;
  /** Canonical Decimal8 quantity. Authoritative when present. */
  quantity_exact?: string;
  /** Average entry price. Null when the engine has not published one. */
  costBasis: number | null;
  /** Canonical Decimal8 basis, or null with an unknown basis. */
  average_price_exact?: string | null;
  /** Exposure at the market, or null when it cannot be computed. */
  currentValue: number | null;
  quantity?: number;
  /**
   * The latest close from the market data pipeline. Null when that pipeline
   * has no bar for this symbol. It used to be the entry price under a column
   * labelled "Market Price".
   */
  marketPrice?: number | null;
  /**
   * true when the engine has no average_price for this row. Every price and
   * notional derived from it is then a placeholder, not a measurement.
   */
  priceUnknown?: boolean;
  /** true when the market data pipeline has no price for this symbol. */
  marketPriceUnknown?: boolean;
  /** Contract size. A futures notional is quantity x price x this. */
  contractMultiplier?: number | null;
  /** true when no contract size is on file, so exposure cannot be computed. */
  multiplierUnknown?: boolean;
  notional?: number | null;
  percentOfTotal?: number | null;
}

export interface Execution {
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  /** Traded value: quantity x price x contract size. Null without a size. */
  notional: number | null;
  commission: number;
  date?: string;
}

export interface FinalizedPosition {
  symbol: string;
  strategyName: string;
  quantity: number;
  /** Yesterday's average price, or null when the engine published none. */
  entryPrice: number | null;
  /**
   * Today's average price for a lot that changed size, and null for a lot
   * that is gone: nothing in the engine's data says what it exited at. This
   * was typed `number` while the API already sent null, so the table called
   * .toFixed on null and took the Trading tab down with it.
   */
  exitPrice: number | null;
  realizedPnL: number | null;
}

export interface StrategyMetrics {
  /**
   * Any of these may be null: the engine did not publish it, or it is
   * mathematically undefined. Null is rendered as unknown, never as zero.
   */
  volatility: number | null;
  /** Annualised return over volatility with a ZERO risk-free rate. */
  sharpeRatio: number | null;
  /** Annualised return over downside deviation, from the engine. */
  sortinoRatio: number | null;
  /** Annualised deviation of negative daily returns, from the engine. */
  downsideDeviation: number | null;
  maxDrawdown: number | null;
  /** Share of profitable DAYS on the equity curve, not of trades. */
  winRate: number | null;
  /**
   * Fills attributed to the selected execution date, or null when legacy rows
   * cannot be attributed to the QT stream.
   */
  executionsToday: number | null;
  /** Mean daily percentage return on winning days. Percent, not dollars. */
  avgWin: number | null;
  /** Mean daily percentage loss on losing days, positive. Percent. */
  avgLoss: number | null;
  profitFactor: number | null;
  dailyReturn: number | null;
  cumulativeReturn: number | null;
  annualizedReturn: number | null;
  grossLeverage: number | null;
  netLeverage: number | null;
  portfolioLeverage: number | null;
  marginPosted: number | null;
  equityToMarginRatio: number | null;
  marginCushion: number | null;
  totalNotional: number | null;
  unrealizedPnL: number | null;
  realizedPnL: number | null;
  totalCommissions: number | null;
  netPnL: number | null;
  cashAvailable: number | null;
  currentPortfolioValue: number | null;
  /** Return since inception. Distinct from netPnL -- see the API comment. */
  totalReturn?: number | null;
}

/**
 * Correlations between the instruments the fund currently holds.
 *
 * `matrix[i][j]` is the correlation of `symbols[i]` with `symbols[j]`, or null
 * where it could not be measured -- too few overlapping returns, or a series
 * that never moved. `observations` is the count behind the THINNEST pair, so a
 * caller can state how firm the whole matrix is rather than implying every
 * cell rests on the same amount of data.
 */
export interface HeldCorrelations {
  symbols: string[];
  matrix: (number | null)[][];
  observations: number;
  /** Held, but the price pipeline has no bars for them. Left out, not zeroed. */
  symbolsWithoutPrices: string[];
}

export interface HistoricalDataPoint {
  date: string;
  value: number;
}

export type PositionStream = 'system' | 'qt';

export type { HistoryBreak } from './historySegments';

export interface Strategy {
  id: string;
  name: string;
  description: string;
  /**
   * false when the engine has published no live_results row for this
   * (strategy_type, portfolio_id) pairing. Every number on the object is then a
   * unknown, not a zero measurement -- filter on this before aggregating.
   */
  dataAvailable?: boolean;
  /** The selected result stream and its reporting date, separate from positionDate. */
  resultSource?: 'qt';
  resultDate?: string | null;
  /** Starting equity. Null when none is on record and no curve supplies one. */
  invested: number | null;
  currentValue: number | null;
  return: number | null;
  returnPercent: number | null;
  positions: Position[];
  /** Proven source of the displayed open positions; unknown is read-only. */
  positionStream?: PositionStream | null;
  /**
   * Engine-owned identities valid for creating a row in this snapshot.
   * Exactly one identity is required before the frontend may offer Add.
   */
  positionStrategyNames: string[];
  /** Actual selected QT snapshot date, not necessarily the current day. */
  positionDate: string | null;
  /** True only when the current server-day row has resolvable engine identity. */
  positionsEditable: boolean;
  positionEditUnavailableReason: string | null;
  historicalData: HistoricalDataPoint[];
  /**
   * Equity curve per portfolio stream, keyed by stream name:
   *   qt        what QT actually decided -- the real book
   *   system    what the algorithm said today, given the real book
   *   benchmark what the algorithm would have compounded to untouched
   *
   * Absent until the dual-portfolio migration has run, so always guard on it.
   */
  equityByStream?: Record<string, HistoricalDataPoint[]>;
  /**
   * Where this curve stops describing the same portfolio, because the strategy
   * changed book. The equity values are untouched; these say where the line
   * must break so nothing is read straight across the change.
   */
  historyBreaks?: HistoryBreak[];
  bestDay: number | null;
  worstDay: number | null;
  metrics: StrategyMetrics;
  executions: Execution[];
  /** False when legacy execution rows cannot be attributed to this stream. */
  executionsAvailable?: boolean;
  executionUnavailableReason?: string | null;
  /** Server-selected live-results date used to scope attributed fills. */
  executionDate?: string | null;
  finalizedPositions: FinalizedPosition[];
  /** Closed-position comparisons remain QT, independently of positionStream. */
  activityStream?: 'qt' | null;
  /** False when the QT comparison snapshot is absent, rather than known empty. */
  finalizedPositionsAvailable?: boolean;
  managers: string[];
  lastUpdate: string;
  /**
   * The book these positions belong to. Positions, risk limits and the traded
   * universe are all keyed on (strategy, book), so this is not decoration --
   * an edit has to name it.
   */
  portfolio_id?: string;
  /** Every book this strategy trades in. More than one means this view is partial. */
  books?: string[];
}

export interface PortfolioData {
  /** Covers only strategies with published results. See strategiesAwaitingData. */
  totalValue: number;
  totalInvested: number;
  /** Null when any included strategy has no known starting equity. */
  totalReturn: number | null;
  /** Null for the same reason, or when the known basis is non-positive. */
  totalReturnPercent: number | null;
  strategies: Strategy[];
  historicalData: HistoricalDataPoint[];
  historicalCoverage?: AggregateCoverage;
  /**
   * How many strategies are excluded from the totals because the engine has
   * published nothing for them. Non-zero means the headline is partial and the
   * UI must say so.
   */
  strategiesAwaitingData?: number;
}

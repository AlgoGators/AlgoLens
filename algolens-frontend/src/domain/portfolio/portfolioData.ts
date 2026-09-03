export interface Position {
  symbol: string;
  name: string;
  shares: number;
  /** Average entry price. Null when the engine has not published one. */
  costBasis: number | null;
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
  notional: number;
  commission: number;
  date?: string;
}

export interface FinalizedPosition {
  symbol: string;
  quantity: number;
  entryPrice: number;
  exitPrice: number;
  realizedPnL: number;
}

export interface StrategyMetrics {
  volatility: number;
  sharpeRatio: number;
  maxDrawdown: number;
  winRate: number;
  totalTrades: number;
  avgWin: number;
  avgLoss: number;
  profitFactor: number;
  dailyReturn: number;
  cumulativeReturn: number;
  annualizedReturn: number;
  grossLeverage: number;
  netLeverage: number;
  portfolioLeverage: number;
  marginPosted: number;
  equityToMarginRatio: number;
  marginCushion: number;
  totalNotional: number;
  unrealizedPnL: number;
  realizedPnL: number;
  totalCommissions: number;
  netPnL: number;
  cashAvailable: number;
  currentPortfolioValue: number;
}

export interface HistoricalDataPoint {
  date: string;
  value: number;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  /**
   * false when the engine has published no live_results row for this
   * (strategy_type, portfolio_id) pairing. Every number on the object is then a
   * placeholder zero, not a measurement -- filter on this before aggregating.
   */
  dataAvailable?: boolean;
  invested: number;
  currentValue: number;
  return: number;
  returnPercent: number;
  positions: Position[];
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
  bestDay: number;
  worstDay: number;
  metrics: StrategyMetrics;
  executions: Execution[];
  finalizedPositions: FinalizedPosition[];
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
  totalReturn: number;
  totalReturnPercent: number;
  strategies: Strategy[];
  historicalData: HistoricalDataPoint[];
  /**
   * How many strategies are excluded from the totals because the engine has
   * published nothing for them. Non-zero means the headline is partial and the
   * UI must say so.
   */
  strategiesAwaitingData?: number;
}
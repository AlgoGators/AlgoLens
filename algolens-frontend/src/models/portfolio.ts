export interface Position {
  symbol: string;
  name: string;
  shares: number;
  costBasis: number;
  currentValue: number;
  quantity?: number;
  marketPrice?: number;
  notional?: number;
  percentOfTotal?: number;
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
  invested: number;
  currentValue: number;
  return: number;
  returnPercent: number;
  positions: Position[];
  historicalData: HistoricalDataPoint[];
  bestDay: number;
  worstDay: number;
  metrics: StrategyMetrics;
  executions: Execution[];
  finalizedPositions: FinalizedPosition[];
  managers: string[];
  lastUpdate: string;
}

export interface PortfolioData {
  totalValue: number;
  totalInvested: number;
  totalReturn: number;
  totalReturnPercent: number;
  strategies: Strategy[];
  historicalData: HistoricalDataPoint[];
}

export interface AllocationSlice {
  symbol: string;
  value: number;
  percentage: number;
}

export interface StrategySlice {
  name: string;
  value: number;
  percentage: number;
}

export interface SymbolPnL {
  symbol: string;
  pnl: number;
}

export interface AdvancedMetrics {
  sortinoRatio: number;
  informationRatio: number;
  hhi: number;
  correlationMatrix: number[][];
  topHoldings: AllocationSlice[];
  var95: number;
}

export interface CombinedMetrics {
  totalInvested: number;
  totalValue: number;
  totalReturn: number;
  returnPercent: number;
  metrics: StrategyMetrics;
  symbolPnL: SymbolPnL[];
  dailyPnL: { date: string; pnl: number }[];
  strategies: Strategy[];
  assetAllocation: AllocationSlice[];
  strategyAllocation: StrategySlice[];
  historicalPerformance: { date: string; return: number }[];
  advancedMetrics: AdvancedMetrics;
}

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

// Generate historical data
const generateHistoricalData = (startValue: number, endValue: number, days: number): HistoricalDataPoint[] => {
  const data: HistoricalDataPoint[] = [];
  const today = new Date();

  for (let i = days; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(date.getDate() - i);

    // Add some randomness but trend towards end value
    const progress = (days - i) / days;
    const baseValue = startValue + (endValue - startValue) * progress;
    const variance = baseValue * 0.05; // 5% variance
    const value = baseValue + (Math.random() - 0.5) * variance;

    data.push({
      date: date.toISOString().split('T')[0],
      value: Math.round(value * 100) / 100
    });
  }

  return data;
};

export const portfolioData: PortfolioData = {
  totalValue: 127845.32,
  totalInvested: 100000,
  totalReturn: 27845.32,
  totalReturnPercent: 27.85,
  strategies: [
    {
      id: 'growth',
      name: 'Growth Strategy',
      description: 'High-growth tech and innovative companies',
      invested: 40000,
      currentValue: 54230.45,
      return: 14230.45,
      returnPercent: 35.58,
      bestDay: 4.2,
      worstDay: -3.8,
      managers: ['Sarah Chen', 'Michael Rodriguez'],
      lastUpdate: 'Updated 3 hours ago',
      metrics: {
        volatility: 17.97,
        sharpeRatio: 1.85,
        maxDrawdown: -12.5,
        winRate: 62.5,
        totalTrades: 156,
        avgWin: 425.50,
        avgLoss: -285.30,
        profitFactor: 1.89,
        dailyReturn: 1.83,
        cumulativeReturn: 35.58,
        annualizedReturn: 42.15,
        grossLeverage: 2.23,
        netLeverage: 1.05,
        portfolioLeverage: 2.23,
        marginPosted: 11591.53,
        equityToMarginRatio: 4.68,
        marginCushion: 78.66,
        totalNotional: 109966.90,
        unrealizedPnL: 2345.67,
        realizedPnL: 11884.78,
        totalCommissions: 865.17,
        netPnL: 13365.28,
        cashAvailable: 15230.12,
        currentPortfolioValue: 54230.45
      },
      executions: [
        { symbol: 'AAPL', side: 'BUY', quantity: 10, price: 192.51, notional: 1925.10, commission: 1.00 },
        { symbol: 'MSFT', side: 'BUY', quantity: 5, price: 425.05, notional: 2125.25, commission: 1.00 },
        { symbol: 'NVDA', side: 'SELL', quantity: 3, price: 729.34, notional: 2188.02, commission: 1.01 },
        { symbol: 'TSLA', side: 'BUY', quantity: 8, price: 383.29, notional: 3066.32, commission: 1.00 }
      ],
      finalizedPositions: [
        { symbol: 'NVDA', quantity: 3, entryPrice: 680.50, exitPrice: 729.34, realizedPnL: 146.52 },
        { symbol: 'AMD', quantity: -5, entryPrice: 152.30, exitPrice: 148.20, realizedPnL: 205.00 },
        { symbol: 'GOOGL', quantity: 8, entryPrice: 138.50, exitPrice: 142.30, realizedPnL: 304.00 }
      ],
      positions: [
        {
          symbol: 'AAPL',
          name: 'Apple Inc.',
          shares: 50,
          quantity: 50,
          costBasis: 8500,
          currentValue: 9625.50,
          marketPrice: 192.51,
          notional: 9625.50,
          percentOfTotal: 17.75
        },
        {
          symbol: 'MSFT',
          name: 'Microsoft Corporation',
          shares: 35,
          quantity: 35,
          costBasis: 12000,
          currentValue: 14875.25,
          marketPrice: 425.01,
          notional: 14875.25,
          percentOfTotal: 27.43
        },
        {
          symbol: 'NVDA',
          name: 'NVIDIA Corporation',
          shares: 25,
          quantity: 25,
          costBasis: 11500,
          currentValue: 18234.70,
          marketPrice: 729.39,
          notional: 18234.70,
          percentOfTotal: 33.62
        },
        {
          symbol: 'TSLA',
          name: 'Tesla, Inc.',
          shares: 30,
          quantity: 30,
          costBasis: 8000,
          currentValue: 11495.00,
          marketPrice: 383.17,
          notional: 11495.00,
          percentOfTotal: 21.20
        }
      ],
      historicalData: generateHistoricalData(40000, 54230.45, 90)
    },
    {
      id: 'dividend',
      name: 'Dividend Strategy',
      description: 'Stable dividend-paying blue chip stocks',
      invested: 35000,
      currentValue: 41234.87,
      return: 6234.87,
      returnPercent: 17.81,
      bestDay: 2.1,
      worstDay: -1.5,
      metrics: {
        volatility: 8.45,
        sharpeRatio: 2.15,
        maxDrawdown: -6.2,
        winRate: 71.2,
        totalTrades: 89,
        avgWin: 312.40,
        avgLoss: -165.80,
        profitFactor: 2.34,
        dailyReturn: 0.85,
        cumulativeReturn: 17.81,
        annualizedReturn: 21.45,
        grossLeverage: 1.15,
        netLeverage: 0.98,
        portfolioLeverage: 1.15,
        marginPosted: 4123.49,
        equityToMarginRatio: 10.00,
        marginCushion: 90.00,
        totalNotional: 47419.60,
        unrealizedPnL: 1234.56,
        realizedPnL: 5000.31,
        totalCommissions: 445.00,
        netPnL: 5789.87,
        cashAvailable: 8765.43,
        currentPortfolioValue: 41234.87
      },
      executions: [
        { symbol: 'JNJ', side: 'BUY', quantity: 15, price: 170.49, notional: 2557.35, commission: 1.00 },
        { symbol: 'PG', side: 'BUY', quantity: 12, price: 158.35, notional: 1900.20, commission: 1.00 },
        { symbol: 'KO', side: 'SELL', quantity: 20, price: 67.49, notional: 1349.80, commission: 1.01 }
      ],
      finalizedPositions: [
        { symbol: 'KO', quantity: 20, entryPrice: 56.67, exitPrice: 67.49, realizedPnL: 216.40 },
        { symbol: 'PEP', quantity: 10, entryPrice: 168.50, exitPrice: 175.20, realizedPnL: 67.00 },
        { symbol: 'T', quantity: -25, entryPrice: 18.90, exitPrice: 17.50, realizedPnL: 350.00 }
      ],
      positions: [
        {
          symbol: 'JNJ',
          name: 'Johnson & Johnson',
          shares: 60,
          quantity: 60,
          costBasis: 9500,
          currentValue: 10234.80,
          marketPrice: 170.58,
          notional: 10234.80,
          percentOfTotal: 24.82
        },
        {
          symbol: 'PG',
          name: 'Procter & Gamble',
          shares: 75,
          quantity: 75,
          costBasis: 10000,
          currentValue: 11876.50,
          marketPrice: 158.35,
          notional: 11876.50,
          percentOfTotal: 28.81
        },
        {
          symbol: 'KO',
          name: 'Coca-Cola Company',
          shares: 150,
          quantity: 150,
          costBasis: 8500,
          currentValue: 10123.57,
          marketPrice: 67.49,
          notional: 10123.57,
          percentOfTotal: 24.55
        },
        {
          symbol: 'VZ',
          name: 'Verizon Communications',
          shares: 200,
          quantity: 200,
          costBasis: 7000,
          currentValue: 9000.00,
          marketPrice: 45.00,
          notional: 9000.00,
          percentOfTotal: 21.82
        }
      ],
      historicalData: generateHistoricalData(35000, 41234.87, 90),
      managers: ['Alice Johnson'],
      lastUpdate: '2023-09-15'
    },
    {
      id: 'value',
      name: 'Value Strategy',
      description: 'Undervalued companies with strong fundamentals',
      invested: 25000,
      currentValue: 32380.00,
      return: 7380.00,
      returnPercent: 29.52,
      bestDay: 3.5,
      worstDay: -2.8,
      managers: ['James Thompson', 'Aisha Patel'],
      lastUpdate: 'Updated 1 hour ago',
      metrics: {
        volatility: 12.34,
        sharpeRatio: 2.05,
        maxDrawdown: -9.8,
        winRate: 65.8,
        totalTrades: 124,
        avgWin: 385.20,
        avgLoss: -198.50,
        profitFactor: 2.12,
        dailyReturn: 1.25,
        cumulativeReturn: 29.52,
        annualizedReturn: 35.80,
        grossLeverage: 1.85,
        netLeverage: 1.12,
        portfolioLeverage: 1.85,
        marginPosted: 6476.00,
        equityToMarginRatio: 5.00,
        marginCushion: 80.00,
        totalNotional: 59903.00,
        unrealizedPnL: 1876.54,
        realizedPnL: 5503.46,
        totalCommissions: 620.00,
        netPnL: 6760.00,
        cashAvailable: 5432.10,
        currentPortfolioValue: 32380.00
      },
      executions: [
        { symbol: 'BRK.B', side: 'BUY', quantity: 8, price: 435.01, notional: 3480.08, commission: 1.00 },
        { symbol: 'JPM', side: 'SELL', quantity: 12, price: 205.19, notional: 2462.28, commission: 1.00 },
        { symbol: 'BAC', side: 'BUY', quantity: 45, price: 39.45, notional: 1775.25, commission: 1.01 }
      ],
      finalizedPositions: [
        { symbol: 'JPM', quantity: -12, entryPrice: 166.75, exitPrice: 205.19, realizedPnL: 461.28 },
        { symbol: 'WFC', quantity: 30, entryPrice: 37.50, exitPrice: 54.75, realizedPnL: 517.50 },
        { symbol: 'C', quantity: 25, entryPrice: 48.20, exitPrice: 52.90, realizedPnL: 117.50 }
      ],
      positions: [
        {
          symbol: 'BRK.B',
          name: 'Berkshire Hathaway Inc.',
          shares: 25,
          quantity: 25,
          costBasis: 8500,
          currentValue: 10875.00,
          marketPrice: 435.00,
          notional: 10875.00,
          percentOfTotal: 33.58
        },
        {
          symbol: 'JPM',
          name: 'JPMorgan Chase & Co.',
          shares: 45,
          quantity: 45,
          costBasis: 7500,
          currentValue: 9234.50,
          marketPrice: 205.21,
          notional: 9234.50,
          percentOfTotal: 28.51
        },
        {
          symbol: 'BAC',
          name: 'Bank of America Corp',
          shares: 200,
          quantity: 200,
          costBasis: 6000,
          currentValue: 7890.50,
          marketPrice: 39.45,
          notional: 7890.50,
          percentOfTotal: 24.37
        },
        {
          symbol: 'WFC',
          name: 'Wells Fargo & Company',
          shares: 80,
          quantity: 80,
          costBasis: 3000,
          currentValue: 4380.00,
          marketPrice: 54.75,
          notional: 4380.00,
          percentOfTotal: 13.54
        }
      ],
      historicalData: generateHistoricalData(25000, 32380.00, 90)
    }
  ],
  historicalData: generateHistoricalData(100000, 127845.32, 365)
};
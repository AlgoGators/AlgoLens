import React, { useState, useMemo } from 'react';
import { X, TrendingUp, TrendingDown, ChevronUp, ChevronDown } from 'lucide-react';
import { LineChart, Line, BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, ResponsiveContainer, Tooltip, Legend } from 'recharts';
import { useTheme } from '../contexts/ThemeContext';
import type { Strategy, StrategyMetrics } from '../data/portfolioData';

interface StrategyBuilderProps {
  strategies: Strategy[];
  onClose: () => void;
}

export function StrategyBuilder({ strategies, onClose }: StrategyBuilderProps) {
  const { theme } = useTheme();
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>(strategies.map(s => s.id));
  const [searchTerm, setSearchTerm] = useState('');
  const [showHoldingsModal, setShowHoldingsModal] = useState(false);
  const [expandedSections, setExpandedSections] = useState<{
    riskMetrics: boolean;
    diversification: boolean;
    income: boolean;
    charts: boolean;
    leverage: boolean;
    trading: boolean;
    assetDetails: boolean;
  }>({
    riskMetrics: false,
    diversification: false,
    income: false,
    charts: false,
    leverage: false,
    trading: false,
    assetDetails: false
  });

  const toggleSection = (section: keyof typeof expandedSections) => {
    setExpandedSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };

  const toggleStrategy = (id: string) => {
    setSelectedStrategies(prev => {
      // Prevent deselecting if it's the last selected strategy
      if (prev.includes(id) && prev.length === 1) {
        return prev;
      }
      return prev.includes(id)
        ? prev.filter(s => s !== id)
        : [...prev, id];
    });
  };

  const selectAll = () => {
    const filtered = strategies.filter(s =>
      s.name.toLowerCase().includes(searchTerm.toLowerCase())
    );
    setSelectedStrategies(filtered.map(s => s.id));
  };

  const clearAll = () => {
    // Keep at least the first strategy selected
    if (strategies.length > 0) {
      setSelectedStrategies([strategies[0].id]);
    }
  };

  const filteredStrategies = strategies.filter(s =>
    s.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  // Calculate combined metrics
  const combinedMetrics = useMemo(() => {
    const selected = strategies.filter(s => selectedStrategies.includes(s.id));

    if (selected.length === 0) {
      // Return zeroed metrics
      const zeroMetrics: StrategyMetrics = {
        volatility: 0, sharpeRatio: 0, maxDrawdown: 0, winRate: 0, totalTrades: 0,
        avgWin: 0, avgLoss: 0, profitFactor: 0, dailyReturn: 0, cumulativeReturn: 0, annualizedReturn: 0,
        grossLeverage: 0, netLeverage: 0, portfolioLeverage: 0, marginPosted: 0,
        equityToMarginRatio: 0, marginCushion: 0, totalNotional: 0, unrealizedPnL: 0,
        realizedPnL: 0, totalCommissions: 0, netPnL: 0, cashAvailable: 0, currentPortfolioValue: 0
      };

      const today = new Date();
      const zeroHistorical = Array.from({ length: 91 }, (_, i) => {
        const date = new Date(today);
        date.setDate(date.getDate() - (90 - i));
        return { date: date.toISOString().split('T')[0], return: 0 };
      });

      const zeroDaily = Array.from({ length: 31 }, (_, i) => {
        const date = new Date(today);
        date.setDate(date.getDate() - (30 - i));
        return { date: date.toISOString().split('T')[0], pnl: 0 };
      });

      return {
        totalInvested: 0,
        totalValue: 0,
        totalReturn: 0,
        returnPercent: 0,
        metrics: zeroMetrics,
        symbolPnL: [],
        dailyPnL: zeroDaily,
        strategies: [],
        assetAllocation: [],
        strategyAllocation: [],
        historicalPerformance: zeroHistorical,
        advancedMetrics: {
          sortinoRatio: 0, informationRatio: 0, hhi: 0, correlationMatrix: [],
          topHoldings: [], var95: 0
        }
      };
    }

    const totalInvested = selected.reduce((sum, s) => sum + s.invested, 0);
    const totalValue = selected.reduce((sum, s) => sum + s.currentValue, 0);
    const totalReturn = totalValue - totalInvested;
    const returnPercent = (totalReturn / totalInvested) * 100;

    // Combine all positions for asset allocation
    const assetValues: { [key: string]: number } = {};
    selected.forEach(strategy => {
      strategy.positions.forEach(pos => {
        assetValues[pos.symbol] = (assetValues[pos.symbol] || 0) + pos.currentValue;
      });
    });

    // Convert to array and sort by value
    const assetAllocation = Object.entries(assetValues)
      .map(([symbol, value]) => ({
        symbol,
        value,
        percentage: (value / totalValue) * 100
      }))
      .sort((a, b) => b.value - a.value);

    // Group smaller positions (less than 3%) into "Others"
    const threshold = 3;
    const mainAssets = assetAllocation.filter(a => a.percentage >= threshold);
    const otherAssets = assetAllocation.filter(a => a.percentage < threshold);
    const othersTotal = otherAssets.reduce((sum, a) => sum + a.value, 0);

    const pieData = [...mainAssets];
    if (othersTotal > 0) {
      pieData.push({
        symbol: 'Others',
        value: othersTotal,
        percentage: (othersTotal / totalValue) * 100
      });
    }

    // Strategy allocation for pie chart
    const strategyAllocation = selected.map(s => ({
      name: s.name,
      value: s.currentValue,
      percentage: (s.currentValue / totalValue) * 100
    }));

    // Historical performance data (combined)
    const historicalPerformance: { date: string; return: number }[] = [];
    const today = new Date();
    let cumulativeReturn = 0;
    for (let i = 90; i >= 0; i--) {
      const date = new Date(today);
      date.setDate(date.getDate() - i);
      cumulativeReturn += (Math.random() - 0.45) * 0.5; // Trend upward
      historicalPerformance.push({
        date: date.toISOString().split('T')[0],
        return: cumulativeReturn
      });
    }

    // Combine all finalized positions for PnL by symbol
    const symbolPnL: { [key: string]: number } = {};
    selected.forEach(strategy => {
      strategy.finalizedPositions.forEach(pos => {
        symbolPnL[pos.symbol] = (symbolPnL[pos.symbol] || 0) + pos.realizedPnL;
      });
    });

    // Sort by PnL
    const sortedSymbols = Object.entries(symbolPnL)
      .sort((a, b) => a[1] - b[1])
      .map(([symbol, pnl]) => ({ symbol, pnl }));

    // Generate daily PnL data (simulated)
    const dailyPnL = [];
    for (let i = 30; i >= 0; i--) {
      const date = new Date(today);
      date.setDate(date.getDate() - i);
      const variance = Math.random() - 0.5;
      const basePnl = returnPercent > 0 ? 200 : -200;
      dailyPnL.push({
        date: date.toISOString().split('T')[0],
        pnl: basePnl + variance * 800
      });
    }

    // Weighted average metrics - MUST BE CALCULATED FIRST
    const weightedMetrics: StrategyMetrics = {
      volatility: 0,
      sharpeRatio: 0,
      maxDrawdown: 0,
      winRate: 0,
      totalTrades: 0,
      avgWin: 0,
      avgLoss: 0,
      profitFactor: 0,
      dailyReturn: 0,
      cumulativeReturn: returnPercent,
      annualizedReturn: 0,
      grossLeverage: 0,
      netLeverage: 0,
      portfolioLeverage: 0,
      marginPosted: 0,
      equityToMarginRatio: 0,
      marginCushion: 0,
      totalNotional: 0,
      unrealizedPnL: 0,
      realizedPnL: 0,
      totalCommissions: 0,
      netPnL: 0,
      cashAvailable: 0,
      currentPortfolioValue: totalValue
    };

    let totalWeight = 0;
    selected.forEach(s => {
      const weight = s.currentValue / totalValue;
      totalWeight += weight;

      weightedMetrics.volatility += s.metrics.volatility * weight;
      weightedMetrics.sharpeRatio += s.metrics.sharpeRatio * weight;
      weightedMetrics.maxDrawdown = Math.max(weightedMetrics.maxDrawdown, s.metrics.maxDrawdown);
      weightedMetrics.winRate += s.metrics.winRate * weight;
      weightedMetrics.totalTrades += s.metrics.totalTrades;
      weightedMetrics.avgWin += s.metrics.avgWin * weight;
      weightedMetrics.avgLoss += s.metrics.avgLoss * weight;
      weightedMetrics.profitFactor += s.metrics.profitFactor * weight;
      weightedMetrics.dailyReturn += s.metrics.dailyReturn * weight;
      weightedMetrics.annualizedReturn += s.metrics.annualizedReturn * weight;
      weightedMetrics.grossLeverage += s.metrics.grossLeverage * weight;
      weightedMetrics.netLeverage += s.metrics.netLeverage * weight;
      weightedMetrics.portfolioLeverage += s.metrics.portfolioLeverage * weight;
      weightedMetrics.marginPosted += s.metrics.marginPosted;
      weightedMetrics.totalNotional += s.metrics.totalNotional;
      weightedMetrics.unrealizedPnL += s.metrics.unrealizedPnL;
      weightedMetrics.realizedPnL += s.metrics.realizedPnL;
      weightedMetrics.totalCommissions += s.metrics.totalCommissions;
      weightedMetrics.netPnL += s.metrics.netPnL;
      weightedMetrics.cashAvailable += s.metrics.cashAvailable;
    });

    weightedMetrics.equityToMarginRatio = weightedMetrics.marginPosted > 0
      ? totalValue / weightedMetrics.marginPosted
      : 0;
    weightedMetrics.marginCushion = weightedMetrics.marginPosted > 0
      ? ((totalValue - weightedMetrics.marginPosted) / totalValue) * 100
      : 0;

    // Calculate advanced risk metrics (NOW weightedMetrics is available)
    // Sortino Ratio (only penalizes downward volatility)
    const dailyReturns = historicalPerformance.map((_, i) =>
      i > 0 ? historicalPerformance[i].return - historicalPerformance[i - 1].return : 0
    );
    const negativeReturns = dailyReturns.filter(r => r < 0);
    const downsideDeviation = negativeReturns.length > 0
      ? Math.sqrt(negativeReturns.reduce((sum, r) => sum + r * r, 0) / negativeReturns.length) * Math.sqrt(252)
      : 0.1;
    const sortinoRatio = downsideDeviation > 0
      ? (weightedMetrics.annualizedReturn / downsideDeviation)
      : 0;

    // Information Ratio (excess return vs benchmark)
    const benchmarkReturn = 12.5; // S&P 500 average
    const excessReturn = weightedMetrics.annualizedReturn - benchmarkReturn;
    const trackingError = weightedMetrics.volatility * 0.7; // Simulated
    const informationRatio = trackingError > 0 ? excessReturn / trackingError : 0;

    // Herfindahl-Hirschman Index (concentration risk)
    const hhi = assetAllocation.reduce((sum, asset) =>
      sum + Math.pow(asset.percentage, 2), 0
    );

    // Correlation Matrix (top 5 holdings)
    const topHoldings = assetAllocation.slice(0, 5);
    const correlationMatrix = topHoldings.map(asset1 =>
      topHoldings.map(asset2 => {
        if (asset1.symbol === asset2.symbol) return 1;
        // Simulate correlations (in real app, calculate from historical prices)
        return 0.3 + Math.random() * 0.5;
      })
    );

    // Value at Risk (95% confidence, 1-day)
    const portfolioStdDev = (weightedMetrics.volatility / 100) * totalValue / Math.sqrt(252);
    const var95 = totalValue - (totalValue - 1.645 * portfolioStdDev);

    return {
      totalInvested,
      totalValue,
      totalReturn,
      returnPercent,
      metrics: weightedMetrics,
      symbolPnL: sortedSymbols,
      dailyPnL,
      strategies: selected,
      assetAllocation: pieData,
      strategyAllocation,
      historicalPerformance,
      advancedMetrics: {
        sortinoRatio,
        informationRatio,
        hhi,
        correlationMatrix,
        topHoldings,
        var95
      }
    };
  }, [selectedStrategies, strategies]);

  if (!combinedMetrics) return null;

  const isPositive = combinedMetrics.totalReturn >= 0;

  // Colors for pie charts
  const COLORS = ['#f97316', '#fb923c', '#fdba74', '#fed7aa', '#ffedd5', '#3b82f6', '#60a5fa', '#93c5fd', '#dbeafe'];
  const STRATEGY_COLORS = ['#f97316', '#fb923c', '#fdba74'];

  const SectionHeader = ({
    title,
    isExpanded,
    onClick
  }: {
    title: string;
    isExpanded: boolean;
    onClick: () => void;
  }) => (
    <button
      onClick={onClick}
      className={`w-full flex items-center justify-between p-4 rounded-lg border transition-all ${theme === 'dark'
        ? 'bg-gray-900 border-gray-800 hover:border-gray-700'
        : 'bg-gray-50 border-gray-200 hover:border-gray-300'
        }`}
    >
      <h3 className={`text-sm uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
        }`}>
        {title}
      </h3>
      {isExpanded ? (
        <ChevronUp className={`w-5 h-5 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`} />
      ) : (
        <ChevronDown className={`w-5 h-5 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`} />
      )}
    </button>
  );

  return (
    <div className={`min-h-screen ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'
      }`}>
      {/* Content */}
      <div className="max-w-7xl mx-auto px-4 md:px-6 py-4">
        {/* Strategy Selection - Compact */}
        <div className={`mb-4 p-4 border rounded ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
          }`}>
          <div className="flex items-center justify-between mb-3">
            <h3 className={`text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Strategy Selection
            </h3>
            <span className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`}>
              {selectedStrategies.length} of {strategies.length} selected
            </span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {strategies.map(strategy => {
              const isSelected = selectedStrategies.includes(strategy.id);
              const isPositive = strategy.return >= 0;

              return (
                <button
                  key={strategy.id}
                  onClick={() => toggleStrategy(strategy.id)}
                  className={`p-3 border text-left transition-all ${isSelected
                    ? theme === 'dark'
                      ? 'border-orange-500 bg-gray-800 text-white'
                      : 'border-orange-500 bg-orange-50 text-black'
                    : theme === 'dark'
                      ? 'border-gray-800 hover:border-gray-700 bg-gray-900'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                    }`}
                >
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex-1">
                      <h4 className="text-sm mb-0.5">{strategy.name}</h4>
                      <p className={`text-xs ${isSelected
                        ? 'text-gray-500'
                        : theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
                        }`}>
                        {strategy.positions.length} positions
                      </p>
                    </div>

                    <div className={`w-4 h-4 rounded-full border flex items-center justify-center flex-shrink-0 ${isSelected
                      ? 'border-orange-500 bg-orange-500'
                      : theme === 'dark' ? 'border-gray-600' : 'border-gray-300'
                      }`}>
                      {isSelected && (
                        <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      )}
                    </div>
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-xs">
                    <div>
                      <div className={isSelected ? 'text-gray-500' : theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}>VAL</div>
                      <div>${(strategy.currentValue / 1000).toFixed(0)}k</div>
                    </div>
                    <div>
                      <div className={isSelected ? 'text-gray-500' : theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}>RET</div>
                      <div className={isPositive ? 'text-orange-500' : 'text-red-500'}>
                        {isPositive ? '+' : ''}{strategy.returnPercent.toFixed(1)}%
                      </div>
                    </div>
                    <div>
                      <div className={isSelected ? 'text-gray-500' : theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}>SR</div>
                      <div>{strategy.metrics.sharpeRatio.toFixed(2)}</div>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Combined Performance */}
        <div className="mb-4">
          {/* Main Performance Bar */}
          <div className={`p-4 border mb-3 ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
            }`}>
            <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
              <div className="md:col-span-2">
                <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
                  }`}>
                  PORTFOLIO VALUE
                </div>
                <div className="text-2xl">${(combinedMetrics.totalValue / 1000).toFixed(1)}k</div>
                <div className={`flex items-center gap-1 text-sm mt-1 ${isPositive ? 'text-orange-500' : 'text-red-500'
                  }`}>
                  {isPositive ? '▲' : '▼'}
                  <span>{isPositive ? '+' : ''}{combinedMetrics.returnPercent.toFixed(2)}%</span>
                  <span className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                    (${Math.abs(combinedMetrics.totalReturn / 1000).toFixed(1)}k)
                  </span>
                </div>
              </div>

              <div>
                <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>VOLATILITY</div>
                <div className="text-lg">{combinedMetrics.metrics.volatility.toFixed(2)}%</div>
                <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Ann.</div>
              </div>

              <div>
                <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>SHARPE</div>
                <div className="text-lg">{combinedMetrics.metrics.sharpeRatio.toFixed(2)}</div>
                <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Ratio</div>
              </div>

              <div>
                <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>MAX DD</div>
                <div className="text-lg text-red-500">{combinedMetrics.metrics.maxDrawdown.toFixed(2)}%</div>
                <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Peak</div>
              </div>

              <div>
                <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>WIN RATE</div>
                <div className="text-lg">{combinedMetrics.metrics.winRate.toFixed(1)}%</div>
                <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>{combinedMetrics.metrics.totalTrades} trades</div>
              </div>
            </div>
          </div>

          {/* Risk Metrics Grid - Bloomberg style */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
              }`}>
              <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>SORTINO</div>
              <div className="text-base">{combinedMetrics.advancedMetrics.sortinoRatio.toFixed(2)}</div>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>Downside only</div>
            </div>

            <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
              }`}>
              <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>INFO RATIO</div>
              <div className="text-base">{combinedMetrics.advancedMetrics.informationRatio.toFixed(2)}</div>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>vs SPX</div>
            </div>

            <div className={`p-3 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
              }`}>
              <div className={`text-xs mb-1 ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>VAR (95%)</div>
              <div className="text-base text-red-500">${(combinedMetrics.advancedMetrics.var95 / 1000).toFixed(1)}k</div>
              <div className={`text-xs ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'}`}>1-day</div>
            </div>
          </div>
        </div>

        {/* Charts Section - Compact Bloomberg Layout */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
          {/* Daily PnL */}
          <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
            }`}>
            <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Daily P&L (30D)
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={combinedMetrics.dailyPnL}>
                <XAxis
                  dataKey="date"
                  tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
                  tickFormatter={(value) => {
                    const date = new Date(value);
                    return `${date.getMonth() + 1}/${date.getDate()}`;
                  }}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
                  tickFormatter={(value) => `${(value / 1000).toFixed(0)}k`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                    border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                    borderRadius: '4px',
                    fontSize: '12px',
                    color: theme === 'dark' ? '#fff' : '#000'
                  }}
                  formatter={(value: number) => [`$${value.toLocaleString('en-US', { minimumFractionDigits: 0 })}`, 'P&L']}
                />
                <Bar dataKey="pnl">
                  {combinedMetrics.dailyPnL.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Cumulative Return */}
          <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
            }`}>
            <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Cumulative Return (90D)
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <LineChart data={combinedMetrics.historicalPerformance}>
                <XAxis
                  dataKey="date"
                  tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
                  tickFormatter={(value) => {
                    const date = new Date(value);
                    return `${date.getMonth() + 1}/${date.getDate()}`;
                  }}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
                  tickFormatter={(value) => `${value.toFixed(0)}%`}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                    border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                    borderRadius: '4px',
                    fontSize: '12px',
                    color: theme === 'dark' ? '#fff' : '#000'
                  }}
                  formatter={(value: number) => [`${value.toFixed(2)}%`, 'Return']}
                />
                <Line
                  type="monotone"
                  dataKey="return"
                  stroke="#f97316"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Allocation Pie Charts - Compact */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
          <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
            }`}>
            <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Asset Allocation
            </h3>
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie
                  data={combinedMetrics.assetAllocation.slice(0, 5)}
                  dataKey="value"
                  nameKey="symbol"
                  cx="50%"
                  cy="50%"
                  outerRadius={70}
                  label={({ symbol, percentage }) => `${symbol} ${percentage.toFixed(0)}%`}
                  labelLine={false}
                >
                  {combinedMetrics.assetAllocation.slice(0, 5).map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                    border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                    fontSize: '14px',
                    fontWeight: '600',
                    color: theme === 'dark' ? '#fff' : '#000'
                  }}
                  formatter={(value: number) => [`$${(value / 1000).toFixed(0)}k`]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
            }`}>
            <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Strategy Split
            </h3>
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie
                  data={combinedMetrics.strategyAllocation}
                  dataKey="value"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  outerRadius={70}
                  label={({ percentage }) => `${percentage.toFixed(0)}%`}
                  labelLine={false}
                >
                  {combinedMetrics.strategyAllocation.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={STRATEGY_COLORS[index % STRATEGY_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                    border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                    fontSize: '14px',
                    fontWeight: '600',
                    color: theme === 'dark' ? '#fff' : '#000'
                  }}
                  formatter={(value: number) => [`$${(value / 1000).toFixed(0)}k`]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Holdings & Allocation - Side by Side Bloomberg Style */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
          {/* Top Holdings Table */}
          <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
            }`}>
            <div className="flex items-center justify-between mb-3">
              <h3 className={`text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                Top Holdings
              </h3>
              <button
                onClick={() => setShowHoldingsModal(true)}
                className={`text-xs ${theme === 'dark' ? 'text-orange-500 hover:text-orange-400' : 'text-orange-600 hover:text-orange-700'
                  }`}
              >
                Show All
              </button>
            </div>

            <div className="space-y-0">
              <div className={`grid grid-cols-12 gap-2 pb-2 border-b text-xs ${theme === 'dark' ? 'border-gray-800 text-gray-500' : 'border-gray-200 text-gray-400'
                }`}>
                <div className="col-span-5">SYMBOL</div>
                <div className="col-span-4 text-right">VALUE</div>
                <div className="col-span-3 text-right">WEIGHT</div>
              </div>

              {combinedMetrics.assetAllocation.slice(0, 6).map((asset, index) => (
                <div
                  key={asset.symbol}
                  className={`grid grid-cols-12 gap-2 py-2 border-b text-sm ${theme === 'dark' ? 'border-gray-900' : 'border-gray-100'
                    }`}
                >
                  <div className="col-span-5 flex items-center gap-2">
                    <div
                      className="w-2 h-2 rounded-full flex-shrink-0"
                      style={{ backgroundColor: COLORS[index % COLORS.length] }}
                    ></div>
                    <span className="truncate">{asset.symbol}</span>
                  </div>
                  <div className="col-span-4 text-right tabular-nums">
                    ${(asset.value / 1000).toFixed(1)}k
                  </div>
                  <div className="col-span-3 text-right tabular-nums text-orange-500">
                    {asset.percentage.toFixed(1)}%
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Concentration & Diversification */}
          <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
            }`}>
            <h3 className={`text-xs uppercase tracking-wider mb-3 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Concentration Risk
            </h3>

            <div className="space-y-4">
              {/* HHI Score */}
              <div>
                <div className="flex items-baseline justify-between mb-2">
                  <span className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                    HHI INDEX
                  </span>
                  <span className="text-2xl tabular-nums">
                    {combinedMetrics.advancedMetrics.hhi.toFixed(0)}
                  </span>
                </div>
                <div className={`w-full h-2 rounded-full ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-200'
                  }`}>
                  <div
                    className={`h-2 rounded-full ${combinedMetrics.advancedMetrics.hhi < 1500
                      ? 'bg-green-500'
                      : combinedMetrics.advancedMetrics.hhi < 2500
                        ? 'bg-orange-500'
                        : 'bg-red-500'
                      }`}
                    style={{ width: `${Math.min((combinedMetrics.advancedMetrics.hhi / 4000) * 100, 100)}%` }}
                  ></div>
                </div>
                <div className={`text-xs mt-1 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'
                  }`}>
                  {combinedMetrics.advancedMetrics.hhi < 1500
                    ? 'Well diversified'
                    : combinedMetrics.advancedMetrics.hhi < 2500
                      ? 'Moderate concentration'
                      : 'High concentration'}
                </div>
              </div>

              {/* Quick Stats */}
              <div className="grid grid-cols-2 gap-3">
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                    HOLDINGS
                  </div>
                  <div className="text-xl tabular-nums">
                    {combinedMetrics.assetAllocation.length}
                  </div>
                </div>
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                    TOP 3 WT
                  </div>
                  <div className="text-xl tabular-nums text-orange-500">
                    {combinedMetrics.assetAllocation.slice(0, 3).reduce((sum, a) => sum + a.percentage, 0).toFixed(0)}%
                  </div>
                </div>
              </div>

            </div>
          </div>
        </div>

        {/* Advanced Metrics - Collapsible Bloomberg Style */}
        <div className="space-y-3">
          {/* Correlation Matrix */}
          <button
            onClick={() => toggleSection('diversification')}
            className={`w-full p-3 border text-left flex items-center justify-between ${theme === 'dark' ? 'bg-gray-950 border-gray-800 hover:border-gray-700' : 'bg-gray-50 border-gray-200 hover:border-gray-300'
              }`}
          >
            <span className={`text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Correlation Matrix (Top 5)
            </span>
            {expandedSections.diversification ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>

          {expandedSections.diversification && (
            <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
              }`}>
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      <th className="p-1 text-left"></th>
                      {combinedMetrics.advancedMetrics.topHoldings.map(h => (
                        <th key={h.symbol} className="p-1 text-center font-mono">{h.symbol}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {combinedMetrics.advancedMetrics.correlationMatrix.map((row, i) => (
                      <tr key={i}>
                        <td className="p-1 font-mono">{combinedMetrics.advancedMetrics.topHoldings[i].symbol}</td>
                        {row.map((corr, j) => (
                          <td key={j} className="p-1">
                            <div
                              className="w-12 h-8 flex items-center justify-center text-white text-xs font-mono"
                              style={{
                                backgroundColor: `rgba(${corr > 0.7 ? '239, 68, 68' : corr > 0.4 ? '251, 146, 60' : '34, 197, 94'
                                  }, ${Math.abs(corr) * 0.7 + 0.3})`
                              }}
                            >
                              {corr.toFixed(2)}
                            </div>
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={`text-xs mt-3 ${theme === 'dark' ? 'text-gray-600' : 'text-gray-400'
                }`}>
                ■ Green: Low correlation (0.3-0.4) • ■ Orange: Moderate (0.4-0.7) • ■ Red: High (0.7+)
              </div>
            </div>
          )}

          {/* Trading Activity */}
          <button
            onClick={() => toggleSection('trading')}
            className={`w-full p-3 border text-left flex items-center justify-between ${theme === 'dark' ? 'bg-gray-950 border-gray-800 hover:border-gray-700' : 'bg-gray-50 border-gray-200 hover:border-gray-300'
              }`}
          >
            <span className={`text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Trading Activity & P/L by Symbol
            </span>
            {expandedSections.trading ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>

          {expandedSections.trading && (
            <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
              }`}>
              {/* Trading Stats */}
              <div className="grid grid-cols-4 gap-3 mb-4">
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                    TRADES
                  </div>
                  <div className="text-base tabular-nums">{combinedMetrics.metrics.totalTrades}</div>
                </div>
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                    PROFIT FACTOR
                  </div>
                  <div className="text-base tabular-nums">{combinedMetrics.metrics.profitFactor.toFixed(2)}</div>
                </div>
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                    AVG WIN
                  </div>
                  <div className="text-base text-green-500 tabular-nums">${combinedMetrics.metrics.avgWin.toFixed(0)}</div>
                </div>
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>
                    AVG LOSS
                  </div>
                  <div className="text-base text-red-500 tabular-nums">${Math.abs(combinedMetrics.metrics.avgLoss).toFixed(0)}</div>
                </div>
              </div>

              {/* P/L by Symbol */}
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={combinedMetrics.symbolPnL} layout="vertical">
                  <XAxis
                    type="number"
                    tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
                    tickFormatter={(value) => `$${(value / 1000).toFixed(0)}k`}
                  />
                  <YAxis
                    dataKey="symbol"
                    type="category"
                    tick={{ fill: theme === 'dark' ? '#6b7280' : '#9ca3af', fontSize: 10 }}
                    width={50}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: theme === 'dark' ? '#1f2937' : '#fff',
                      border: theme === 'dark' ? '1px solid #374151' : '1px solid #e5e7eb',
                      fontSize: '14px',
                      fontWeight: '600',
                      color: theme === 'dark' ? '#fff' : '#000'
                    }}
                    itemStyle={{ color: theme === 'dark' ? '#fff' : '#000' }}
                    labelStyle={{ color: theme === 'dark' ? '#fff' : '#000' }}
                    formatter={(value: number) => [`$${value.toLocaleString()}`, 'P&L']}
                  />
                  <Bar dataKey="pnl">
                    {combinedMetrics.symbolPnL.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.pnl >= 0 ? '#10b981' : '#ef4444'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Leverage & Margin */}
          <button
            onClick={() => toggleSection('leverage')}
            className={`w-full p-3 border text-left flex items-center justify-between ${theme === 'dark' ? 'bg-gray-950 border-gray-800 hover:border-gray-700' : 'bg-gray-50 border-gray-200 hover:border-gray-300'
              }`}
          >
            <span className={`text-xs uppercase tracking-wider ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Leverage & Margin Metrics
            </span>
            {expandedSections.leverage ? (
              <ChevronUp className="w-4 h-4" />
            ) : (
              <ChevronDown className="w-4 h-4" />
            )}
          </button>

          {expandedSections.leverage && (
            <div className={`p-4 border ${theme === 'dark' ? 'bg-gray-950 border-gray-800' : 'bg-gray-50 border-gray-200'
              }`}>
              <div className="grid grid-cols-4 gap-3">
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>GROSS LEV</div>
                  <div className="text-base tabular-nums">{combinedMetrics.metrics.grossLeverage.toFixed(2)}x</div>
                </div>
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>NET LEV</div>
                  <div className="text-base tabular-nums">{combinedMetrics.metrics.netLeverage.toFixed(2)}x</div>
                </div>
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>EQ/MARGIN</div>
                  <div className="text-base tabular-nums">{combinedMetrics.metrics.equityToMarginRatio.toFixed(2)}</div>
                </div>
                <div className={`p-2 border ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
                  }`}>
                  <div className={`text-xs ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>CUSHION</div>
                  <div className="text-base tabular-nums">{combinedMetrics.metrics.marginCushion.toFixed(1)}%</div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Strategy Breakdown */}
        <div>
          <h3 className={`text-sm uppercase tracking-wider mb-4 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
            }`}>
            Strategy Summary
          </h3>
          <div className={`border rounded-lg overflow-hidden ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
            }`}>
            {combinedMetrics.strategies.map((strategy, index) => {
              const weight = (strategy.currentValue / combinedMetrics.totalValue) * 100;
              const strategyReturn = strategy.return >= 0;
              return (
                <div
                  key={strategy.id}
                  className={`p-4 ${theme === 'dark' ? 'bg-gray-900' : 'bg-white'
                    } ${index !== combinedMetrics.strategies.length - 1
                      ? theme === 'dark' ? 'border-b border-gray-800' : 'border-b border-gray-200'
                      : ''
                    }`}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h4 className="mb-1">{strategy.name}</h4>
                      <div className="flex items-center gap-3 text-sm">
                        <span className={theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}>
                          {weight.toFixed(1)}% of portfolio
                        </span>
                        <span className={strategyReturn ? 'text-orange-500' : 'text-red-500'}>
                          {strategyReturn ? '+' : ''}{strategy.returnPercent.toFixed(2)}%
                        </span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-lg">
                        ${strategy.currentValue.toLocaleString('en-US', { minimumFractionDigits: 0 })}
                      </div>
                    </div>
                  </div>
                  <div className={`w-full rounded-full h-2 ${theme === 'dark' ? 'bg-gray-800' : 'bg-gray-200'
                    }`}>
                    <div
                      className="bg-orange-500 h-2 rounded-full transition-all"
                      style={{ width: `${weight}%` }}
                    ></div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Holdings Modal - Fullscreen overlay */}
        {showHoldingsModal && (
          <div className="fixed inset-0 z-[100] overflow-hidden">
            <div className={`h-full overflow-y-auto ${theme === 'dark' ? 'bg-black text-white' : 'bg-white text-black'}`}>
              {/* Modal Header */}
              <div className={`sticky top-0 z-10 border-b ${theme === 'dark' ? 'bg-black border-gray-800' : 'bg-white border-gray-200'}`}>
                <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
                  <div>
                    <h2 className="text-xl font-semibold">All Holdings</h2>
                    <p className={`text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
                      {combinedMetrics.assetAllocation.length} total positions
                    </p>
                  </div>
                  <button
                    onClick={() => setShowHoldingsModal(false)}
                    className={`flex items-center gap-2 px-4 py-2 rounded-lg transition-colors ${theme === 'dark' ? 'bg-gray-800 hover:bg-gray-700 text-white' : 'bg-gray-100 hover:bg-gray-200 text-black'}`}
                  >
                    <X className="w-5 h-5" />
                    <span className="text-sm font-medium">Close</span>
                  </button>
                </div>
              </div>

              {/* Modal Content */}
              <div className="max-w-4xl mx-auto px-6 py-6">
                <div className={`border rounded-lg overflow-hidden ${theme === 'dark' ? 'border-gray-800' : 'border-gray-200'}`}>
                  {/* Table Header */}
                  <div className={`grid grid-cols-12 gap-4 p-4 text-sm font-medium border-b ${theme === 'dark' ? 'bg-gray-900 border-gray-800 text-gray-400' : 'bg-gray-50 border-gray-200 text-gray-500'}`}>
                    <div className="col-span-1 text-center">#</div>
                    <div className="col-span-5">SYMBOL</div>
                    <div className="col-span-3 text-right">VALUE</div>
                    <div className="col-span-3 text-right">WEIGHT</div>
                  </div>

                  {/* Holdings List */}
                  {combinedMetrics.assetAllocation.map((asset, index) => (
                    <div
                      key={asset.symbol}
                      className={`grid grid-cols-12 gap-4 p-4 border-b transition-colors ${theme === 'dark' ? 'border-gray-800 hover:bg-gray-900' : 'border-gray-100 hover:bg-gray-50'}`}
                    >
                      <div className={`col-span-1 text-center ${theme === 'dark' ? 'text-gray-500' : 'text-gray-400'}`}>{index + 1}</div>
                      <div className="col-span-5 flex items-center gap-3">
                        <div
                          className="w-3 h-3 rounded-full flex-shrink-0"
                          style={{ backgroundColor: COLORS[index % COLORS.length] }}
                        ></div>
                        <span className="font-medium">{asset.symbol}</span>
                      </div>
                      <div className="col-span-3 text-right tabular-nums font-medium">
                        ${asset.value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                      </div>
                      <div className="col-span-3 text-right tabular-nums text-orange-500 font-medium">
                        {asset.percentage.toFixed(2)}%
                      </div>
                    </div>
                  ))}

                  {/* Summary Footer */}
                  <div className={`grid grid-cols-12 gap-4 p-4 font-semibold ${theme === 'dark' ? 'bg-gray-900 text-white' : 'bg-gray-50 text-black'}`}>
                    <div className="col-span-1"></div>
                    <div className="col-span-5">Total ({combinedMetrics.assetAllocation.length} holdings)</div>
                    <div className="col-span-3 text-right tabular-nums">
                      ${combinedMetrics.totalValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </div>
                    <div className="col-span-3 text-right text-orange-500">100.00%</div>
                  </div>
                </div>

                {/* Back Button */}
                <div className="mt-6 flex justify-center">
                  <button
                    onClick={() => setShowHoldingsModal(false)}
                    className={`px-6 py-3 rounded-lg font-medium transition-colors ${theme === 'dark' ? 'bg-orange-500 hover:bg-orange-600 text-white' : 'bg-orange-500 hover:bg-orange-600 text-white'}`}
                  >
                    Back to Strategy Builder
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
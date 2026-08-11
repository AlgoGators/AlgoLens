import React from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import { MetricInfo } from './MetricInfo';
import type { StrategyMetrics } from '@/models';

interface FinancialAnalysisProps {
  metrics: StrategyMetrics;
}

export function FinancialAnalysis({ metrics }: FinancialAnalysisProps) {
  const { theme } = useTheme();

  const MetricCard = ({ label, value, isPercentage = false, isPositive = true, info }: {
    label: string;
    value: number;
    isPercentage?: boolean;
    isPositive?: boolean;
    info?: { description: string; formula?: string };
  }) => (
    <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
      }`}>
      <div className={`text-sm mb-1 flex items-center ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
        }`}>
        {label}
        {info && (
          <MetricInfo
            metric={label}
            description={info.description}
            formula={info.formula}
          />
        )}
      </div>
      <div className={`text-lg ${isPositive
          ? value >= 0 ? 'text-orange-500' : 'text-red-500'
          : ''
        }`}>
        {value >= 0 && isPositive && isPercentage ? '+' : ''}
        {isPercentage
          ? `${value.toFixed(2)}%`
          : value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        }
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Performance Metrics */}
      <div>
        <h3 className={`text-sm uppercase tracking-wider mb-4 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Performance Metrics
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricCard
            label="Daily Return"
            value={metrics.dailyReturn}
            isPercentage
            info={{
              description: "The percentage change in portfolio value from the previous trading day to today."
            }}
          />
          <MetricCard
            label="Cumulative Return"
            value={metrics.cumulativeReturn}
            isPercentage
            info={{
              description: "Total return since the strategy's inception, showing overall performance.",
              formula: "(Current Value - Initial Investment) / Initial Investment × 100"
            }}
          />
          <MetricCard
            label="Annualized Return"
            value={metrics.annualizedReturn}
            isPercentage
            info={{
              description: "Expected return over a year based on current performance, useful for comparing strategies.",
              formula: "((1 + Cumulative Return) ^ (365 / Days)) - 1"
            }}
          />
          <MetricCard
            label="Volatility"
            value={metrics.volatility}
            isPercentage
            isPositive={false}
            info={{
              description: "Measures how much the portfolio's returns fluctuate. Higher volatility means higher risk.",
              formula: "Standard Deviation of Daily Returns × √252"
            }}
          />
        </div>
      </div>

      {/* Risk Metrics */}
      <div>
        <h3 className={`text-sm uppercase tracking-wider mb-4 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Risk Metrics
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <MetricCard
            label="Sharpe Ratio"
            value={metrics.sharpeRatio}
            isPositive={false}
            info={{
              description: "Risk-adjusted return metric. Higher is better. Above 1 is good, above 2 is excellent.",
              formula: "(Portfolio Return - Risk-Free Rate) / Portfolio Volatility"
            }}
          />
          <MetricCard
            label="Max Drawdown"
            value={metrics.maxDrawdown}
            isPercentage
            info={{
              description: "Largest peak-to-trough decline. Shows worst-case loss scenario from a high point.",
              formula: "(Trough Value - Peak Value) / Peak Value × 100"
            }}
          />
          <MetricCard
            label="Win Rate"
            value={metrics.winRate}
            isPercentage
            isPositive={false}
            info={{
              description: "Percentage of profitable trades. A 60%+ win rate is generally considered good.",
              formula: "(Winning Trades / Total Trades) × 100"
            }}
          />
          <MetricCard
            label="Profit Factor"
            value={metrics.profitFactor}
            isPositive={false}
            info={{
              description: "Ratio of gross profit to gross loss. Above 1.5 is good, above 2 is excellent.",
              formula: "Total Winning Trades $ / Total Losing Trades $"
            }}
          />
        </div>
      </div>

      {/* Leverage & Margin */}
      <div>
        <h3 className={`text-sm uppercase tracking-wider mb-4 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Leverage & Margin
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 flex items-center ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Gross Leverage
              <MetricInfo
                metric="Gross Leverage"
                description="Total value of all positions (long + short) divided by portfolio equity. Measures total market exposure."
                formula="(Total Long + Total Short) / Portfolio Value"
              />
            </div>
            <div className="text-lg">{metrics.grossLeverage.toFixed(2)}x</div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 flex items-center ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Net Leverage
              <MetricInfo
                metric="Net Leverage"
                description="Net market exposure after offsetting long and short positions. Shows directional risk."
                formula="(Total Long - Total Short) / Portfolio Value"
              />
            </div>
            <div className="text-lg">{metrics.netLeverage.toFixed(2)}x</div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 flex items-center ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Equity-to-Margin
              <MetricInfo
                metric="Equity-to-Margin Ratio"
                description="How much equity you have relative to margin requirements. Higher is safer."
                formula="Portfolio Value / Margin Posted"
              />
            </div>
            <div className="text-lg">{metrics.equityToMarginRatio.toFixed(2)}x</div>
          </div>
          <MetricCard
            label="Margin Cushion"
            value={metrics.marginCushion}
            isPercentage
            isPositive={false}
            info={{
              description: "Buffer before margin call. Higher percentage means more safety cushion.",
              formula: "(Available Margin / Total Margin) × 100"
            }}
          />
        </div>
      </div>

      {/* P&L Breakdown */}
      <div>
        <h3 className={`text-sm uppercase tracking-wider mb-4 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          P&L Breakdown
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-white' : 'text-gray-500'
              }`}>
              Unrealized P&L
            </div>
            <div className={metrics.unrealizedPnL >= 0 ? 'text-orange-500 text-lg' : 'text-red-500 text-lg'}>
              ${metrics.unrealizedPnL.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-white' : 'text-gray-500'
              }`}>
              Realized P&L
            </div>
            <div className={metrics.realizedPnL >= 0 ? 'text-orange-500 text-lg' : 'text-red-500 text-lg'}>
              ${metrics.realizedPnL.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Total Commissions
            </div>
            <div className="text-lg">
              ${metrics.totalCommissions.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-white' : 'text-gray-500'
              }`}>
              Net P&L
            </div>
            <div className={metrics.netPnL >= 0 ? 'text-orange-500 text-lg' : 'text-red-500 text-lg'}>
              ${metrics.netPnL.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
        </div>
      </div>

      {/* Trading Statistics */}
      <div>
        <h3 className={`text-sm uppercase tracking-wider mb-4 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Trading Statistics
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Total Trades
            </div>
            <div className="text-lg">{metrics.totalTrades}</div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Avg Win
            </div>
            <div className="text-lg text-orange-500">
              ${metrics.avgWin.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Avg Loss
            </div>
            <div className="text-lg text-red-500">
              ${metrics.avgLoss.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Total Notional
            </div>
            <div className="text-lg">
              ${metrics.totalNotional.toLocaleString('en-US', { minimumFractionDigits: 0 })}
            </div>
          </div>
        </div>
      </div>

      {/* Portfolio Overview */}
      <div>
        <h3 className={`text-sm uppercase tracking-wider mb-4 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
          Portfolio Overview
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Portfolio Value
            </div>
            <div className="text-lg">
              ${metrics.currentPortfolioValue.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Cash Available
            </div>
            <div className="text-lg">
              ${metrics.cashAvailable.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
          <div className={`p-4 rounded-lg ${theme === 'dark' ? 'bg-gray-900' : 'bg-gray-50'
            }`}>
            <div className={`text-sm mb-1 ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
              Margin Posted
            </div>
            <div className="text-lg">
              ${metrics.marginPosted.toLocaleString('en-US', { minimumFractionDigits: 2 })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

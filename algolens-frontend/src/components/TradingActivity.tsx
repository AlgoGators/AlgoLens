import React from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import type { Execution, FinalizedPosition } from '../domain/portfolio/portfolioData';
import { formatMetric } from '../domain/portfolio/formatMetric';
import { formatPrice } from '../domain/portfolio/formatPrice';

interface TradingActivityProps {
  executions: Execution[];
  finalizedPositions: FinalizedPosition[];
}

export function TradingActivity({ executions, finalizedPositions }: TradingActivityProps) {
  const { theme } = useTheme();

  // Only fills whose contract size is known contribute to the total, and the
  // count below says how many were left out rather than adding them as zero.
  const priced = executions.filter(e => e.notional != null);
  const unpricedFills = executions.length - priced.length;
  const totalNotional = priced.reduce((sum, exec) => sum + (exec.notional as number), 0);
  const totalCommissions = executions.reduce((sum, exec) => sum + exec.commission, 0);

  // Only lots whose realised P&L the engine actually published contribute to
  // the total, and the count below says how many were left out. Summing an
  // unknown as zero would report a partial total as a complete one.
  const settled = finalizedPositions.filter(p => p.realizedPnL != null);
  const unsettledLots = finalizedPositions.length - settled.length;
  const totalRealized = settled.reduce((sum, p) => sum + (p.realizedPnL as number), 0);

  return (
    <div className="space-y-6">
      {/* Daily Executions */}
      <div>
        <h3 className={`text-sm uppercase tracking-wider mb-4 ${
          theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
        }`}>
          Daily Executions
        </h3>
        
        <div className={`border rounded-lg overflow-hidden ${
          theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
          {/* Header */}
          <div className={`grid grid-cols-7 gap-4 p-4 text-sm border-b ${
            theme === 'dark'
              ? 'bg-gray-900 border-gray-800 text-gray-400'
              : 'bg-gray-50 border-gray-200 text-gray-500'
          }`}>
            <div>Date</div>
            <div>Symbol</div>
            <div>Side</div>
            <div className="text-right">Quantity</div>
            <div className="text-right">Price</div>
            <div className="text-right">Notional</div>
            <div className="text-right">Commission</div>
          </div>

          {/* Executions */}
          {executions.map((execution, index) => (
            <div
              key={`${execution.symbol}-${index}`}
              className={`grid grid-cols-7 gap-4 p-4 transition-colors ${
                theme === 'dark' ? 'hover:bg-gray-900' : 'hover:bg-gray-50'
              } ${
                index !== executions.length - 1
                  ? theme === 'dark'
                    ? 'border-b border-gray-800'
                    : 'border-b border-gray-200'
                  : ''
              }`}
            >
              <div className={`text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-500'}`}>
                {execution.date
                  ? new Date(execution.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
                  : '-'}
              </div>
              <div>{execution.symbol}</div>
              <div>
                <span className={`px-2 py-1 rounded text-xs ${
                  execution.side === 'BUY'
                    ? 'bg-orange-500 bg-opacity-20 text-orange-500'
                    : 'bg-red-500 bg-opacity-20 text-red-500'
                }`}>
                  {execution.side}
                </span>
              </div>
              <div className="text-right">{execution.quantity}</div>
              <div className="text-right">
                {formatPrice(execution.price)}
              </div>
              <div className="text-right">
                {execution.notional == null ? '—' : `$${execution.notional.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </div>
              <div className="text-right">
                ${execution.commission.toFixed(2)}
              </div>
            </div>
          ))}

          {/* Summary */}
          <div className={`grid grid-cols-7 gap-4 p-4 border-t ${
            theme === 'dark'
              ? 'bg-gray-900 border-gray-800'
              : 'bg-gray-50 border-gray-200'
          }`}>
            <div className="col-span-5">Trades: {executions.length}</div>
            <div className="text-right">
              <div className={`text-sm ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
                Total
              </div>
              <div>${totalNotional.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</div>
            </div>
            <div className="text-right">
              ${totalCommissions.toFixed(2)}
            </div>
          </div>
        </div>
      </div>

      {/* Finalized Positions */}
      <div>
        <h3 className={`text-sm uppercase tracking-wider mb-4 ${
          theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
        }`}>
          Yesterday's Finalized Position Results
        </h3>
        
        <div className={`border rounded-lg overflow-hidden ${
          theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
        }`}>
          {/* Header */}
          <div className={`grid grid-cols-5 gap-4 p-4 text-sm border-b ${
            theme === 'dark' 
              ? 'bg-gray-900 border-gray-800 text-gray-400' 
              : 'bg-gray-50 border-gray-200 text-gray-500'
          }`}>
            <div>Symbol</div>
            <div className="text-right">Quantity</div>
            <div className="text-right">Entry Price</div>
            <div className="text-right">Exit Price</div>
            <div className="text-right">Realized P&L</div>
          </div>

          {/* Positions */}
          {finalizedPositions.map((position, index) => (
            <div
              key={`${position.symbol}-${index}`}
              className={`grid grid-cols-5 gap-4 p-4 transition-colors ${
                theme === 'dark' ? 'hover:bg-gray-900' : 'hover:bg-gray-50'
              } ${
                index !== finalizedPositions.length - 1 
                  ? theme === 'dark' 
                    ? 'border-b border-gray-800' 
                    : 'border-b border-gray-200' 
                  : ''
              }`}
            >
              <div>{position.symbol}</div>
              <div className="text-right">{position.quantity.toFixed(2)}</div>
              <div className="text-right">
                {position.entryPrice == null ? '\u2014' : formatPrice(position.entryPrice)}
              </div>
              {/* A lot that is gone today exited at a price nothing here
                  records. Unknown, not yesterday's entry price. */}
              <div className="text-right">
                {position.exitPrice == null ? '\u2014' : formatPrice(position.exitPrice)}
              </div>
              <div className={`text-right ${
                position.realizedPnL == null
                  ? ''
                  : position.realizedPnL >= 0 ? 'text-orange-500' : 'text-red-500'
              }`}>
                {position.realizedPnL == null
                  ? '\u2014'
                  : `$${position.realizedPnL.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </div>
            </div>
          ))}

          {/* Summary */}
          <div className={`grid grid-cols-5 gap-4 p-4 border-t ${
            theme === 'dark' 
              ? 'bg-gray-900 border-gray-800' 
              : 'bg-gray-50 border-gray-200'
          }`}>
            <div className="col-span-4">
              Total Positions: {finalizedPositions.length}
              {unsettledLots > 0 && (
                <span className={`ml-2 text-sm ${
                  theme === 'dark' ? 'text-amber-400' : 'text-amber-600'
                }`}>
                  ({unsettledLots} with no realised P&L on record, not in the total)
                </span>
              )}
            </div>
            <div className="text-right">
              <div className={`text-sm ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
                Total P&L
              </div>
              {/* Only lots the engine published a realised P&L for are in
                  this total. Counting an unknown as zero would report a
                  partial figure as a complete one. */}
              <div className={
                settled.length === 0 ? '' : totalRealized >= 0 ? 'text-orange-500' : 'text-red-500'
              }>
                {settled.length === 0
                  ? '\u2014'
                  : `$${totalRealized.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

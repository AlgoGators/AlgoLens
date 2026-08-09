import React from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import type { Execution, FinalizedPosition } from '../domain/portfolio/portfolioData';

interface TradingActivityProps {
  executions: Execution[];
  finalizedPositions: FinalizedPosition[];
}

export function TradingActivity({ executions, finalizedPositions }: TradingActivityProps) {
  const { theme } = useTheme();

  const totalNotional = executions.reduce((sum, exec) => sum + exec.notional, 0);
  const totalCommissions = executions.reduce((sum, exec) => sum + exec.commission, 0);

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
                ${execution.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
              <div className="text-right">
                ${execution.notional.toLocaleString('en-US', { minimumFractionDigits: 2 })}
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
              <div>${totalNotional.toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
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
                ${position.entryPrice.toFixed(2)}
              </div>
              <div className="text-right">
                ${position.exitPrice.toFixed(2)}
              </div>
              <div className={`text-right ${
                position.realizedPnL >= 0 ? 'text-orange-500' : 'text-red-500'
              }`}>
                ${position.realizedPnL.toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
            </div>
          ))}

          {/* Summary */}
          <div className={`grid grid-cols-5 gap-4 p-4 border-t ${
            theme === 'dark' 
              ? 'bg-gray-900 border-gray-800' 
              : 'bg-gray-50 border-gray-200'
          }`}>
            <div className="col-span-4">Total Positions: {finalizedPositions.length}</div>
            <div className="text-right">
              <div className={`text-sm ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
              }`}>
                Total P&L
              </div>
              <div className={
                finalizedPositions.reduce((sum, pos) => sum + pos.realizedPnL, 0) >= 0 
                  ? 'text-orange-500' 
                  : 'text-red-500'
              }>
                ${finalizedPositions.reduce((sum, pos) => sum + pos.realizedPnL, 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

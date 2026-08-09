import React from 'react';
import { useTheme } from '../adapters/react/ThemeContext';
import type { Position } from '../domain/portfolio/portfolioData';

interface PositionBreakdownProps {
  positions: Position[];
}

export function PositionBreakdown({ positions }: PositionBreakdownProps) {
  const { theme } = useTheme();

  const totalNotional = positions.reduce((sum, pos) => sum + (pos.notional || pos.currentValue), 0);

  return (
    <div>
      <h3 className={`text-sm uppercase tracking-wider mb-4 ${
        theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
      }`}>
        Today's Positions
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
          <div className="text-right">Market Price</div>
          <div className="text-right">Notional</div>
          <div className="text-right">% of Total</div>
        </div>

        {/* Positions */}
        {positions.map((position, index) => {
          const notional = position.notional || position.currentValue;
          const percentOfTotal = position.percentOfTotal || (notional / totalNotional) * 100;
          const marketPrice = position.marketPrice || position.currentValue / position.shares;

          return (
            <div
              key={position.symbol}
              className={`grid grid-cols-5 gap-4 p-4 transition-colors ${
                theme === 'dark' ? 'hover:bg-gray-900' : 'hover:bg-gray-50'
              } ${
                index !== positions.length - 1 
                  ? theme === 'dark' 
                    ? 'border-b border-gray-800' 
                    : 'border-b border-gray-200' 
                  : ''
              }`}
            >
              <div>
                <div className="mb-1">{position.symbol}</div>
                <div className={`text-sm ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  {position.name}
                </div>
              </div>
              <div className="text-right">{position.shares}</div>
              <div className="text-right">
                ${marketPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className="text-right">
                ${notional.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </div>
              <div className="text-right">{percentOfTotal.toFixed(2)}%</div>
            </div>
          );
        })}

        {/* Summary */}
        <div className={`grid grid-cols-5 gap-4 p-4 border-t ${
          theme === 'dark' 
            ? 'bg-gray-900 border-gray-800' 
            : 'bg-gray-50 border-gray-200'
        }`}>
          <div className="col-span-3">
            <div className="mb-1">Active Positions: {positions.length}</div>
          </div>
          <div className="text-right">
            <div className={`text-sm ${
              theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
            }`}>
              Total Notional
            </div>
            <div>${totalNotional.toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
          </div>
          <div className="text-right">100.00%</div>
        </div>
      </div>
    </div>
  );
}

import React, { useState } from 'react';
import { Pencil, Plus } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';
import { useAuth } from '../adapters/react/AuthContext';
import { isInternalRole } from '../domain/identity/user';
import type { Position } from '../domain/portfolio/portfolioData';
import { EditPositionModal } from './EditPositionModal';

interface PositionBreakdownProps {
  positions: Position[];
  /**
   * Supplying this turns on manual editing for internal roles. Omitted (the
   * subscriber-facing views), the table stays exactly as it was: read-only.
   */
  strategyId?: string;
  /** Called after a successful write so the caller can refetch the book. */
  onEdited?: () => void;
}

type EditTarget = {
  symbol: string | null;
  existing: { quantity: number; average_price: number | null } | null;
};

export function PositionBreakdown({ positions, strategyId, onEdited }: PositionBreakdownProps) {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [editing, setEditing] = useState<EditTarget | null>(null);

  // The backend enforces this too (@internal_only); this only avoids offering a
  // button that would come back 403.
  const canEdit = Boolean(strategyId) && isInternalRole(user?.role);
  const columns = canEdit ? 'grid-cols-6' : 'grid-cols-5';

  const totalNotional = positions.reduce((sum, pos) => sum + (pos.notional || pos.currentValue), 0);

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className={`text-sm uppercase tracking-wider ${
          theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
        }`}>
          Today's Positions
        </h3>
        {canEdit && (
          <button
            onClick={() => setEditing({ symbol: null, existing: null })}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm ${
              theme === 'dark'
                ? 'bg-gray-800 hover:bg-gray-700 text-white'
                : 'bg-gray-100 hover:bg-gray-200 text-black'
            }`}
          >
            <Plus className="w-4 h-4" />
            Add position
          </button>
        )}
      </div>

      <div className={`border rounded-lg overflow-hidden ${
        theme === 'dark' ? 'border-gray-800' : 'border-gray-200'
      }`}>
        {/* Header */}
        <div className={`grid ${columns} gap-4 p-4 text-sm border-b ${
          theme === 'dark'
            ? 'bg-gray-900 border-gray-800 text-gray-400'
            : 'bg-gray-50 border-gray-200 text-gray-500'
        }`}>
          <div>Symbol</div>
          <div className="text-right">Quantity</div>
          <div className="text-right">Market Price</div>
          <div className="text-right">Notional</div>
          <div className="text-right">% of Total</div>
          {canEdit && <div className="text-right">Adjust</div>}
        </div>

        {/* Positions */}
        {positions.map((position, index) => {
          const notional = position.notional || position.currentValue;
          const percentOfTotal = position.percentOfTotal || (notional / totalNotional) * 100;
          const marketPrice = position.marketPrice || position.currentValue / position.shares;

          return (
            <div
              key={position.symbol}
              className={`grid ${columns} gap-4 p-4 transition-colors ${
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
              {canEdit && (
                <div className="text-right">
                  <button
                    aria-label={`Adjust ${position.symbol}`}
                    onClick={() =>
                      setEditing({
                        symbol: position.symbol,
                        existing: {
                          quantity: position.shares,
                          average_price: position.marketPrice ?? null,
                        },
                      })
                    }
                    className={`inline-flex items-center justify-center rounded-lg p-1.5 ${
                      theme === 'dark' ? 'hover:bg-gray-800' : 'hover:bg-gray-200'
                    }`}
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                </div>
              )}
            </div>
          );
        })}

        {/* Summary */}
        <div className={`grid ${columns} gap-4 p-4 border-t ${
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
          {canEdit && <div />}
        </div>
      </div>

      {editing && strategyId && (
        <EditPositionModal
          strategyId={strategyId}
          symbol={editing.symbol}
          existing={editing.existing}
          theme={theme}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            onEdited?.();
          }}
        />
      )}
    </div>
  );
}

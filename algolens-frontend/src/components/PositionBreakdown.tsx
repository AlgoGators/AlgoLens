import React, { useState } from 'react';
import { Pencil, Plus } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';
import { useAuth } from '../adapters/react/useAuth';
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
  /** The book these positions came from. Passed to the editor so it writes there. */
  portfolioId?: string;
  /** Every book this strategy trades in; more than one means this table is partial. */
  books?: string[];
  /** Called after a successful write so the caller can refetch the book. */
  onEdited?: () => void;
}

type EditTarget = {
  symbol: string | null;
  existing: { quantity: number; average_price: number | null } | null;
};

export function PositionBreakdown({
  positions,
  strategyId,
  portfolioId,
  books,
  onEdited,
}: PositionBreakdownProps) {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [editing, setEditing] = useState<EditTarget | null>(null);

  // The backend enforces this too (@internal_only); this only avoids offering a
  // button that would come back 403.
  const canEdit = Boolean(strategyId) && isInternalRole(user?.role);
  const columns = canEdit ? 'grid-cols-6' : 'grid-cols-5';

  // Positions with no known price contribute a placeholder zero, so they are
  // excluded rather than quietly dragging the total down.
  const pricedPositions = positions.filter(p => !p.priceUnknown);
  const totalNotional = pricedPositions.reduce(
    (sum, pos) => sum + (pos.notional || pos.currentValue),
    0,
  );
  const unpricedCount = positions.length - pricedPositions.length;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className={`text-sm uppercase tracking-wider ${
          theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
        }`}>
          Today's Positions
          {portfolioId && (
            <span className={`ml-2 font-mono normal-case ${
              theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
            }`}>
              {portfolioId}
            </span>
          )}
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

      {/* A strategy can trade a different universe in each book it belongs to.
          This table is one book; saying so is the difference between a partial
          view and a wrong one. */}
      {books && books.length > 1 && (
        <div className={`mb-4 rounded-lg border px-4 py-3 text-sm ${
          theme === 'dark'
            ? 'border-gray-800 bg-gray-900 text-gray-300'
            : 'border-gray-200 bg-gray-50 text-gray-700'
        }`}>
          This strategy also trades in{' '}
          {books.filter(b => b !== portfolioId).map((b, i, arr) => (
            <span key={b}>
              <span className="font-mono">{b}</span>
              {i < arr.length - 1 ? ', ' : ''}
            </span>
          ))}
          . Those positions, and their risk limits, are separate and are not shown here.
        </div>
      )}

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
              {/* An unknown price makes the price, the notional and the share
                  of the book all meaningless. Showing $0.00 would state that
                  the position is worthless. */}
              <div className="text-right">
                {position.priceUnknown
                  ? '—'
                  : `$${marketPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </div>
              <div className="text-right">
                {position.priceUnknown
                  ? '—'
                  : `$${notional.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </div>
              <div className="text-right">
                {position.priceUnknown ? '—' : `${percentOfTotal.toFixed(2)}%`}
              </div>
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
            {unpricedCount > 0 && (
              <div className={`text-sm ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`}>
                Total excludes {unpricedCount}{' '}
                {unpricedCount === 1 ? 'position' : 'positions'} with no known price.
              </div>
            )}
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
          portfolioId={portfolioId}
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

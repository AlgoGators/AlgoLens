import React, { useEffect, useId, useState } from 'react';
import { formatPrice } from '../domain/portfolio/formatPrice';
import { Pencil, Plus } from 'lucide-react';
import { useTheme } from '../adapters/react/ThemeContext';
import { useAuth } from '../adapters/react/useAuth';
import { isInternalRole } from '../domain/identity/user';
import type { Position, PositionStream } from '../domain/portfolio/portfolioData';
import { positionValueEvidence, type ExistingPositionValue } from '../domain/portfolio/positionEdit';
import { EditPositionModal } from './EditPositionModal';
import { counted } from '../domain/text/pluralize';

interface PositionBreakdownProps {
  positions: Position[];
  /** Must be an identified QT snapshot before edit controls can appear. */
  positionStream?: PositionStream | null;
  /** Explicit engine identities supplied for this snapshot; never inferred. */
  positionStrategyNames?: string[];
  /**
   * Supplying this turns on manual editing for internal roles. Omitted (the
   * subscriber-facing views), the table stays exactly as it was: read-only.
   */
  strategyId?: string;
  /** The book these positions came from. Passed to the editor so it writes there. */
  portfolioId?: string;
  /** Actual selected QT snapshot date, never inferred as today by the browser. */
  positionDate?: string | null;
  positionsEditable?: boolean;
  positionEditUnavailableReason?: string | null;
  /**
   * Present when edits are made in the QT proposal workspace instead of the
   * legacy dialog. Renders an "Edit positions" button that takes the reader
   * there. It only navigates; it never enables a write.
   */
  onEditInWorkspace?: () => void;
  /**
   * When set, the "Edit positions" button is still shown to internal readers
   * but disabled, and this sentence is on the page beside it explaining why.
   */
  workspaceEditUnavailableReason?: string | null;
  /** Every AlgoLens registry book membership; more than one means this table may be partial. */
  books?: string[];
  /**
   * Shown beside the heading in place of the plain book name -- a box the
   * reader can open to switch book. The caller owns which book is loaded.
   */
  bookControl?: React.ReactNode;
  /** Called after a successful write so the caller can refetch the book. */
  onEdited?: () => void;
}

type EditTarget = {
  symbol: string | null;
  strategyName: string;
  existing: ExistingPositionValue | null;
};

export function PositionBreakdown({
  positions,
  positionStream,
  positionStrategyNames,
  strategyId,
  portfolioId,
  positionDate,
  positionsEditable,
  positionEditUnavailableReason,
  onEditInWorkspace,
  workspaceEditUnavailableReason,
  books,
  bookControl,
  onEdited,
}: PositionBreakdownProps) {
  const { theme } = useTheme();
  const { user } = useAuth();
  const [editing, setEditing] = useState<EditTarget | null>(null);

  // The backend enforces this too (@internal_only); this only avoids offering a
  // button that would come back 403.
  const isInternalMember = isInternalRole(user?.role);
  // Fail closed for legacy/unknown payloads. Only the API's explicit true says
  // this is the current server-date snapshot with resolvable engine identity.
  const canEdit = Boolean(strategyId) && positionStream === 'qt'
    && isInternalMember && positionsEditable === true;
  useEffect(() => {
    setEditing(null);
  }, [strategyId, portfolioId, positionStream, positionDate, positionsEditable, user?.id, user?.role]);
  const addIdentityFieldIsValid = Array.isArray(positionStrategyNames)
    && positionStrategyNames.every(
      name => typeof name === 'string' && name.trim().length > 0,
    );
  // Preserve opaque engine keys exactly. A partially malformed field cannot
  // be salvaged into an apparently unambiguous write capability.
  const addStrategyNames = addIdentityFieldIsValid
    ? [...new Set(positionStrategyNames)]
    : [];
  const canAdd = canEdit && addStrategyNames.length === 1;
  const columns = canEdit ? 'grid-cols-6' : 'grid-cols-5';

  // The way in to editing for an internal reader whose legacy editor is not
  // available. With a reason it is disabled and the reason is written on the
  // page (the grey box below when it already says the same thing, otherwise a
  // line of its own), never only in a tooltip.
  const statusBoxId = useId();
  const reasonId = useId();
  const editEntryReason = workspaceEditUnavailableReason?.trim() || null;
  const showEditEntry = isInternalMember && !canEdit && (!!editEntryReason || !!onEditInWorkspace);
  const statusBoxShown = isInternalMember && !canEdit && !!positionEditUnavailableReason;
  const reasonInStatusBox = statusBoxShown && editEntryReason === positionEditUnavailableReason?.trim();

  // Only rows whose exposure could actually be computed contribute to the
  // total. A row missing a price or a contract size is counted as missing, not
  // as zero, and the banner below says how many.
  const pricedPositions = positions.filter(p => p.notional != null);
  const unpricedCount = positions.length - pricedPositions.length;
  const totalNotional = pricedPositions.reduce(
    (sum, pos) => sum + (pos.notional as number),
    0,
  );
  const hasPricedTotal = pricedPositions.length > 0;
  const hasCompleteTotal = positions.length > 0 && unpricedCount === 0;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className={`text-sm uppercase tracking-wider ${
            theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
          }`}>
            {positionStream === 'system' ? 'Model / System positions'
              : positionStream === 'qt' ? 'QT positions' : 'Legacy / Unscoped positions'}
            {' '}snapshot {positionDate ?? '(date unavailable)'}
            {!bookControl && portfolioId && (
              <span className={`ml-2 font-mono normal-case ${
                theme === 'dark' ? 'text-gray-500' : 'text-gray-400'
              }`}>
                {portfolioId}
              </span>
            )}
          </h3>
          {bookControl}
        </div>
        {showEditEntry && (
          <div className="flex flex-col items-end gap-1">
            <button
              type="button"
              data-qt-edit-entry=""
              disabled={!!editEntryReason}
              onClick={editEntryReason ? undefined : onEditInWorkspace}
              aria-describedby={editEntryReason ? (reasonInStatusBox ? statusBoxId : reasonId) : undefined}
              className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 ${
                editEntryReason
                  ? theme === 'dark'
                    ? 'cursor-not-allowed bg-gray-800 text-gray-400'
                    : 'cursor-not-allowed bg-gray-100 text-gray-600'
                  : 'bg-blue-600 text-white hover:bg-blue-700'
              }`}
            >
              <Pencil className="w-4 h-4" />
              Edit positions
            </button>
            {editEntryReason && !reasonInStatusBox && (
              <p id={reasonId} className={`max-w-xs text-right text-xs ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                {editEntryReason}
              </p>
            )}
          </div>
        )}
        {canAdd && (
          <button
            onClick={() => setEditing({ symbol: null, strategyName: addStrategyNames[0], existing: null })}
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

      {statusBoxShown && (
        <div id={statusBoxId} role="status" className={`mb-4 rounded-lg border px-4 py-3 text-sm ${
          theme === 'dark' ? 'border-gray-800 bg-gray-900 text-gray-300' : 'border-gray-200 bg-gray-50 text-gray-700'
        }`}>
          {positionEditUnavailableReason}
        </div>
      )}

      {/* Registry membership does not prove that the trading runtime published
          positions for a book. Keep the reporting relationship and runtime
          data availability distinct, especially for flat snapshots. */}
      {books && books.length > 1 && (
        <div className={`mb-4 rounded-lg border px-4 py-3 text-sm ${
          theme === 'dark'
            ? 'border-gray-800 bg-gray-900 text-gray-300'
            : 'border-gray-200 bg-gray-50 text-gray-700'
        }`}>
          This strategy is also registered in{' '}
          {books.filter(b => b !== portfolioId).map((b, i, arr) => (
            <span key={b}>
              <span className="font-mono">{b}</span>
              {i < arr.length - 1 ? ', ' : ''}
            </span>
          ))}
          {' '}for AlgoLens reporting. Positions and risk limits appear for a book only when
          published by the trading runtime
          {bookControl ? '; choose the book in the box above to see them.' : '; other books are not shown here.'}
        </div>
      )}

      <div className="overflow-x-auto">
        <div className={`min-w-[760px] border rounded-lg overflow-hidden ${
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
          <div className="text-right">{unpricedCount > 0 ? 'Share of known displayed exposure' : 'Share of displayed exposure'}</div>
          {canEdit && <div className="text-right">Adjust</div>}
        </div>

        {/* Positions */}
        {positions.map((position, index) => {
          // No derived fallbacks. Each of these is either published or unknown;
          // computing a stand-in here is how a placeholder becomes a figure
          // somebody trades on.
          const notional = position.notional ?? null;
          // Share of the book's total exposure, which is what the footer
          // totals to 100%. The API's percentOfTotal is a share of portfolio
          // VALUE, a different denominator entirely -- using it here printed
          // 588% under a column header that sums to 100%.
          const percentOfTotal =
            notional != null && totalNotional > 0 ? (notional / totalNotional) * 100 : null;
          const marketPrice = position.marketPrice ?? null;
          const existingValue: ExistingPositionValue = {
            quantity: position.shares,
            average_price: position.costBasis ?? null,
            quantity_exact: position.quantity_exact,
            average_price_exact: position.average_price_exact,
          };
          const evidence = positionValueEvidence(existingValue);

          return (
            <div
              key={`${position.symbol}:${position.strategyName ?? index}`}
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
              <div className="text-right">{evidence.quantity}</div>
              {/* An unknown price makes the price, the notional and the share
                  of the book all meaningless. Showing $0.00 would state that
                  the position is worthless. */}
              <div className="text-right">
                {marketPrice == null
                  ? '—'
                  : formatPrice(marketPrice)}
              </div>
              <div className="text-right">
                {notional == null
                  ? '—'
                  : `$${notional.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
              </div>
              <div className="text-right">
                {percentOfTotal == null ? '—' : `${percentOfTotal.toFixed(2)}%`}
              </div>
              {canEdit && (
                <div className="text-right">
                  {evidence.valid && (
                    <button
                      aria-label={`Adjust ${position.symbol}${position.strategyName ? ` (${position.strategyName})` : ''}`}
                      onClick={() =>
                        setEditing({
                          symbol: position.symbol,
                          strategyName: position.strategyName,
                          // The editor edits cost basis, not the market price.
                          existing: existingValue,
                        })
                      }
                      className={`inline-flex items-center justify-center rounded-lg p-1.5 ${
                        theme === 'dark' ? 'hover:bg-gray-800' : 'hover:bg-gray-200'
                      }`}
                    >
                      <Pencil className="w-4 h-4" />
                    </button>
                  )}
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
                Total excludes {counted(unpricedCount, 'position')} with unknown notional.
              </div>
            )}
          </div>
          <div className="text-right">
            <div className={`text-sm ${
              theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
            }`}>
              Total Notional
            </div>
            <div>
              {hasPricedTotal
                ? `$${totalNotional.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                : '\u2014'}
              {hasPricedTotal && !hasCompleteTotal && (
                <span className={`ml-1 text-sm ${theme === 'dark' ? 'text-amber-400' : 'text-amber-600'}`}>
                  partial
                </span>
              )}
            </div>
          </div>
          <div className="text-right">{hasCompleteTotal ? '100.00%' : '\u2014'}</div>
          {canEdit && <div />}
        </div>
        </div>
      </div>

      {editing && strategyId && canEdit && (
        <EditPositionModal
          strategyId={strategyId}
          strategyName={editing.strategyName}
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

import React, { useState, useEffect } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { PortfolioApiService, type OverrideRecord } from '../services/portfolioApi';
import { AlertCircle } from 'lucide-react';

interface OverrideHistoryProps {
  strategyId: string;
}

export function OverrideHistory({ strategyId }: OverrideHistoryProps) {
  const { theme } = useTheme();
  const [overrides, setOverrides] = useState<OverrideRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchOverrides = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await PortfolioApiService.getOverrides(strategyId);
        // Sort newest first
        const sorted = data.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
        setOverrides(sorted);
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        setError(`Failed to load override history: ${errorMessage}`);
      } finally {
        setIsLoading(false);
      }
    };

    fetchOverrides();
  }, [strategyId]);

  // Derive the "what changed" description from before_state and after_state
  const getChangeDescription = (before: Record<string, unknown>, after: Record<string, unknown>): string => {
    // before_state may be {} for a newly created position
    if (Object.keys(before).length === 0) {
      return 'New position';
    }

    const beforeQty = before.quantity;
    const afterQty = after.quantity;
    const beforePrice = before.average_price;
    const afterPrice = after.average_price;

    const changes: string[] = [];
    if (beforeQty !== afterQty) {
      changes.push(`qty: ${beforeQty} → ${afterQty}`);
    }
    if (beforePrice !== afterPrice) {
      changes.push(`price: ${beforePrice ?? 'n/a'} → ${afterPrice ?? 'n/a'}`);
    }

    return changes.length > 0 ? changes.join(', ') : 'No changes';
  };

  // Format date/time for display
  const formatDate = (dateStr: string): string => {
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center py-8 ${
        theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
      }`}>
        Loading override history...
      </div>
    );
  }

  if (error) {
    return (
      <div className={`p-4 rounded-lg border ${
        theme === 'dark'
          ? 'bg-red-950 border-red-900 text-red-100'
          : 'bg-red-50 border-red-200 text-red-900'
      }`}>
        {error}
      </div>
    );
  }

  if (overrides.length === 0) {
    return (
      <div className={`text-center py-8 ${
        theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
      }`}>
        No position overrides yet
      </div>
    );
  }

  return (
    <div>
      <h3 className={`text-sm uppercase tracking-wider mb-4 ${
        theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
      }`}>
        Override History
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
          <div>When</div>
          <div>Symbol</div>
          <div>What Changed</div>
          <div>Reason</div>
          <div>Who</div>
        </div>

        {/* Rows */}
        {overrides.map((record, index) => (
          <div
            key={record.id}
            className={`grid grid-cols-5 gap-4 p-4 border-b transition-colors ${
              theme === 'dark'
                ? 'hover:bg-gray-900 border-gray-800'
                : 'hover:bg-gray-50 border-gray-200'
            } ${
              record.overrode_risk
                ? theme === 'dark'
                  ? 'border-l-4 border-l-red-600 bg-red-950 bg-opacity-20'
                  : 'border-l-4 border-l-red-500 bg-red-50'
                : ''
            } ${
              index === overrides.length - 1
                ? theme === 'dark'
                  ? 'border-b-0'
                  : 'border-b-0'
                : ''
            }`}
          >
            <div className={`text-sm ${theme === 'dark' ? 'text-gray-300' : 'text-gray-600'}`}>
              {formatDate(record.created_at)}
            </div>

            <div className="font-medium">{record.symbol}</div>

            <div className={`text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}`}>
              {getChangeDescription(record.before_state, record.after_state)}
            </div>

            <div className={`text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}`}>
              {record.reason}
            </div>

            <div className="flex items-center gap-2">
              <div className={`text-sm ${theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}`}>
                User {record.user_id}
              </div>
              {record.overrode_risk && (
                <div className="flex items-center gap-1 px-2 py-1 rounded text-xs font-semibold bg-red-600 text-white">
                  <AlertCircle className="w-3 h-3" />
                  RISK OVERRIDE
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Config history: versions from newest to oldest, with revert buttons.
 * Marks the currently active version clearly.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { PortfolioApiService, type ConfigHistoryEntry } from '../services/portfolioApi';
import { AlertCircle, Check, X, RotateCcw } from 'lucide-react';

interface ConfigHistoryProps {
  strategyId: string;
}

export function ConfigHistory({ strategyId }: ConfigHistoryProps) {
  const { theme } = useTheme();

  const [entries, setEntries] = useState<ConfigHistoryEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revertingVersion, setRevertingVersion] = useState<number | null>(null);
  const [revertReason, setRevertReason] = useState('');
  const [revertError, setRevertError] = useState<string | null>(null);
  const [revertSuccess, setRevertSuccess] = useState<number | null>(null);

  // Fetch history on mount
  useEffect(() => {
    const fetchHistory = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await PortfolioApiService.getConfigHistory(strategyId);
        setEntries(data.versions);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
      } finally {
        setIsLoading(false);
      }
    };

    fetchHistory();
  }, [strategyId]);

  // Submit revert
  const handleRevert = useCallback(async (version: number) => {
    setRevertError(null);
    setRevertSuccess(null);

    if (!revertReason.trim()) {
      setRevertError('Please provide a reason for reverting');
      return;
    }

    try {
      setRevertingVersion(version);
      await PortfolioApiService.activateConfigVersion(strategyId, {
        version,
        reason: revertReason,
      });

      // Refresh history to show updated is_active flags
      const data = await PortfolioApiService.getConfigHistory(strategyId);
      setEntries(data.versions);

      setRevertSuccess(version);
      setRevertReason('');

      // Clear success message after 3 seconds
      setTimeout(() => setRevertSuccess(null), 3000);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setRevertError(message);
    } finally {
      setRevertingVersion(null);
    }
  }, [strategyId, revertReason]);

  // Loading state
  if (isLoading) {
    return (
      <div className={`flex items-center justify-center py-12 ${
        theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
      }`}>
        <div className="text-center">
          <div className="mb-2">Loading history...</div>
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className={`rounded-lg border p-6 ${
        theme === 'dark'
          ? 'bg-red-950 border-red-800'
          : 'bg-red-50 border-red-200'
      }`}>
        <div className="flex items-start gap-3">
          <AlertCircle className={`w-5 h-5 flex-shrink-0 ${
            theme === 'dark' ? 'text-red-400' : 'text-red-600'
          }`} />
          <div>
            <h3 className={`font-semibold mb-1 ${
              theme === 'dark' ? 'text-red-200' : 'text-red-900'
            }`}>
              Cannot Load History
            </h3>
            <p className={theme === 'dark' ? 'text-red-300' : 'text-red-800'}>
              {error}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Empty state
  if (entries.length === 0) {
    return (
      <div className={`rounded-lg border p-6 ${
        theme === 'dark'
          ? 'bg-gray-900 border-gray-800'
          : 'bg-gray-50 border-gray-200'
      }`}>
        <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>
          No configuration versions yet. Create a change to start the audit trail.
        </p>
      </div>
    );
  }

  return (
    <div>
      {revertSuccess && (
        <div className={`rounded-lg border p-4 mb-6 flex items-center gap-2 ${
          theme === 'dark'
            ? 'bg-green-950 border-green-800'
            : 'bg-green-50 border-green-200'
        }`}>
          <Check className={`w-5 h-5 ${
            theme === 'dark' ? 'text-green-400' : 'text-green-600'
          }`} />
          <span className={theme === 'dark' ? 'text-green-200' : 'text-green-800'}>
            Configuration reverted successfully. New version takes effect at the next session start.
          </span>
        </div>
      )}

      {revertError && (
        <div className={`rounded-lg border p-4 mb-6 flex items-start gap-2 ${
          theme === 'dark'
            ? 'bg-red-950 border-red-800'
            : 'bg-red-50 border-red-200'
        }`}>
          <X className={`w-5 h-5 flex-shrink-0 ${
            theme === 'dark' ? 'text-red-400' : 'text-red-600'
          }`} />
          <span className={theme === 'dark' ? 'text-red-200' : 'text-red-800'}>
            {revertError}
          </span>
        </div>
      )}

      {/* Version list: newest first */}
      <div className="space-y-4">
        {entries.map((entry) => (
          <div
            key={entry.id}
            className={`rounded-lg border p-4 ${
              entry.is_active
                ? theme === 'dark'
                  ? 'border-green-800 bg-green-950'
                  : 'border-green-200 bg-green-50'
                : theme === 'dark'
                  ? 'border-gray-800 bg-gray-900'
                  : 'border-gray-200 bg-white'
            }`}
          >
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="flex items-center gap-2">
                  <h4 className={`font-semibold ${
                    theme === 'dark' ? 'text-gray-200' : 'text-gray-900'
                  }`}>
                    Version {entry.version}
                  </h4>
                  {entry.is_active && (
                    <span className={`text-xs font-semibold px-2 py-1 rounded ${
                      theme === 'dark'
                        ? 'bg-green-900 text-green-200'
                        : 'bg-green-200 text-green-900'
                    }`}>
                      ACTIVE
                    </span>
                  )}
                </div>

                <div className={`text-xs mt-1 space-y-0.5 ${
                  theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
                }`}>
                  <div>
                    {new Date(entry.created_at).toLocaleDateString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      year: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </div>
                  <div>By {entry.created_by}</div>
                </div>
              </div>

              {/* Revert button (disabled if already active) */}
              {!entry.is_active && (
                <button
                  onClick={() => {
                    setRevertingVersion(entry.version);
                    setRevertReason('');
                    setRevertError(null);
                  }}
                  className={`flex items-center gap-1 px-3 py-1 rounded text-sm transition-colors ${
                    revertingVersion === entry.version
                      ? theme === 'dark'
                        ? 'bg-gray-800 text-gray-400'
                        : 'bg-gray-200 text-gray-600'
                      : theme === 'dark'
                        ? 'text-orange-400 hover:bg-gray-800'
                        : 'text-orange-600 hover:bg-gray-100'
                  }`}
                >
                  <RotateCcw className="w-4 h-4" />
                  Revert
                </button>
              )}
            </div>

            {/* Reason */}
            <p className={`text-sm mb-4 ${
              theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
            }`}>
              {entry.reason}
            </p>

            {/* Changes in this version */}
            {Object.keys(entry.overrides).length > 0 && (
              <div className={`text-xs mb-4 space-y-1 font-mono ${
                theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
              }`}>
                <div className={theme === 'dark' ? 'text-gray-500' : 'text-gray-500'}>
                  Changes:
                </div>
                {Object.entries(entry.overrides).map(([path, value]) => (
                  <div key={path}>
                    {path}: <span className={theme === 'dark' ? 'text-gray-300' : 'text-gray-900'}>{String(value)}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Revert form (shows when reverting this version) */}
            {revertingVersion === entry.version && (
              <div className={`rounded border-t pt-3 mt-3 ${
                theme === 'dark' ? 'border-gray-700' : 'border-gray-300'
              }`}>
                <label className={`block text-xs font-medium mb-2 ${
                  theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
                }`}>
                  Reason for reverting <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={revertReason}
                  onChange={(e) => setRevertReason(e.target.value)}
                  placeholder="Why are you reverting to this version?"
                  className={`w-full px-2 py-1 rounded border text-xs ${
                    theme === 'dark'
                      ? 'border-gray-700 bg-gray-800 text-white'
                      : 'border-gray-300 bg-white text-gray-900'
                  }`}
                  rows={2}
                />

                <div className="flex gap-2 mt-3">
                  <button
                    onClick={() => handleRevert(entry.version)}
                    className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
                      theme === 'dark'
                        ? 'bg-orange-600 text-white hover:bg-orange-700'
                        : 'bg-orange-500 text-white hover:bg-orange-600'
                    }`}
                  >
                    Confirm Revert
                  </button>
                  <button
                    onClick={() => setRevertingVersion(null)}
                    className={`px-3 py-1 rounded text-sm transition-colors ${
                      theme === 'dark'
                        ? 'text-gray-400 hover:bg-gray-800'
                        : 'text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

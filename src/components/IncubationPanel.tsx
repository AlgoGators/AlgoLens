import React, { useState, useEffect } from "react";
import { AlertCircle, TrendingUp, Clock, DollarSign, CheckCircle, Zap } from "lucide-react";
import {
  calculateIncubationProgress,
  formatIncubationDate,
  formatMockCapital,
  formatEquity,
  isWindowComplete,
  isNearEndOfWindow,
  validateMockCapital,
  validateReason,
} from "../lib/incubationUtils";

interface IncubatingStrategy {
  id: string;
  name: string;
  strategy_type: string;
  portfolio_id: string;
  mock_capital: number;
  incubation_started_at: string;
  days_elapsed: number;
  window_days: number;
}

interface IncubationPanelProps {
  onClose?: () => void;
}

export default function IncubationPanel({ onClose }: IncubationPanelProps) {
  const [strategies, setStrategies] = useState<IncubatingStrategy[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<IncubatingStrategy | null>(null);
  const [showPromoteDialog, setShowPromoteDialog] = useState(false);
  const [promoteReason, setPromoteReason] = useState("");
  const [promoteError, setPromoteError] = useState<string | null>(null);
  const [promoting, setPromoting] = useState(false);

  useEffect(() => {
    fetchStrategies();
  }, []);

  async function fetchStrategies() {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem("access_token");
      if (!token) {
        setError("Not authenticated");
        return;
      }

      const response = await fetch("/api/portfolio/incubation", {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        const data = await response.json();
        setError(data.error || `Error: ${response.status}`);
        return;
      }

      const data = await response.json();
      setStrategies(data.incubating_strategies || []);
    } catch (err) {
      setError(`Failed to fetch incubating strategies: ${err}`);
    } finally {
      setLoading(false);
    }
  }

  async function handlePromote() {
    if (!selectedStrategy) return;

    const [reasonValid, reasonError] = validateReason(promoteReason);
    if (!reasonValid) {
      setPromoteError(reasonError);
      return;
    }

    setPromoting(true);
    setPromoteError(null);

    try {
      const token = localStorage.getItem("access_token");
      const response = await fetch(
        `/api/portfolio/incubation/${selectedStrategy.id}/promote`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ reason: promoteReason }),
        }
      );

      if (!response.ok) {
        const data = await response.json();
        setPromoteError(data.error || `Error: ${response.status}`);
        return;
      }

      // Success: refresh list and close dialog
      setShowPromoteDialog(false);
      setPromoteReason("");
      setSelectedStrategy(null);
      await fetchStrategies();
    } catch (err) {
      setPromoteError(`Failed to promote: ${err}`);
    } finally {
      setPromoting(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center p-8">
        <div className="text-gray-500">Loading incubation strategies...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg">
        <div className="flex gap-2">
          <AlertCircle className="w-5 h-5 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="font-semibold text-red-900 dark:text-red-300">Error</h3>
            <p className="text-sm text-red-800 dark:text-red-400">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (strategies.length === 0) {
    return (
      <div className="text-center py-12 px-6">
        <TrendingUp className="w-12 h-12 text-gray-300 dark:text-gray-600 mx-auto mb-4" />
        <h3 className="text-lg font-semibold text-gray-700 dark:text-gray-300 mb-2">
          No Incubating Strategies
        </h3>
        <p className="text-gray-600 dark:text-gray-400">
          Strategies in incubation will appear here, running on mock capital for 3-4 months.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-4">
        <div className="flex gap-2">
          <AlertCircle className="w-5 h-5 text-blue-600 dark:text-blue-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm text-blue-800 dark:text-blue-300">
            <strong>Mock Capital:</strong> These strategies trade notional capital isolated
            from the real portfolio. They do not affect headline metrics or real positions.
          </div>
        </div>
      </div>

      <div className="space-y-4">
        {strategies.map((strategy) => {
          const progress = calculateIncubationProgress(
            strategy.days_elapsed,
            strategy.window_days
          );
          const isComplete = isWindowComplete(strategy.days_elapsed, strategy.window_days);
          const isNearEnd = isNearEndOfWindow(strategy.days_elapsed, strategy.window_days);

          return (
            <div
              key={strategy.id}
              className="border border-gray-200 dark:border-gray-700 rounded-lg p-6 hover:border-gray-300 dark:hover:border-gray-600 transition-colors"
            >
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
                    {strategy.name}
                  </h3>
                  <p className="text-sm text-gray-600 dark:text-gray-400">{strategy.id}</p>
                </div>
                {isComplete && (
                  <div className="bg-green-50 dark:bg-green-900/20 px-3 py-1 rounded-full">
                    <span className="text-sm font-medium text-green-700 dark:text-green-400">
                      Window Complete
                    </span>
                  </div>
                )}
                {isNearEnd && !isComplete && (
                  <div className="bg-yellow-50 dark:bg-yellow-900/20 px-3 py-1 rounded-full">
                    <span className="text-sm font-medium text-yellow-700 dark:text-yellow-400">
                      Ending Soon
                    </span>
                  </div>
                )}
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
                <div>
                  <div className="flex items-center gap-1 mb-1">
                    <DollarSign className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                    <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                      Mock Capital
                    </span>
                  </div>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    {formatMockCapital(strategy.mock_capital)}
                  </p>
                </div>

                <div>
                  <div className="flex items-center gap-1 mb-1">
                    <Clock className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                    <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                      Elapsed
                    </span>
                  </div>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    {strategy.days_elapsed}d/{strategy.window_days}d
                  </p>
                </div>

                <div>
                  <div className="flex items-center gap-1 mb-1">
                    <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                      Started
                    </span>
                  </div>
                  <p className="text-sm text-gray-900 dark:text-white">
                    {formatIncubationDate(strategy.incubation_started_at)}
                  </p>
                </div>

                <div>
                  <div className="flex items-center gap-1 mb-1">
                    <Zap className="w-4 h-4 text-gray-500 dark:text-gray-400" />
                    <span className="text-xs font-medium text-gray-600 dark:text-gray-400">
                      Progress
                    </span>
                  </div>
                  <p className="text-lg font-semibold text-gray-900 dark:text-white">
                    {Math.round(progress)}%
                  </p>
                </div>
              </div>

              {/* Progress Bar */}
              <div className="mb-6">
                <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full transition-all ${
                      isComplete
                        ? "bg-green-500"
                        : isNearEnd
                          ? "bg-yellow-500"
                          : "bg-blue-500"
                    }`}
                    style={{ width: `${Math.min(progress, 100)}%` }}
                  />
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setSelectedStrategy(strategy)}
                  className="px-4 py-2 text-gray-900 dark:text-white bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 rounded-lg transition-colors"
                >
                  View Performance
                </button>

                {!isComplete && (
                  <button
                    onClick={() => {
                      setSelectedStrategy(strategy);
                      setShowPromoteDialog(true);
                      setPromoteReason("");
                      setPromoteError(null);
                    }}
                    className="px-4 py-2 text-white bg-blue-600 hover:bg-blue-700 dark:bg-blue-700 dark:hover:bg-blue-800 rounded-lg transition-colors flex items-center gap-2"
                  >
                    <CheckCircle className="w-4 h-4" />
                    Promote to Live
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Promote Dialog */}
      {showPromoteDialog && selectedStrategy && (
        <div className="fixed inset-0 bg-black/50 dark:bg-black/70 flex items-center justify-center z-50 p-4">
          <div className="bg-white dark:bg-gray-800 rounded-lg max-w-md w-full">
            <div className="p-6">
              <h2 className="text-xl font-bold text-gray-900 dark:text-white mb-2">
                Promote to Live?
              </h2>
              <p className="text-gray-600 dark:text-gray-400 mb-4">
                {selectedStrategy.name} will enter the real portfolio and its mock positions
                will become real. This cannot be undone.
              </p>

              <div className="mb-4">
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
                  Reason for promotion
                </label>
                <textarea
                  value={promoteReason}
                  onChange={(e) => {
                    setPromoteReason(e.target.value);
                    setPromoteError(null);
                  }}
                  className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg dark:bg-gray-700 dark:text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g., 'Completed incubation with consistent positive returns...'"
                  rows={3}
                />
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                  Minimum 10 characters required.
                </p>
              </div>

              {promoteError && (
                <div className="mb-4 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded text-sm text-red-600 dark:text-red-400">
                  {promoteError}
                </div>
              )}

              <div className="flex gap-2 justify-end">
                <button
                  onClick={() => setShowPromoteDialog(false)}
                  disabled={promoting}
                  className="px-4 py-2 text-gray-700 dark:text-gray-300 bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded-lg transition-colors disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handlePromote}
                  disabled={promoting}
                  className="px-4 py-2 text-white bg-blue-600 hover:bg-blue-700 dark:bg-blue-700 dark:hover:bg-blue-800 rounded-lg transition-colors disabled:opacity-50"
                >
                  {promoting ? "Promoting..." : "Confirm Promotion"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

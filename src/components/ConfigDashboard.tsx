/**
 * Config dashboard for strategy parameter overrides.
 *
 * THE CRITICAL PATTERN: effective (running now) vs active_overrides.overrides (pending at next session).
 * Every overridden field shows both values, unmistakably. A banner warns when pending changes exist.
 * A trader who changes a risk parameter must see and confirm it does not take effect immediately.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useTheme } from '../contexts/ThemeContext';
import { PortfolioApiService, type ConfigResponse } from '../services/portfolioApi';
import {
  flattenConfig,
  mergeOverrides,
  buildOverridePayload,
  coerceValue,
  canSubmitConfig,
  type FlatConfigField,
  type MergedField,
} from '../lib/configEdit';
import { AlertCircle, Check, X } from 'lucide-react';

interface ConfigDashboardProps {
  strategyId: string;
}

export function ConfigDashboard({ strategyId }: ConfigDashboardProps) {
  const { theme } = useTheme();

  // API state
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);

  // Form state: path -> edited value (or undefined if coerce failed)
  const [edits, setEdits] = useState<Record<string, any>>({});
  const [reason, setReason] = useState('');

  // Fetch config on mount
  useEffect(() => {
    const fetchConfig = async () => {
      try {
        setIsLoading(true);
        setError(null);
        const data = await PortfolioApiService.getConfig(strategyId);
        setConfig(data);
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        setError(message);
        setConfig(null);
      } finally {
        setIsLoading(false);
      }
    };

    fetchConfig();
  }, [strategyId]);

  // Flatten effective into form fields; compute running vs pending
  const fields = config ? flattenConfig(config.effective) : [];
  const merged = config ? mergeOverrides(config.effective, config.active_overrides?.overrides ?? null) : {};

  // Whether any field is overridden (pending != running)
  const hasOverrides = Object.values(merged).some(m => m.isOverridden);

  // Handle input change; coerce based on field type
  const handleChange = useCallback((path: string, rawValue: string, type: string) => {
    const coerced = coerceValue(rawValue, type as any);
    setEdits(prev => ({
      ...prev,
      [path]: coerced,
    }));
    // Clear success on any change
    setSubmitSuccess(false);
  }, []);

  // Submit new config
  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    setSubmitSuccess(false);

    if (!config) return;

    // Guard: must have changes and valid reason
    if (!canSubmitConfig(edits, reason)) {
      setSubmitError('Please provide a reason and at least one change');
      return;
    }

    // Build payload: only include changed values, nested by section
    const payload = buildOverridePayload(edits, config.effective);

    // Guard: payload must not be empty after build
    if (Object.keys(payload).length === 0) {
      setSubmitError('No changes to submit');
      return;
    }

    try {
      setIsSubmitting(true);
      await PortfolioApiService.updateConfig(strategyId, {
        overrides: payload,
        reason,
      });

      // Refresh config to show new active_overrides
      const updated = await PortfolioApiService.getConfig(strategyId);
      setConfig(updated);
      setEdits({});
      setReason('');
      setSubmitSuccess(true);

      // Clear success message after 3 seconds
      setTimeout(() => setSubmitSuccess(false), 3000);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setSubmitError(message);
    } finally {
      setIsSubmitting(false);
    }
  }, [config, edits, reason, strategyId]);

  // Loading state
  if (isLoading) {
    return (
      <div className={`flex items-center justify-center py-12 ${
        theme === 'dark' ? 'text-gray-400' : 'text-gray-500'
      }`}>
        <div className="text-center">
          <div className="mb-2">Loading configuration...</div>
        </div>
      </div>
    );
  }

  // Error state: either no permission, or network error
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
              Cannot Load Configuration
            </h3>
            <p className={theme === 'dark' ? 'text-red-300' : 'text-red-800'}>
              {error}
            </p>
          </div>
        </div>
      </div>
    );
  }

  // No config published yet
  if (!config) {
    return (
      <div className={`rounded-lg border p-6 ${
        theme === 'dark'
          ? 'bg-gray-900 border-gray-800'
          : 'bg-gray-50 border-gray-200'
      }`}>
        <p className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>
          The engine has not published its configuration yet. Please check back once a session has started.
        </p>
      </div>
    );
  }

  return (
    <div>
      {/* Banner: pending changes exist, will take effect at next session */}
      {hasOverrides && (
        <div className={`rounded-lg border p-4 mb-6 flex items-start gap-3 ${
          theme === 'dark'
            ? 'bg-amber-950 border-amber-800'
            : 'bg-amber-50 border-amber-200'
        }`}>
          <AlertCircle className={`w-5 h-5 flex-shrink-0 ${
            theme === 'dark' ? 'text-amber-400' : 'text-amber-600'
          }`} />
          <div>
            <h3 className={`font-semibold ${
              theme === 'dark' ? 'text-amber-200' : 'text-amber-900'
            }`}>
              Pending Changes
            </h3>
            <p className={`text-sm ${
              theme === 'dark' ? 'text-amber-300' : 'text-amber-800'
            }`}>
              Configuration changes take effect at the next session start. Current values are running now.
            </p>
          </div>
        </div>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit}>
        {/* Group fields by section */}
        {Array.from(new Set(fields.map(f => f.section))).map(section => {
          const sectionFields = fields.filter(f => f.section === section);

          return (
            <div key={section} className="mb-8">
              <h3 className={`text-sm font-semibold uppercase tracking-wider mb-4 ${
                theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
              }`}>
                {section}
              </h3>

              <div className="grid gap-4">
                {sectionFields.map(field => {
                  const mergedField = merged[field.path];
                  if (!mergedField) return null;

                  const isOverridden = mergedField.isOverridden;
                  const currentEditValue = edits[field.path];
                  const displayEditValue = currentEditValue !== undefined ? currentEditValue : '';

                  return (
                    <div
                      key={field.path}
                      className={`rounded-lg border p-4 ${
                        theme === 'dark'
                          ? 'border-gray-800 bg-gray-900'
                          : 'border-gray-200 bg-white'
                      }`}
                    >
                      <div className="flex items-start justify-between mb-3">
                        <label className={`text-sm font-medium ${
                          theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
                        }`}>
                          {field.key}
                        </label>
                        {isOverridden && (
                          <span className={`text-xs font-semibold px-2 py-1 rounded ${
                            theme === 'dark'
                              ? 'bg-amber-950 text-amber-200'
                              : 'bg-amber-100 text-amber-800'
                          }`}>
                            PENDING
                          </span>
                        )}
                      </div>

                      {/* Running vs Pending status */}
                      <div className={`text-xs mb-3 space-y-1 ${
                        theme === 'dark' ? 'text-gray-400' : 'text-gray-600'
                      }`}>
                        <div>
                          Running: <span className="font-mono font-semibold">{String(mergedField.running)}</span>
                        </div>
                        {isOverridden && (
                          <div>
                            Pending: <span className="font-mono font-semibold text-amber-500">{String(mergedField.pending)}</span>
                          </div>
                        )}
                      </div>

                      {/* Input or read-only display */}
                      {field.type === 'unsupported' ? (
                        <div className={`px-3 py-2 rounded ${
                          theme === 'dark'
                            ? 'bg-gray-800 text-gray-400'
                            : 'bg-gray-100 text-gray-600'
                        }`}>
                          <span className="text-xs">(Read-only: edit in config file)</span>
                        </div>
                      ) : field.type === 'boolean' ? (
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={displayEditValue === '' ? mergedField.running : displayEditValue}
                            onChange={(e) => handleChange(field.path, e.target.checked.toString(), field.type)}
                            className="rounded"
                            disabled={isSubmitting}
                          />
                          <span className={`text-sm ${
                            theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
                          }`}>
                            {displayEditValue === '' ? mergedField.running.toString() : displayEditValue.toString()}
                          </span>
                        </label>
                      ) : (
                        <input
                          type={field.type === 'number' ? 'number' : 'text'}
                          value={displayEditValue === '' ? mergedField.running : displayEditValue}
                          onChange={(e) => handleChange(field.path, e.target.value, field.type)}
                          step={field.type === 'number' ? 'any' : undefined}
                          className={`w-full px-3 py-2 rounded border ${
                            currentEditValue === undefined && displayEditValue !== ''
                              ? theme === 'dark'
                                ? 'border-red-700 bg-red-950'
                                : 'border-red-300 bg-red-50'
                              : theme === 'dark'
                                ? 'border-gray-700 bg-gray-800 text-white'
                                : 'border-gray-300 bg-white text-gray-900'
                          }`}
                          disabled={isSubmitting}
                        />
                      )}

                      {/* Coerce error feedback */}
                      {currentEditValue === undefined && displayEditValue !== '' && (
                        <div className="text-xs text-red-500 mt-2">
                          Invalid {field.type}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}

        {/* Reason field (mandatory) */}
        <div className="mb-6">
          <label className={`block text-sm font-medium mb-2 ${
            theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
          }`}>
            Reason for changes <span className="text-red-500">*</span>
          </label>
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Describe why you're making these changes..."
            className={`w-full px-3 py-2 rounded border ${
              theme === 'dark'
                ? 'border-gray-700 bg-gray-800 text-white'
                : 'border-gray-300 bg-white text-gray-900'
            }`}
            rows={3}
            disabled={isSubmitting}
          />
        </div>

        {/* Submit messages */}
        {submitSuccess && (
          <div className={`rounded-lg border p-4 mb-6 flex items-center gap-2 ${
            theme === 'dark'
              ? 'bg-green-950 border-green-800'
              : 'bg-green-50 border-green-200'
          }`}>
            <Check className={`w-5 h-5 ${
              theme === 'dark' ? 'text-green-400' : 'text-green-600'
            }`} />
            <span className={theme === 'dark' ? 'text-green-200' : 'text-green-800'}>
              Configuration updated successfully. Changes take effect at the next session start.
            </span>
          </div>
        )}

        {submitError && (
          <div className={`rounded-lg border p-4 mb-6 flex items-start gap-2 ${
            theme === 'dark'
              ? 'bg-red-950 border-red-800'
              : 'bg-red-50 border-red-200'
          }`}>
            <X className={`w-5 h-5 flex-shrink-0 ${
              theme === 'dark' ? 'text-red-400' : 'text-red-600'
            }`} />
            <span className={theme === 'dark' ? 'text-red-200' : 'text-red-800'}>
              {submitError}
            </span>
          </div>
        )}

        {/* Diff summary */}
        {Object.keys(edits).length > 0 && Object.values(edits).some(v => v !== undefined) && (
          <div className={`rounded-lg border p-4 mb-6 ${
            theme === 'dark'
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-300 bg-gray-50'
          }`}>
            <h4 className={`text-sm font-semibold mb-3 ${
              theme === 'dark' ? 'text-gray-300' : 'text-gray-700'
            }`}>
              Changes to submit
            </h4>
            <div className="space-y-1 text-xs font-mono">
              {Object.entries(edits).map(([path, newValue]) => {
                if (newValue === undefined) return null;
                const oldValue = config?.effective[path.split('.')[0]]?.[path.split('.')[1]];
                if (newValue === oldValue) return null;

                return (
                  <div key={path} className={theme === 'dark' ? 'text-gray-400' : 'text-gray-600'}>
                    {path}: <span className={theme === 'dark' ? 'text-gray-300' : 'text-gray-900'}>{String(newValue)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Submit button */}
        <button
          type="submit"
          disabled={!canSubmitConfig(edits, reason) || isSubmitting}
          className={`px-4 py-2 rounded font-medium transition-colors ${
            !canSubmitConfig(edits, reason) || isSubmitting
              ? theme === 'dark'
                ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                : 'bg-gray-200 text-gray-500 cursor-not-allowed'
              : theme === 'dark'
                ? 'bg-orange-600 text-white hover:bg-orange-700'
                : 'bg-orange-500 text-white hover:bg-orange-600'
          }`}
        >
          {isSubmitting ? 'Submitting...' : 'Submit Changes'}
        </button>
      </form>
    </div>
  );
}

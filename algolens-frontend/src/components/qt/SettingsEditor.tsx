/**
 * Desk settings editor (A7), ported from the closed config dashboard (#33/#34:
 * ConfigDashboard + ConfigHistory) onto the settings lane: the settings the
 * last live run used (live_run_metadata.settings_used), editable key by key,
 * saved as a new strategy_config version that the next live run merges over
 * the config files. Running and pending are shown side by side; a revert is a
 * new version. The database and email sections are never shown.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Check, RotateCcw } from 'lucide-react';
import { useTheme } from '../../adapters/react/ThemeContext';
import { DeskService } from '../../application/qt/deskService';
import {
  buildSettingChanges,
  canSubmitSettings,
  displaySetting,
  groupBySection,
  isEditable,
  pathKey,
  pathLabel,
  versionStatus,
  type SettingField,
  type SettingsState,
} from '../../domain/qt/settings';

export function SettingsEditor({ portfolioId }: { portfolioId: string }) {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const [state, setState] = useState<SettingsState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [revertTo, setRevertTo] = useState<number | null>(null);
  const [revertReason, setRevertReason] = useState('');

  const load = useCallback(async () => {
    try {
      setState(await DeskService.settings(portfolioId));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [portfolioId]);

  useEffect(() => {
    load();
  }, [load]);

  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const card = `rounded-lg border p-3 ${dark ? 'border-gray-800 bg-gray-900' : 'border-gray-200 bg-white'}`;
  const input = `w-full px-3 py-2 rounded border text-sm ${
    dark ? 'border-gray-700 bg-gray-800 text-white' : 'border-gray-300 bg-white text-gray-900'
  }`;

  if (error) return <p className="text-sm text-red-500">Settings unavailable: {error}</p>;
  if (!state) return <p className={`text-sm ${muted}`}>Loading settings...</p>;

  const { changes, invalid } = buildSettingChanges(state.fields, edits);
  const canSubmit = state.editable && canSubmitSettings(changes, invalid, reason) && !busy;
  const status = versionStatus(state);

  const submit = async () => {
    setBusy(true);
    setSubmitError(null);
    try {
      const version = await DeskService.saveSettings(portfolioId, changes, reason.trim());
      setEdits({});
      setReason('');
      setSuccess(`Saved as version ${version.version}. It takes effect at the next live run.`);
      await load();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const revert = async (version: number) => {
    setBusy(true);
    setSubmitError(null);
    try {
      const created = await DeskService.revertSettings(portfolioId, version, revertReason.trim());
      setRevertTo(null);
      setRevertReason('');
      setSuccess(
        `Restored ${version === 0 ? 'the config files' : `version ${version}`} as version ${created.version}. It takes effect at the next live run.`,
      );
      await load();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const fieldCard = (field: SettingField) => {
    const key = pathKey(field.path);
    const editable = state.editable && isEditable(field);
    const current = key in edits ? edits[key] : displaySetting(field.pending ?? field.value);
    const bad = key in edits && invalid.includes(pathLabel(field.path));
    return (
      <div key={key} className={card}>
        <div className="flex items-start justify-between gap-2">
          <label className="text-sm font-medium break-all" htmlFor={`setting-${key}`}>
            {pathLabel(field.path)}
          </label>
          {(field.pending !== null || field.pending_from_files) && (
            <span className={`text-xs font-semibold px-2 py-0.5 rounded ${dark ? 'bg-amber-950 text-amber-200' : 'bg-amber-100 text-amber-800'}`}>
              PENDING
            </span>
          )}
        </div>
        <div className={`text-xs mt-1 mb-2 space-y-0.5 ${muted}`}>
          <div>
            Running: <span className="font-mono font-semibold">{displaySetting(field.value) || 'null'}</span>
          </div>
          {field.pending !== null && (
            <div>
              Pending: <span className="font-mono font-semibold text-amber-500">{displaySetting(field.pending)}</span>
            </div>
          )}
          {field.pending_from_files && <div className="text-amber-500">Pending: back to the config file value</div>}
        </div>
        {!editable ? (
          <div className={`text-xs ${muted}`}>{isEditable(field) ? '' : '(read-only)'}</div>
        ) : field.type === 'boolean' ? (
          <select
            id={`setting-${key}`}
            className={input}
            value={current}
            disabled={busy}
            onChange={e => setEdits(prev => ({ ...prev, [key]: e.target.value }))}
          >
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        ) : (
          <input
            id={`setting-${key}`}
            className={`${input} ${bad ? 'border-red-500' : ''}`}
            value={current}
            disabled={busy}
            inputMode={field.type === 'number' ? 'decimal' : undefined}
            onChange={e => setEdits(prev => ({ ...prev, [key]: e.target.value }))}
          />
        )}
        {bad && <div className="text-xs text-red-500 mt-1">Invalid {field.type}</div>}
      </div>
    );
  };

  return (
    <div data-testid="settings-editor">
      <div className={`text-sm mb-3 ${muted}`}>
        <div>Running: {status.running}</div>
        {status.pending && <div className="text-amber-500">Pending: {status.pending}</div>}
      </div>

      {state.pending && (
        <div className={`rounded-lg border p-3 mb-4 flex items-start gap-2 ${dark ? 'bg-amber-950 border-amber-800' : 'bg-amber-50 border-amber-200'}`}>
          <AlertCircle className="w-4 h-4 mt-0.5 text-amber-500 flex-shrink-0" />
          <p className="text-sm">Saved changes take effect at the next live run. The running values are what trades now.</p>
        </div>
      )}

      {!state.running && (
        <p className={`text-sm mb-4 ${muted}`}>
          No live run has reported the settings it used yet. Editing opens after the first run that does.
        </p>
      )}

      {groupBySection(state.fields).map(([section, fields]) => (
        <div key={section} className="mb-5">
          <h5 className={`text-xs font-semibold uppercase tracking-wider mb-2 ${muted}`}>{section}</h5>
          <div className="grid gap-2 md:grid-cols-2">{fields.map(fieldCard)}</div>
        </div>
      ))}

      {state.editable && state.running && (
        <>
          {changes.length > 0 && (
            <div className={`${card} mb-3 text-xs font-mono`}>
              {changes.map(c => (
                <div key={pathKey(c.path)}>
                  {pathLabel(c.path)}: {displaySetting(c.value)}
                </div>
              ))}
            </div>
          )}
          <label className="block text-sm mb-2">
            Reason <span className="text-red-500">*</span>
            <textarea
              aria-label="Settings reason"
              className={`${input} mt-1`}
              rows={2}
              value={reason}
              disabled={busy}
              onChange={e => setReason(e.target.value)}
            />
          </label>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={submit}
            className="px-4 py-2 rounded bg-orange-500 text-white disabled:opacity-50"
          >
            {busy ? 'Saving...' : 'Save settings'}
          </button>
        </>
      )}

      {success && (
        <p className="mt-3 text-sm text-green-600 flex items-center gap-1">
          <Check className="w-4 h-4" /> {success}
        </p>
      )}
      {submitError && <p className="mt-3 text-sm text-red-500">{submitError}</p>}

      <h5 className={`text-xs font-semibold uppercase tracking-wider mt-6 mb-2 ${muted}`}>History</h5>
      {state.history.length === 0 && <p className={`text-sm ${muted}`}>No desk settings saved yet: the config files apply.</p>}
      <ul className="space-y-2">
        {state.history.map(v => (
          <li key={v.version} className={card}>
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>
                <span className="font-semibold">v{v.version}</span>
                {v.is_active && <span className="ml-2 text-xs text-orange-500">ACTIVE</span>}
                {state.running?.version === v.version && <span className="ml-2 text-xs text-green-600">RUNNING</span>}
                <span className={`ml-2 ${muted}`}>
                  {v.created_by}, {new Date(v.created_at).toLocaleString()}
                </span>
              </span>
              {state.editable && !v.is_active && state.running && (
                <button type="button" className="text-xs flex items-center gap-1 hover:underline" onClick={() => setRevertTo(v.version)}>
                  <RotateCcw className="w-3 h-3" /> Restore
                </button>
              )}
            </div>
            <p className={`text-xs mt-1 ${muted}`}>{v.reason}</p>
            <pre className={`text-xs mt-1 overflow-x-auto ${muted}`}>{JSON.stringify(v.overrides)}</pre>
          </li>
        ))}
        {state.editable && state.running && state.active && (
          <li>
            <button type="button" className="text-xs flex items-center gap-1 hover:underline" onClick={() => setRevertTo(0)}>
              <RotateCcw className="w-3 h-3" /> Restore the config files (no desk settings)
            </button>
          </li>
        )}
      </ul>

      {revertTo !== null && (
        <div className={`${card} mt-3`}>
          <p className="text-sm mb-2">
            Restore {revertTo === 0 ? 'the config files' : `version ${revertTo}`} as a new version. Reason:
          </p>
          <textarea
            aria-label="Restore reason"
            className={input}
            rows={2}
            value={revertReason}
            onChange={e => setRevertReason(e.target.value)}
          />
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              disabled={busy || !revertReason.trim()}
              onClick={() => revert(revertTo)}
              className="px-3 py-1 rounded bg-orange-500 text-white disabled:opacity-50"
            >
              Restore
            </button>
            <button type="button" className="px-3 py-1 rounded border" onClick={() => setRevertTo(null)}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

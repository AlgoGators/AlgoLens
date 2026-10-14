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
  filterFields,
  groupBySection,
  isConfigNote,
  isEditable,
  labelInSection,
  pathKey,
  pathLabel,
  readOpenState,
  sectionOpen,
  versionStatus,
  writeOpenState,
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
  const [query, setQuery] = useState('');
  // Open/closed sections and history, remembered per viewer and portfolio.
  const openKey = `algolens.qt.settings.open.${portfolioId}`;
  const [opened, setOpened] = useState<Record<string, boolean>>(() => readOpenState(openKey));
  const remember = (next: Record<string, boolean>) => {
    setOpened(next);
    writeOpenState(openKey, next);
  };

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
  const cell = `w-full px-2 py-1 rounded border text-xs font-mono ${
    dark ? 'border-gray-700 bg-gray-800 text-white' : 'border-gray-300 bg-white text-gray-900'
  }`;
  const rule = dark ? 'border-gray-800' : 'border-gray-100';

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

  // One compact row per setting: name, running value, pending value, inline edit.
  const fieldRow = (field: SettingField) => {
    const key = pathKey(field.path);
    const editable = state.editable && isEditable(field);
    const current = key in edits ? edits[key] : displaySetting(field.pending ?? field.value);
    const bad = key in edits && invalid.includes(pathLabel(field.path));
    const pending = field.pending !== null || field.pending_from_files;
    return (
      <tr key={key} className={`border-t ${rule} align-middle`}>
        <td className="py-1.5 pr-4">
          <label className="block text-xs font-mono break-words" htmlFor={`setting-${key}`} title={pathLabel(field.path)}>
            {labelInSection(field)}
          </label>
        </td>
        <td className="py-1.5 pr-4 text-xs font-mono text-right">
          {/* A long value (a list, a table) is cut; the whole of it is in the tooltip. */}
          <span className="block truncate" title={displaySetting(field.value) || 'null'}>
            {displaySetting(field.value) || 'null'}
          </span>
        </td>
        <td className="py-1.5 pr-4 text-xs font-mono text-right">
          {pending ? (
            <span
              className="block truncate text-amber-500"
              title={`Takes effect at the next live run: ${field.pending_from_files ? 'file value' : displaySetting(field.pending)}`}
            >
              {field.pending_from_files ? 'file value' : displaySetting(field.pending)}
            </span>
          ) : (
            <span className={muted}>-</span>
          )}
        </td>
        <td className="py-1.5">
          {!editable ? (
            <span className={`text-xs ${muted}`}>{isEditable(field) ? '' : 'read-only'}</span>
          ) : field.type === 'boolean' ? (
            <select
              id={`setting-${key}`}
              className={cell}
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
              className={`${cell} ${bad ? 'border-red-500' : ''}`}
              value={current}
              disabled={busy}
              title={bad ? `Invalid ${field.type}` : undefined}
              inputMode={field.type === 'number' ? 'decimal' : undefined}
              onChange={e => setEdits(prev => ({ ...prev, [key]: e.target.value }))}
            />
          )}
        </td>
      </tr>
    );
  };

  // Config comments (_note, _description, ...) are documentation, not settings.
  const shown = filterFields(state.fields.filter(f => !isConfigNote(f)), query);

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

      <input
        type="search"
        aria-label="Filter settings"
        placeholder="Filter settings (e.g. risk leverage)"
        className={`${input} mb-3`}
        value={query}
        onChange={e => setQuery(e.target.value)}
      />
      {shown.length === 0 && <p className={`text-sm mb-3 ${muted}`}>No setting matches.</p>}
      <div className="flex gap-3 mb-2 text-xs">
        <button
          type="button"
          data-testid="settings-expand-all"
          className={`hover:underline ${muted}`}
          onClick={() =>
            remember({ ...opened, ...Object.fromEntries(groupBySection(shown).map(([s]) => [s, true])) })
          }
        >
          Expand all
        </button>
        <button
          type="button"
          data-testid="settings-collapse-all"
          className={`hover:underline ${muted}`}
          onClick={() =>
            remember({ ...opened, ...Object.fromEntries(groupBySection(shown).map(([s]) => [s, false])) })
          }
        >
          Collapse all
        </button>
      </div>
      <div className="space-y-2 mb-5">
        {groupBySection(shown).map(([section, fields]) => {
          const pendingCount = fields.filter(f => f.pending !== null || f.pending_from_files).length;
          const editedCount = fields.filter(f => pathKey(f.path) in edits).length;
          return (
            <details
              key={section}
              data-testid={`settings-section-${section}`}
              className={`rounded-lg border ${dark ? 'border-gray-800 bg-gray-900' : 'border-gray-200 bg-white'}`}
              open={
                query.trim() !== '' ||
                editedCount > 0 ||
                sectionOpen(opened, section, pendingCount > 0)
              }
            >
              <summary
                onClick={e => {
                  e.preventDefault();
                  const isOpen = query.trim() !== '' || editedCount > 0 || sectionOpen(opened, section, pendingCount > 0);
                  remember({ ...opened, [section]: !isOpen });
                }}
                className="cursor-pointer select-none px-3 py-2 text-xs font-semibold uppercase tracking-wider flex items-center gap-2">
                <span>{section}</span>
                <span className={`normal-case font-normal ${muted}`}>{fields.length}</span>
                {pendingCount > 0 && <span className="normal-case font-normal text-amber-500">{pendingCount} pending</span>}
                {editedCount > 0 && <span className="normal-case font-normal text-orange-500">{editedCount} edited</span>}
              </summary>
              <div className="px-3 pb-2 overflow-x-auto">
                <table className="w-full table-fixed">
                  <colgroup>
                    <col className="w-[38%]" />
                    <col className="w-[22%]" />
                    <col className="w-[16%]" />
                    <col className="w-[24%]" />
                  </colgroup>
                  <thead>
                    <tr className={`text-[11px] uppercase tracking-wider ${muted}`}>
                      <th className="text-left font-normal py-1 pr-4">Setting</th>
                      <th className="text-right font-normal py-1 pr-4">Running</th>
                      <th className="text-right font-normal py-1 pr-4">Pending</th>
                      <th className="text-left font-normal py-1">{state.editable ? 'New value' : ''}</th>
                    </tr>
                  </thead>
                  <tbody>{fields.map(fieldRow)}</tbody>
                </table>
              </div>
            </details>
          );
        })}
      </div>

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

      <button
        type="button"
        data-testid="settings-history-toggle"
        aria-expanded={opened.__history === true}
        className={`text-xs font-semibold uppercase tracking-wider mt-6 mb-2 hover:underline ${muted}`}
        onClick={() => remember({ ...opened, __history: !(opened.__history === true) })}
      >
        {opened.__history === true ? '▾' : '▸'} History ({state.history.length})
      </button>
      {opened.__history === true && state.history.length === 0 && (
        <p className={`text-sm ${muted}`}>No desk settings saved yet: the config files apply.</p>
      )}
      {opened.__history === true && <ul className="space-y-2">
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
            <details className="mt-1">
              <summary className={`text-xs cursor-pointer ${muted}`}>Changes</summary>
              <pre className={`text-xs mt-1 overflow-x-auto ${muted}`}>{JSON.stringify(v.overrides, null, 2)}</pre>
            </details>
          </li>
        ))}
        {state.editable && state.running && state.active && (
          <li>
            <button type="button" className="text-xs flex items-center gap-1 hover:underline" onClick={() => setRevertTo(0)}>
              <RotateCcw className="w-3 h-3" /> Restore the config files (no desk settings)
            </button>
          </li>
        )}
      </ul>}

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

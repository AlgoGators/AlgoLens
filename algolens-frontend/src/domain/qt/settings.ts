/**
 * The desk settings editor (A7), ported from the closed config dashboard
 * (#33/#34) onto the settings lane of rulings 2/3/26:
 *
 *   running  what the last live run traded on (live_run_metadata.settings_used)
 *   pending  an active strategy_config version newer than the running one,
 *            merged over the config files at the next live run
 *
 * Every field shows both, unmistakably. Only keys the run reported can be
 * edited; the database, email and qt blocks and backtest keys are never shown. An admin's locked
 * settings are shown greyed out (D-14), one-value settings read-only with the reason (D-16).
 */

export type SettingType = 'number' | 'boolean' | 'string' | 'array' | 'null' | 'object';

export interface SettingField {
  path: string[];
  value: unknown;
  type: SettingType;
  overridden: boolean;
  /** The value the next run will use, when it differs from the running one. */
  pending: unknown;
  /** The active version stops overriding this key: it goes back to the file value. */
  pending_from_files: boolean;
  /** D-16: the config files' explanation of the setting. */
  help?: string | null;
  /** D-14: an admin locked it (the lock pattern that covers it); shown greyed out. */
  locked?: boolean;
  lockPattern?: string[] | null;
  /** D-16: why it cannot be changed (one legal value, or it mirrors another setting). */
  readOnly?: string | null;
  /** D-15: the engine's bounds on a risk gate limit. */
  bounds?: SettingBounds | null;
}

export interface SettingBounds {
  min: number | null;
  max: number | null;
  minExclusive: boolean;
  integer: boolean;
}

export interface SettingsVersion {
  version: number;
  overrides: Record<string, unknown>;
  reason: string;
  created_by: string;
  created_at: string;
  is_active: boolean;
}

export interface SettingsState {
  portfolioId: string;
  editable: boolean;
  running: { date: string; version: number | null } | null;
  active: SettingsVersion | null;
  pending: boolean;
  fields: SettingField[];
  history: SettingsVersion[];
}

export interface SettingChange {
  path: string[];
  value: unknown;
}

export const pathKey = (path: string[]) => path.join('\u0000');
export const pathLabel = (path: string[]) => path.join('.');

/** Whether a field can be edited in the form: a typed value that is neither locked by an admin
 * (D-14) nor read-only (D-16); null leaves are read-only. */
export function isEditable(field: SettingField): boolean {
  if (field.locked || field.readOnly) return false;
  return field.type === 'number' || field.type === 'boolean' || field.type === 'string' || field.type === 'array';
}

/** Why a field cannot be changed, for the greyed-out row; null when it can. */
export function lockedReason(field: SettingField): string | null {
  if (field.readOnly) return field.readOnly;
  if (field.locked) {
    const pattern = field.lockPattern?.join('.');
    const by = pattern && pattern !== field.path.join('.') ? ` (${pattern})` : '';
    return `Locked by an admin${by}`;
  }
  return null;
}

/** D-15: the bounds as a hint ("above 0 and at most 10, a whole number"), or null. */
export function boundsHint(bounds: SettingBounds | null | undefined): string | null {
  if (!bounds) return null;
  const parts: string[] = [];
  if (bounds.min !== null) parts.push(`${bounds.minExclusive ? 'above' : 'at least'} ${bounds.min}`);
  if (bounds.max !== null) parts.push(`at most ${bounds.max}`);
  const range = parts.join(' and ');
  return bounds.integer ? `${range ? `${range}, ` : ''}a whole number` : range || null;
}

/** Whether a number breaks a field's bounds (the engine refuses it, D-78). */
export function outOfBounds(value: unknown, bounds: SettingBounds | null | undefined): boolean {
  if (!bounds || typeof value !== 'number') return false;
  if (bounds.integer && !Number.isInteger(value)) return true;
  if (bounds.min !== null && (bounds.minExclusive ? value <= bounds.min : value < bounds.min)) return true;
  return bounds.max !== null && value > bounds.max;
}

/** Parse a typed value to the field's type; undefined = invalid. */
export function coerceSetting(raw: string, type: SettingType): unknown {
  const text = raw.trim();
  switch (type) {
    case 'number': {
      if (text === '' || !/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(text)) return undefined;
      const n = Number(text);
      return Number.isFinite(n) ? n : undefined;
    }
    case 'boolean':
      return text === 'true' ? true : text === 'false' ? false : undefined;
    case 'string':
      return raw;
    case 'array': {
      try {
        const parsed = JSON.parse(text);
        return Array.isArray(parsed) ? parsed : undefined;
      } catch {
        return undefined;
      }
    }
    default:
      return undefined;
  }
}

/** The text shown in an input for a value. */
export function displaySetting(value: unknown): string {
  if (Array.isArray(value)) return JSON.stringify(value);
  if (value === null || value === undefined) return '';
  return String(value);
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/**
 * The form's edits (raw text per field) as changes against what the next run
 * would use: unchanged values are dropped so they do not make empty versions.
 */
export function buildSettingChanges(
  fields: SettingField[],
  edits: Record<string, string>,
): { changes: SettingChange[]; invalid: string[] } {
  const changes: SettingChange[] = [];
  const invalid: string[] = [];
  for (const field of fields) {
    const key = pathKey(field.path);
    if (!(key in edits) || !isEditable(field)) continue;
    const value = coerceSetting(edits[key], field.type);
    if (value === undefined || outOfBounds(value, field.bounds)) {
      invalid.push(pathLabel(field.path));
      continue;
    }
    const baseline = field.pending !== null && field.pending !== undefined ? field.pending : field.value;
    if (same(value, baseline)) continue;
    changes.push({ path: field.path, value });
  }
  return { changes, invalid };
}

export function canSubmitSettings(changes: SettingChange[], invalid: string[], reason: string): boolean {
  return changes.length > 0 && invalid.length === 0 && reason.trim().length > 0;
}

/** Group fields by their top-level section for display. */
export function groupBySection(fields: SettingField[]): [string, SettingField[]][] {
  const groups = new Map<string, SettingField[]>();
  for (const field of fields) {
    const section = field.path.length > 1 ? field.path[0] : 'general';
    if (!groups.has(section)) groups.set(section, []);
    groups.get(section)!.push(field);
  }
  return Array.from(groups.entries());
}

/** "Running v3 / Pending v4" style status. */
export function versionStatus(state: SettingsState): { running: string; pending: string | null } {
  const running = state.running
    ? state.running.version === null
      ? `config files only (run of ${state.running.date})`
      : `version ${state.running.version} (run of ${state.running.date})`
    : 'no live run has reported its settings yet';
  const pending = state.pending && state.active ? `version ${state.active.version}, from the next live run` : null;
  return { running, pending };
}

/** A field's name inside its section (the section is the first path segment). */
export function labelInSection(field: SettingField): string {
  return field.path.length > 1 ? field.path.slice(1).join('.') : field.path[0];
}

/** The fields whose dotted path contains every word of `query` (case-insensitive). */
export function filterFields(fields: SettingField[], query: string): SettingField[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return fields;
  return fields.filter(field => {
    const label = pathLabel(field.path).toLowerCase();
    return words.every(word => label.includes(word));
  });
}

/**
 * Which settings sections a viewer opened or closed, remembered in this
 * browser only (a convenience: storage can be missing or refuse, and then
 * nothing is remembered).
 */
export function readOpenState(key: string): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(key);
    const parsed = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(([, v]) => typeof v === 'boolean'),
    ) as Record<string, boolean>;
  } catch {
    return {};
  }
}

export function writeOpenState(key: string, value: Record<string, boolean>): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage unavailable: the state is simply not remembered
  }
}

/** A section is open when the viewer said so; otherwise when it needs attention. */
export function sectionOpen(remembered: Record<string, boolean>, section: string, needsAttention: boolean): boolean {
  return remembered[section] ?? needsAttention;
}

/** A config comment (`_note`, `_description`, `_idm_rationale`, ...): documentation, not a setting. */
export function isConfigNote(field: SettingField): boolean {
  return field.path.some(segment => segment.startsWith('_'));
}


/**
 * D-14: a lock path as an admin types it ("strategies.*.type") into its keys; null when it is
 * empty or has an empty key.
 */
export function parseLockPath(text: string): string[] | null {
  const keys = text.trim().split('.').map(k => k.trim());
  return keys.length > 0 && keys.every(k => k.length > 0) ? keys : null;
}

/**
 * The desk settings editor (A7), ported from the closed config dashboard
 * (#33/#34) onto the settings lane of rulings 2/3/26:
 *
 *   running  what the last live run traded on (live_run_metadata.settings_used)
 *   pending  an active strategy_config version newer than the running one,
 *            merged over the config files at the next live run
 *
 * Every field shows both, unmistakably. Only keys the run reported can be
 * edited; the database and email sections are never shown.
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

/** Whether a field can be edited in the form (null leaves are read-only). */
export function isEditable(field: SettingField): boolean {
  return field.type === 'number' || field.type === 'boolean' || field.type === 'string' || field.type === 'array';
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
    if (value === undefined) {
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

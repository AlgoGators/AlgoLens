/**
 * Pure logic for config form editing—no React, no async.
 *
 * Key insight: the engine reloads config once per session, at start.
 * So two different values exist: what's running (effective), and what's
 * staged for the next session (active_overrides.overrides).
 * The form must show both, unmistakably.
 */

export interface FlatConfigField {
  section: string;
  key: string;
  path: string; // dotted: execution.slippage_bps
  value: any;
  type: 'number' | 'boolean' | 'string' | 'unsupported';
}

export interface MergedField {
  running: any;
  pending: any;
  isOverridden: boolean;
}

/**
 * Flatten nested config object into a list of editable fields.
 * Each leaf becomes a {section, key, path, value, type}.
 * Arrays and nested objects are marked unsupported (render read-only).
 */
export function flattenConfig(
  effective: Record<string, Record<string, any>>,
): FlatConfigField[] {
  const fields: FlatConfigField[] = [];

  for (const [section, sectionValue] of Object.entries(effective)) {
    if (typeof sectionValue !== 'object' || sectionValue === null) continue;

    for (const [key, value] of Object.entries(sectionValue)) {
      const type = inferType(value);
      const path = `${section}.${key}`;

      fields.push({
        section,
        key,
        path,
        value,
        type,
      });
    }
  }

  return fields;
}

/**
 * Infer the type of a value. Returns 'unsupported' for arrays/nested objects.
 */
function inferType(value: any): 'number' | 'boolean' | 'string' | 'unsupported' {
  if (typeof value === 'number') return 'number';
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'string') return 'string';
  if (Array.isArray(value)) return 'unsupported';
  if (typeof value === 'object' && value !== null) return 'unsupported';
  return 'unsupported';
}

/**
 * Merge effective config with pending overrides.
 * Return a map of path -> {running, pending, isOverridden}.
 * This lets the UI show both values without recomputing.
 */
export function mergeOverrides(
  effective: Record<string, Record<string, any>>,
  overrides: Record<string, any> | null,
): Record<string, MergedField> {
  const result: Record<string, MergedField> = {};
  const overridesMap = overrides || {};

  for (const [section, sectionValue] of Object.entries(effective)) {
    if (typeof sectionValue !== 'object' || sectionValue === null) continue;

    for (const [key, runningValue] of Object.entries(sectionValue)) {
      const path = `${section}.${key}`;
      const pendingValue = overridesMap[path] !== undefined ? overridesMap[path] : runningValue;

      result[path] = {
        running: runningValue,
        pending: pendingValue,
        isOverridden: overridesMap[path] !== undefined,
      };
    }
  }

  return result;
}

/**
 * Build nested override payload from edits.
 * Only include paths whose value actually changed from effective.
 * Sending unchanged values back would create meaningless audit entries.
 */
export function buildOverridePayload(
  edits: Record<string, any>,
  effective: Record<string, Record<string, any>>,
): Record<string, Record<string, any>> {
  const payload: Record<string, Record<string, any>> = {};

  for (const [path, newValue] of Object.entries(edits)) {
    if (newValue === undefined) continue; // Skip coerce failures

    const [section, key] = path.split('.');
    const oldValue = effective[section]?.[key];

    // Only include if actually changed
    if (newValue !== oldValue) {
      if (!payload[section]) {
        payload[section] = {};
      }
      payload[section][key] = newValue;
    }
  }

  return payload;
}

/**
 * Coerce an input string to the declared type.
 * Return undefined for invalid input so the caller can block submit.
 */
export function coerceValue(raw: string, type: 'number' | 'boolean' | 'string' | 'unsupported'): any {
  if (type === 'number') {
    const n = parseFloat(raw);
    return isNaN(n) ? undefined : n;
  }

  if (type === 'boolean') {
    if (raw === 'true') return true;
    if (raw === 'false') return false;
    return undefined;
  }

  if (type === 'string') {
    return raw;
  }

  // unsupported
  return undefined;
}

/**
 * Guard submit based on form state.
 * Returns false if reason is empty/whitespace, no changes, or any coerce failed.
 */
export function canSubmitConfig(
  edits: Record<string, any>,
  reason: string,
): boolean {
  // Reason must be non-empty and non-whitespace
  if (!reason || !reason.trim()) {
    return false;
  }

  // Must have at least one change
  const changes = Object.values(edits).filter(v => v !== undefined);
  if (changes.length === 0) {
    return false;
  }

  // No coerce failures (values must not be undefined)
  if (Object.values(edits).includes(undefined)) {
    return false;
  }

  return true;
}

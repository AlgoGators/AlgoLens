import { describe, expect, it } from 'vitest';
import {
  buildSettingChanges,
  canSubmitSettings,
  coerceSetting,
  filterFields,
  groupBySection,
  labelInSection,
  pathKey,
  versionStatus,
  type SettingField,
  type SettingsState,
  isConfigNote,
  readOpenState,
  sectionOpen,
  writeOpenState,
} from './settings';
import { boundsHint, isEditable, lockedReason, outOfBounds, parseLockPath } from './settings';

const field = (path: string[], value: unknown, type: SettingField['type'], pending: unknown = null): SettingField => ({
  path,
  value,
  type,
  overridden: false,
  pending,
  pending_from_files: false,
});

const fields = [
  field(['risk', 'max_leverage'], 2, 'number'),
  field(['risk', 'use_overlay'], true, 'boolean'),
  field(['strategies', 'tf', 'lookbacks'], [16, 32], 'array'),
  field(['capital'], 500000, 'number', 400000),
  field(['note'], null, 'null'),
];

describe('coerceSetting', () => {
  it('parses each type or refuses', () => {
    expect(coerceSetting('1.5', 'number')).toBe(1.5);
    expect(coerceSetting('-2e3', 'number')).toBe(-2000);
    expect(coerceSetting('abc', 'number')).toBeUndefined();
    expect(coerceSetting('', 'number')).toBeUndefined();
    expect(coerceSetting('true', 'boolean')).toBe(true);
    expect(coerceSetting('yes', 'boolean')).toBeUndefined();
    expect(coerceSetting('[8, 16]', 'array')).toEqual([8, 16]);
    expect(coerceSetting('{"a":1}', 'array')).toBeUndefined();
    expect(coerceSetting('x', 'null')).toBeUndefined();
  });
});

describe('buildSettingChanges', () => {
  it('sends only real changes, by path', () => {
    const { changes, invalid } = buildSettingChanges(fields, {
      [pathKey(['risk', 'max_leverage'])]: '1.5',
      [pathKey(['risk', 'use_overlay'])]: 'true', // unchanged
      [pathKey(['strategies', 'tf', 'lookbacks'])]: '[8,16]',
    });
    expect(invalid).toEqual([]);
    expect(changes).toEqual([
      { path: ['risk', 'max_leverage'], value: 1.5 },
      { path: ['strategies', 'tf', 'lookbacks'], value: [8, 16] },
    ]);
  });

  it('compares against the pending value when one exists', () => {
    expect(buildSettingChanges(fields, { [pathKey(['capital'])]: '400000' }).changes).toEqual([]);
    expect(buildSettingChanges(fields, { [pathKey(['capital'])]: '500000' }).changes).toEqual([
      { path: ['capital'], value: 500000 },
    ]);
  });

  it('reports invalid input and ignores read-only fields', () => {
    const { changes, invalid } = buildSettingChanges(fields, {
      [pathKey(['risk', 'max_leverage'])]: 'lots',
      [pathKey(['note'])]: 'x',
    });
    expect(changes).toEqual([]);
    expect(invalid).toEqual(['risk.max_leverage']);
  });
});

describe('canSubmitSettings', () => {
  const change = [{ path: ['capital'], value: 1 }];
  it('needs a change, no invalid input and a reason', () => {
    expect(canSubmitSettings(change, [], 'why')).toBe(true);
    expect(canSubmitSettings(change, [], '  ')).toBe(false);
    expect(canSubmitSettings([], [], 'why')).toBe(false);
    expect(canSubmitSettings(change, ['x'], 'why')).toBe(false);
  });
});

describe('display', () => {
  it('groups by top-level section', () => {
    expect(groupBySection(fields).map(([s, f]) => [s, f.length])).toEqual([
      ['risk', 2],
      ['strategies', 1],
      ['general', 2],
    ]);
  });

  it('says what is running and what is pending', () => {
    const state: SettingsState = {
      portfolioId: 'QT',
      editable: true,
      running: { date: '2026-10-08', version: 3 },
      active: { version: 4, overrides: {}, reason: 'r', created_by: 'd', created_at: '', is_active: true },
      pending: true,
      fields: [],
      history: [],
    };
    expect(versionStatus(state)).toEqual({
      running: 'version 3 (run of 2026-10-08)',
      pending: 'version 4, from the next live run',
    });
    expect(versionStatus({ ...state, pending: false }).pending).toBeNull();
    expect(versionStatus({ ...state, running: null }).running).toMatch(/no live run/);
  });
});

describe('compact settings view', () => {
  const field = (path: string[]): SettingField => ({ path, type: 'number', value: 1, overridden: false, pending: null, pending_from_files: false });

  it('names a field inside its section', () => {
    expect(labelInSection(field(['risk', 'max_gross_leverage']))).toBe('max_gross_leverage');
    expect(labelInSection(field(['strategies', 'TREND', 'weight']))).toBe('TREND.weight');
    expect(labelInSection(field(['capital']))).toBe('capital');
  });

  it('filters on every word of the query, any case', () => {
    const fields = [field(['risk', 'max_gross_leverage']), field(['risk', 'per_name_cap']), field(['opt', 'buffer'])];
    expect(filterFields(fields, '').length).toBe(3);
    expect(filterFields(fields, 'RISK leverage').map(f => f.path.join('.'))).toEqual(['risk.max_gross_leverage']);
    expect(filterFields(fields, 'nothing')).toEqual([]);
  });
});

describe('remembered open sections', () => {
  it('opens a section the viewer opened, else one that needs attention', () => {
    expect(sectionOpen({ risk: true }, 'risk', false)).toBe(true);
    expect(sectionOpen({ risk: false }, 'risk', true)).toBe(false);
    expect(sectionOpen({}, 'risk', true)).toBe(true);
    expect(sectionOpen({}, 'risk', false)).toBe(false);
  });

  it('round-trips through storage and ignores junk', () => {
    // The tests run in node: give them a window with an in-memory storage.
    const store = new Map<string, string>();
    (globalThis as unknown as { window: unknown }).window = {
      localStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
      },
    };
    writeOpenState('t.open', { risk: true, opt: false });
    expect(readOpenState('t.open')).toEqual({ risk: true, opt: false });
    window.localStorage.setItem('t.junk', '{"a": 1, "b": true}');
    expect(readOpenState('t.junk')).toEqual({ b: true });
    window.localStorage.setItem('t.bad', 'not json');
    expect(readOpenState('t.bad')).toEqual({});
    expect(readOpenState('t.missing')).toEqual({});
  });
});

describe('remembered open sections without storage', () => {
  it('remembers nothing and never throws', () => {
    (globalThis as unknown as { window: unknown }).window = {
      localStorage: {
        getItem: () => {
          throw new Error('denied');
        },
        setItem: () => {
          throw new Error('denied');
        },
      },
    };
    expect(readOpenState('x')).toEqual({});
    expect(() => writeOpenState('x', { a: true })).not.toThrow();
  });
});

describe('config comments', () => {
  const f = (path: string[]): SettingField =>
    ({ path, type: 'string', value: 'x', overridden: false, pending: null, pending_from_files: false });
  it('are the keys starting with an underscore, at any depth', () => {
    expect(isConfigNote(f(['live', '_note']))).toBe(true);
    expect(isConfigNote(f(['strategies', 'TREND', 'config', '_idm_rationale']))).toBe(true);
    expect(isConfigNote(f(['risk', 'max_gross_leverage']))).toBe(false);
  });
});


describe('locks, read-only settings and bounds (D-14, D-15, D-16)', () => {
  const base = {
    path: ['risk', 'modules', 'carver', 'R_max'],
    value: 2.25,
    type: 'number' as const,
    overridden: false,
    pending: null,
    pending_from_files: false,
  };
  const bounds = { min: 0, max: 3, minExclusive: true, integer: false };

  it('greys out a locked or read-only setting, and says why', () => {
    expect(isEditable({ ...base, locked: true, lockPattern: ['risk'] })).toBe(false);
    expect(lockedReason({ ...base, locked: true, lockPattern: ['risk'] })).toBe('Locked by an admin (risk)');
    expect(lockedReason({ ...base, readOnly: 'One legal value.' })).toBe('One legal value.');
    expect(lockedReason(base)).toBeNull();
    expect(isEditable(base)).toBe(true);
  });

  it('refuses a value out of the engine bounds before it is sent', () => {
    const field = { ...base, bounds };
    expect(buildSettingChanges([field], { [pathKey(field.path)]: '1000' }).invalid).toEqual(['risk.modules.carver.R_max']);
    expect(buildSettingChanges([field], { [pathKey(field.path)]: '0' }).invalid).toHaveLength(1);
    expect(buildSettingChanges([field], { [pathKey(field.path)]: '3' }).changes).toHaveLength(1);
    expect(buildSettingChanges([field], { [pathKey(field.path)]: '3.5' }).invalid).toHaveLength(1);
    expect(outOfBounds(2.5, { min: 0, max: 100, minExclusive: false, integer: true })).toBe(true);
    expect(boundsHint(bounds)).toBe('above 0 and at most 3');
    expect(boundsHint({ min: 0, max: 100, minExclusive: false, integer: true })).toBe('at least 0 and at most 100, a whole number');
  });
});

describe('parseLockPath (D-14)', () => {
  it('splits a typed path into keys and refuses an empty key', () => {
    expect(parseLockPath('strategies.*.type')).toEqual(['strategies', '*', 'type']);
    expect(parseLockPath(' covariance_* ')).toEqual(['covariance_*']);
    expect(parseLockPath('risk..x')).toBeNull();
    expect(parseLockPath('')).toBeNull();
  });
});

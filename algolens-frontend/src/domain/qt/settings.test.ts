import { describe, expect, it } from 'vitest';
import {
  buildSettingChanges,
  canSubmitSettings,
  coerceSetting,
  groupBySection,
  pathKey,
  versionStatus,
  type SettingField,
  type SettingsState,
} from './settings';

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

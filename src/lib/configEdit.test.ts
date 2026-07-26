/**
 * Pure logic for config form editing—no React, no async.
 * Tests run before implementation to catch design issues.
 */
import { describe, it, expect } from 'vitest';
import {
  flattenConfig,
  mergeOverrides,
  buildOverridePayload,
  coerceValue,
  canSubmitConfig,
  type FlatConfigField,
} from './configEdit';

// Real effective config from the spec
const EXAMPLE_EFFECTIVE = {
  execution: { commission_rate: 0.0005, position_limit_live: 500, slippage_bps: 1 },
  optimization: { buffer_size_factor: 0.01, cost_penalty_scalar: 50, tau: 1, use_buffering: true },
  risk: { confidence_level: 0.99, lookback_period: 252, max_correlation: 0.85 },
  strategy_defaults: { carver_buffer_floor: 0.5, max_strategy_allocation: 1, min_strategy_allocation: 0.1 },
};

describe('flattenConfig', () => {
  it('flattens a nested config object into a list of fields with types', () => {
    const fields = flattenConfig(EXAMPLE_EFFECTIVE);

    expect(fields).toHaveLength(13); // Count all leaf fields

    // Each field must have section, key, path, value, type
    fields.forEach(field => {
      expect(field).toHaveProperty('section');
      expect(field).toHaveProperty('key');
      expect(field).toHaveProperty('path');
      expect(field).toHaveProperty('value');
      expect(field).toHaveProperty('type');
    });
  });

  it('correctly infers type as "number" for numeric values', () => {
    const fields = flattenConfig(EXAMPLE_EFFECTIVE);
    const slippageBpsField = fields.find(f => f.key === 'slippage_bps');

    expect(slippageBpsField).toBeDefined();
    expect(slippageBpsField?.type).toBe('number');
    expect(slippageBpsField?.value).toBe(1);
  });

  it('correctly infers type as "boolean" for boolean values', () => {
    const fields = flattenConfig(EXAMPLE_EFFECTIVE);
    const useBufferingField = fields.find(f => f.key === 'use_buffering');

    expect(useBufferingField).toBeDefined();
    expect(useBufferingField?.type).toBe('boolean');
    expect(useBufferingField?.value).toBe(true);
  });

  it('correctly infers type as "string" for string values', () => {
    const testConfig = {
      section: { name: 'test', value: 123 },
    };
    const fields = flattenConfig(testConfig);
    const nameField = fields.find(f => f.key === 'name');

    expect(nameField?.type).toBe('string');
  });

  it('marks nested objects/arrays as unsupported', () => {
    const testConfig = {
      good: { value: 1 },
      bad: { nested: { deep: true } },
    };
    const fields = flattenConfig(testConfig);
    const badField = fields.find(f => f.key === 'nested');

    expect(badField?.type).toBe('unsupported');
  });

  it('marks arrays as unsupported', () => {
    const testConfig = {
      section: { items: [1, 2, 3] },
    };
    const fields = flattenConfig(testConfig);
    const itemsField = fields.find(f => f.key === 'items');

    expect(itemsField?.type).toBe('unsupported');
  });

  it('constructs correct dotted paths for nested keys', () => {
    const fields = flattenConfig(EXAMPLE_EFFECTIVE);
    const slippageField = fields.find(f => f.key === 'slippage_bps');

    expect(slippageField?.path).toBe('execution.slippage_bps');
  });

  it('preserves section names for easy grouping', () => {
    const fields = flattenConfig(EXAMPLE_EFFECTIVE);
    const executionFields = fields.filter(f => f.section === 'execution');

    expect(executionFields).toHaveLength(3);
  });
});

describe('mergeOverrides', () => {
  it('returns running=pending when no override exists', () => {
    const result = mergeOverrides(EXAMPLE_EFFECTIVE, null);
    const slippage = result['execution.slippage_bps'];

    expect(slippage.running).toBe(1);
    expect(slippage.pending).toBe(1);
    expect(slippage.isOverridden).toBe(false);
  });

  it('shows different running vs pending when override exists', () => {
    const overrides = { 'execution.slippage_bps': 3 };
    const result = mergeOverrides(EXAMPLE_EFFECTIVE, overrides);
    const slippage = result['execution.slippage_bps'];

    expect(slippage.running).toBe(1);
    expect(slippage.pending).toBe(3);
    expect(slippage.isOverridden).toBe(true);
  });

  it('includes all effective fields even if not overridden', () => {
    const result = mergeOverrides(EXAMPLE_EFFECTIVE, { 'execution.slippage_bps': 3 });

    expect(result['execution.commission_rate']).toBeDefined();
    expect(result['risk.confidence_level']).toBeDefined();
  });

  it('ignores overrides for paths not in effective', () => {
    const overrides = { 'nonexistent.field': 99 };
    const result = mergeOverrides(EXAMPLE_EFFECTIVE, overrides);

    expect(result['nonexistent.field']).toBeUndefined();
  });
});

describe('buildOverridePayload', () => {
  it('excludes unchanged fields from the payload', () => {
    const edits = { 'execution.commission_rate': 0.0005 }; // unchanged
    const payload = buildOverridePayload(edits, EXAMPLE_EFFECTIVE);

    expect(payload.execution).toBeUndefined();
  });

  it('includes only changed fields in the payload', () => {
    const edits = {
      'execution.slippage_bps': 3, // changed from 1
      'execution.commission_rate': 0.0005, // unchanged
    };
    const payload = buildOverridePayload(edits, EXAMPLE_EFFECTIVE);

    expect(payload.execution.slippage_bps).toBe(3);
    expect(payload.execution.commission_rate).toBeUndefined();
  });

  it('nests changes by section', () => {
    const edits = {
      'execution.slippage_bps': 3,
      'risk.confidence_level': 0.95,
    };
    const payload = buildOverridePayload(edits, EXAMPLE_EFFECTIVE);

    expect(payload.execution).toBeDefined();
    expect(payload.risk).toBeDefined();
    expect(Object.keys(payload).length).toBe(2); // Only two sections changed
  });

  it('returns an empty object if no fields changed', () => {
    const edits = {
      'execution.commission_rate': 0.0005,
      'execution.position_limit_live': 500,
    };
    const payload = buildOverridePayload(edits, EXAMPLE_EFFECTIVE);

    expect(Object.keys(payload).length).toBe(0);
  });

  it('correctly nests multiple changes within a section', () => {
    const edits = {
      'execution.slippage_bps': 5,
      'execution.position_limit_live': 1000,
    };
    const payload = buildOverridePayload(edits, EXAMPLE_EFFECTIVE);

    expect(payload.execution.slippage_bps).toBe(5);
    expect(payload.execution.position_limit_live).toBe(1000);
  });
});

describe('coerceValue', () => {
  it('parses a numeric string into a number when type is "number"', () => {
    const result = coerceValue('42', 'number');
    expect(result).toBe(42);
  });

  it('parses a decimal string into a number', () => {
    const result = coerceValue('1.5', 'number');
    expect(result).toBe(1.5);
  });

  it('returns undefined when a non-numeric string is parsed as number', () => {
    const result = coerceValue('not a number', 'number');
    expect(result).toBeUndefined();
  });

  it('parses "true" and "false" strings as booleans', () => {
    expect(coerceValue('true', 'boolean')).toBe(true);
    expect(coerceValue('false', 'boolean')).toBe(false);
  });

  it('returns undefined for invalid boolean strings', () => {
    const result = coerceValue('yes', 'boolean');
    expect(result).toBeUndefined();
  });

  it('returns the string as-is when type is "string"', () => {
    const result = coerceValue('hello world', 'string');
    expect(result).toBe('hello world');
  });

  it('returns undefined for unsupported types', () => {
    const result = coerceValue('anything', 'unsupported');
    expect(result).toBeUndefined();
  });

  it('handles negative numbers correctly', () => {
    expect(coerceValue('-5', 'number')).toBe(-5);
    expect(coerceValue('-1.5', 'number')).toBe(-1.5);
  });

  it('handles zero correctly', () => {
    expect(coerceValue('0', 'number')).toBe(0);
  });

  it('handles empty string for numbers as invalid', () => {
    expect(coerceValue('', 'number')).toBeUndefined();
  });
});

describe('canSubmitConfig', () => {
  it('returns false when reason is empty', () => {
    const edits = { 'execution.slippage_bps': 3 };
    expect(canSubmitConfig(edits, '')).toBe(false);
  });

  it('returns false when reason is only whitespace', () => {
    const edits = { 'execution.slippage_bps': 3 };
    expect(canSubmitConfig(edits, '   ')).toBe(false);
  });

  it('returns false when there are no changes', () => {
    const edits = {};
    expect(canSubmitConfig(edits, 'Testing config')).toBe(false);
  });

  it('returns false when any edit failed to coerce (has undefined value)', () => {
    // Simulate a failed coerce: the edit map has been built with invalid values
    // The actual validation would catch this, but here we check that edits with
    // undefined are rejected
    const edits = {
      'execution.slippage_bps': 3,
      'risk.confidence_level': undefined, // Failed coerce
    };
    expect(canSubmitConfig(edits as any, 'Testing config')).toBe(false);
  });

  it('returns true when reason is valid and edits exist', () => {
    const edits = { 'execution.slippage_bps': 3 };
    expect(canSubmitConfig(edits, 'Adjusting slippage for market conditions')).toBe(true);
  });

  it('returns true with minimal reason text', () => {
    const edits = { 'execution.slippage_bps': 3 };
    expect(canSubmitConfig(edits, 'test')).toBe(true);
  });

  it('returns true when multiple edits exist and reason is valid', () => {
    const edits = {
      'execution.slippage_bps': 3,
      'risk.confidence_level': 0.95,
    };
    expect(canSubmitConfig(edits, 'Risk reduction pass')).toBe(true);
  });
});

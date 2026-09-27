import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parseFixedDecimal8 } from './fixedDecimal8';

type ValidVector = { text: string; scaled: string };
type InvalidVector = { label: string; value: unknown };
const vectors = JSON.parse(readFileSync(new URL('../../../../contracts/fixed-decimal8-vectors.json', import.meta.url), 'utf8')) as {
  valid: ValidVector[];
  invalid: InvalidVector[];
};

describe('canonical signed Decimal8', () => {
  for (const { text } of vectors.valid) {
    it(`returns ${text} verbatim`, () => {
      expect(parseFixedDecimal8(text)).toBe(text);
    });
  }

  for (const { text, scaled } of vectors.valid) {
    it(`fixture scaled integer independently matches ${text}`, () => {
      const value = BigInt(scaled);
      const magnitude = value < 0n ? -value : value;
      const whole = (magnitude / 100000000n).toString();
      const fractional = (magnitude % 100000000n).toString().padStart(8, '0').replace(/0+$/, '');
      const expected = `${value < 0n ? '-' : ''}${whole}${fractional ? `.${fractional}` : ''}`;
      expect(expected).toBe(text);
    });
  }

  it('keeps adjacent scaled units distinct beyond Number precision', () => {
    const left = vectors.valid.find(({ scaled }) => scaled === '9223372036854775806');
    const right = vectors.valid.find(({ scaled }) => scaled === '9223372036854775807');
    expect(left).toBeDefined();
    expect(right).toBeDefined();
    expect(parseFixedDecimal8(left!.text)).not.toBe(parseFixedDecimal8(right!.text));
  });

  for (const { label, value } of vectors.invalid) {
    it(`rejects ${label} with the fixed error`, () => {
      expect(() => parseFixedDecimal8(value)).toThrowError(/^invalid_fixed_decimal8$/);
    });
  }

  it('rejects boxed strings, numeric wrappers, and hostile objects without coercion', () => {
    expect(() => parseFixedDecimal8(new String('1'))).toThrowError(/^invalid_fixed_decimal8$/);
    expect(() => parseFixedDecimal8(new Number(1))).toThrowError(/^invalid_fixed_decimal8$/);
    expect(() => parseFixedDecimal8(Object.assign(Object.create(null), { toString: () => { throw new Error('coerced'); } })))
      .toThrowError(/^invalid_fixed_decimal8$/);
  });

  it('rejects non-JSON primitive types without coercion', () => {
    for (const value of [undefined, 1n, Symbol('one')]) {
      expect(() => parseFixedDecimal8(value)).toThrowError(/^invalid_fixed_decimal8$/);
    }
  });

  it('rejects a long string without echoing it', () => {
    expect(() => parseFixedDecimal8('9'.repeat(10000))).toThrowError(/^invalid_fixed_decimal8$/);
  });

  it('does not leak state between calls', () => {
    expect(parseFixedDecimal8('0.00000001')).toBe('0.00000001');
    expect(() => parseFixedDecimal8('92233720368.54775808')).toThrowError(/^invalid_fixed_decimal8$/);
    expect(parseFixedDecimal8('-0.00000001')).toBe('-0.00000001');
    expect(parseFixedDecimal8('0.00000001')).toBe('0.00000001');
  });
});

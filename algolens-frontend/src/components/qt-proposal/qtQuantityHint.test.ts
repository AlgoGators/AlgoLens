//
// The sentence above the quantity boxes, built from the asset types present.
// Written to be safe for a type nobody has given words to yet: it says what it
// knows, joins the phrases it has, and always ends in exactly one full stop.

import { describe, expect, it } from 'vitest';
import { QUANTITY_PHRASES, quantityHint } from './qtQuantityHint';

const three = { FUTURE: 'whole contracts for futures', EQUITY: 'fractions allowed for equities', BOND: 'face value in hundreds for bonds' };

describe('quantityHint', () => {
  it('says nothing for no types, and nothing for types it has no words for', () => {
    expect(quantityHint([])).toBeNull();
    expect(quantityHint(['OPTION'])).toBeNull();
  });
  it('one type: capitalised, one full stop', () => {
    expect(quantityHint(['EQUITY'])).toBe('Fractions allowed for equities.');
    expect(quantityHint(['FUTURE'])).toBe('Whole contracts for futures.');
  });
  it('two types: joined with a semicolon, in the fixed order, however they arrive', () => {
    const expected = 'Whole contracts for futures; fractions allowed for equities.';
    expect(quantityHint(['FUTURE', 'EQUITY'])).toBe(expected);
    expect(quantityHint(new Set(['EQUITY', 'FUTURE']))).toBe(expected);
  });
  it('ignores an unknown type beside known ones', () => {
    expect(quantityHint(['OPTION', 'EQUITY'])).toBe('Fractions allowed for equities.');
  });
  it('three types (hypothetical): every phrase present, no stray or doubled full stop', () => {
    expect(quantityHint(['BOND', 'EQUITY', 'FUTURE'], three))
      .toBe('Whole contracts for futures; fractions allowed for equities; face value in hundreds for bonds.');
    expect(quantityHint(['FUTURE', 'BOND'], three)).toBe('Whole contracts for futures; face value in hundreds for bonds.');
  });
  it('a phrase that already ends in a full stop does not get a second one', () => {
    expect(quantityHint(['FUTURE'], { FUTURE: 'whole contracts.' })).toBe('Whole contracts.');
  });
  it('uses the shipped wording for the two known types', () => {
    expect(Object.keys(QUANTITY_PHRASES)).toEqual(['FUTURE', 'EQUITY']);
  });
});

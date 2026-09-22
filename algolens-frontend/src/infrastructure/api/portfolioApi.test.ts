// @vitest-environment jsdom

import { describe, expect, it } from 'vitest';

import {
  aggregatePortfolioTotals,
  sanitizePositionStrategyNames,
} from './portfolioApi';

describe('strategy detail position identities', () => {
  it('deduplicates valid identities without changing their opaque text', () => {
    expect(sanitizePositionStrategyNames([
      ' Engine A ',
      ' Engine A ',
      'Engine A',
      'Engine B',
    ])).toEqual([' Engine A ', 'Engine A', 'Engine B']);
  });

  it('fails the whole field closed when any entry is invalid', () => {
    expect(sanitizePositionStrategyNames(['Engine A', null])).toEqual([]);
    expect(sanitizePositionStrategyNames(['Engine A', '   '])).toEqual([]);
    expect(sanitizePositionStrategyNames(['Engine A', 42])).toEqual([]);
  });

  it('fails closed when the response field is absent or not an array', () => {
    expect(sanitizePositionStrategyNames(undefined)).toEqual([]);
    expect(sanitizePositionStrategyNames('Engine A')).toEqual([]);
  });
});

describe('portfolio return aggregation', () => {
  it('withholds return figures when any included starting equity is unknown', () => {
    const totals = aggregatePortfolioTotals([
      { dataAvailable: true, invested: 100_000, currentValue: 110_000 },
      { dataAvailable: true, invested: null, currentValue: 100_000 },
    ]);

    expect(totals).toEqual({
      totalValue: 210_000,
      totalInvested: 100_000,
      totalReturn: null,
      totalReturnPercent: null,
    });
  });

  it('retains numeric return figures when every included basis is known', () => {
    const totals = aggregatePortfolioTotals([
      { dataAvailable: true, invested: 100_000, currentValue: 110_000 },
      { dataAvailable: true, invested: 50_000, currentValue: 55_000 },
      { dataAvailable: false, invested: null, currentValue: 0 },
    ]);

    expect(totals).toEqual({
      totalValue: 165_000,
      totalInvested: 150_000,
      totalReturn: 15_000,
      totalReturnPercent: 10,
    });
  });
});

import { describe, expect, it } from 'vitest';

import { counted, pluralize } from './pluralize';

describe('the noun for a count', () => {
  it('is singular for exactly one, plural otherwise', () => {
    expect(pluralize(1, 'position')).toBe('position');
    expect(pluralize(0, 'position')).toBe('positions');
    expect(pluralize(2, 'position')).toBe('positions');
  });

  it('takes an irregular plural when the default -s is wrong', () => {
    expect(pluralize(1, 'strategy', 'strategies')).toBe('strategy');
    expect(pluralize(3, 'strategy', 'strategies')).toBe('strategies');
  });

  it('counts a negative as plural, as English does', () => {
    expect(pluralize(-1, 'day')).toBe('days');
  });
});

describe('the count with its noun', () => {
  it('reads as a phrase', () => {
    expect(counted(1, 'Holding')).toBe('1 Holding');
    expect(counted(4, 'Holding')).toBe('4 Holdings');
    expect(counted(1, 'incubating strategy', 'incubating strategies')).toBe('1 incubating strategy');
    expect(counted(0, 'position')).toBe('0 positions');
  });
});

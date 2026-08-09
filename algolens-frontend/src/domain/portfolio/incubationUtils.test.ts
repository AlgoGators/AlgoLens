import { describe, it, expect } from 'vitest';
import {
  calculateDaysRemaining,
  calculateIncubationProgress,
  formatEquity,
  formatIncubationDate,
  formatMockCapital,
  INCUBATION_WINDOW_DAYS,
  isNearEndOfWindow,
  isWindowComplete,
  validateMockCapital,
  validateReason,
} from './incubationUtils';

describe('incubationUtils', () => {
  describe('calculateIncubationProgress', () => {
    it('returns 0 at day 0', () => {
      expect(calculateIncubationProgress(0)).toBe(0);
    });

    it('returns 50 at day 60', () => {
      expect(calculateIncubationProgress(60)).toBe(50);
    });

    it('returns 100 at day 120', () => {
      expect(calculateIncubationProgress(120)).toBe(100);
    });

    it('caps progress at 100 if past window', () => {
      expect(calculateIncubationProgress(150)).toBe(100);
    });

    it('clamps negative elapsed days at 0', () => {
      expect(calculateIncubationProgress(-1)).toBe(0);
    });

    it('handles zero window gracefully', () => {
      expect(calculateIncubationProgress(10, 0)).toBe(0);
    });
  });

  describe('calculateDaysRemaining', () => {
    it('uses the default incubation window', () => {
      expect(calculateDaysRemaining(20)).toBe(INCUBATION_WINDOW_DAYS - 20);
    });

    it('does not return negative days', () => {
      expect(calculateDaysRemaining(150)).toBe(0);
    });
  });

  describe('formatIncubationDate', () => {
    it('formats ISO date string', () => {
      expect(formatIncubationDate('2026-07-26T12:00:00Z')).toMatch(
        /Jul 26, 2026/
      );
    });

    it('returns N/A for null', () => {
      expect(formatIncubationDate(null)).toBe('N/A');
    });

    it('returns Invalid for malformed date', () => {
      expect(formatIncubationDate('not a date')).toBe('Invalid');
    });
  });

  describe('formatMockCapital', () => {
    it('formats whole-dollar mock capital', () => {
      expect(formatMockCapital(250000)).toBe('$250,000');
    });

    it('returns $0 for nullish input', () => {
      expect(formatMockCapital(null)).toBe('$0');
      expect(formatMockCapital(undefined)).toBe('$0');
    });
  });

  describe('validateMockCapital', () => {
    it('accepts valid numeric string', () => {
      expect(validateMockCapital('250000')).toEqual([true, '']);
    });

    it('rejects non-positive capital', () => {
      const [valid, message] = validateMockCapital(0);
      expect(valid).toBe(false);
      expect(message).toContain('greater than zero');
    });

    it('rejects too-small capital', () => {
      const [valid, message] = validateMockCapital(50000);
      expect(valid).toBe(false);
      expect(message).toContain('at least $100,000');
    });
  });

  describe('validateReason', () => {
    it('accepts valid reason', () => {
      expect(validateReason('Testing new momentum strategy')).toEqual([true, '']);
    });

    it('rejects whitespace-only reason', () => {
      const [valid, message] = validateReason('   ');
      expect(valid).toBe(false);
      expect(message).toContain('cannot be empty');
    });
  });

  describe('formatEquity', () => {
    it('formats large equity', () => {
      expect(formatEquity(1250000)).toBe('$1,250,000');
    });
  });

  describe('window status helpers', () => {
    it('reports near end and complete states', () => {
      expect(isNearEndOfWindow(100)).toBe(false);
      expect(isNearEndOfWindow(110)).toBe(true);
      expect(isWindowComplete(100)).toBe(false);
      expect(isWindowComplete(120)).toBe(true);
    });
  });
});

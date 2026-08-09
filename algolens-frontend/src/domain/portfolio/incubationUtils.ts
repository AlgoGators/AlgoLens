/**
 * Incubation utility functions: formatting, progress calculation, validation.
 *
 * Pure functions for the incubation UI. No side effects.
 */

// Incubation window: strategies are observed for 3-4 months
export const INCUBATION_WINDOW_DAYS = 120;

export function calculateIncubationProgress(
  daysElapsed: number,
  windowDays: number = INCUBATION_WINDOW_DAYS
): number {
  if (windowDays <= 0) return 0;
  const progress = (daysElapsed / windowDays) * 100;
  return Math.min(Math.max(progress, 0), 100);
}

export function calculateDaysRemaining(
  daysElapsed: number,
  windowDays: number = INCUBATION_WINDOW_DAYS
): number {
  return Math.max(windowDays - daysElapsed, 0);
}

export function formatIncubationDate(date: string | Date | null): string {
  if (!date) return 'N/A';

  const d = typeof date === 'string' ? new Date(date) : date;
  if (Number.isNaN(d.getTime())) return 'Invalid';

  return d.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatMockCapital(value: number | null | undefined): string {
  if (value === null || value === undefined) return '$0';

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

export function validateMockCapital(value: unknown): [boolean, string] {
  let numericValue = value;
  if (typeof numericValue === 'string') {
    numericValue = parseFloat(numericValue);
  }

  if (typeof numericValue !== 'number' || Number.isNaN(numericValue)) {
    return [false, 'Mock capital must be a number'];
  }

  if (numericValue <= 0) {
    return [false, 'Mock capital must be greater than zero'];
  }

  if (numericValue < 100000) {
    return [false, 'Mock capital must be at least $100,000'];
  }

  return [true, ''];
}

export function validateReason(reason: unknown): [boolean, string] {
  if (typeof reason !== 'string') {
    return [false, 'Reason must be text'];
  }

  const trimmed = reason.trim();
  if (!trimmed) {
    return [false, 'Reason cannot be empty'];
  }

  if (trimmed.length < 10) {
    return [false, 'Reason must be at least 10 characters'];
  }

  if (trimmed.length > 500) {
    return [false, 'Reason must not exceed 500 characters'];
  }

  return [true, ''];
}

export function formatEquity(value: number | null | undefined): string {
  if (value === null || value === undefined) return '$0';

  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

export function isNearEndOfWindow(
  daysElapsed: number,
  windowDays: number = INCUBATION_WINDOW_DAYS
): boolean {
  return daysElapsed >= windowDays - 14;
}

export function isWindowComplete(
  daysElapsed: number,
  windowDays: number = INCUBATION_WINDOW_DAYS
): boolean {
  return daysElapsed >= windowDays;
}

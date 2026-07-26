/**
 * Incubation utility functions: formatting, progress calculation, validation.
 *
 * Pure functions for the IncubationPanel component. No side effects.
 */

// Incubation window: strategies are observed for 3-4 months
export const INCUBATION_WINDOW_DAYS = 120;

/**
 * Calculate the progress percentage of an incubating strategy.
 *
 * @param daysElapsed Days since incubation_started_at
 * @param windowDays Total observation window (default 120)
 * @returns Progress as percentage (0-100)
 */
export function calculateIncubationProgress(
  daysElapsed: number,
  windowDays: number = INCUBATION_WINDOW_DAYS
): number {
  if (windowDays <= 0) return 0;
  const progress = (daysElapsed / windowDays) * 100;
  // Cap at 100 in case strategy runs past the window
  return Math.min(progress, 100);
}

/**
 * Format a date for display in the incubation UI.
 *
 * @param date ISO date string or Date object
 * @returns Formatted date string, e.g. "Jul 26, 2026"
 */
export function formatIncubationDate(date: string | Date | null): string {
  if (!date) return "N/A";

  const d = typeof date === "string" ? new Date(date) : date;
  if (isNaN(d.getTime())) return "Invalid";

  return d.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/**
 * Format a currency value for mock capital display.
 *
 * @param value Numeric value
 * @returns Formatted string, e.g. "$250,000"
 */
export function formatMockCapital(value: number | null): string {
  if (value === null || value === undefined) return "$0";

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

/**
 * Validate mock capital input.
 *
 * @param value String or number input from user
 * @returns Tuple of [isValid, errorMessage]
 */
export function validateMockCapital(value: unknown): [boolean, string] {
  if (typeof value === "string") {
    value = parseFloat(value);
  }

  if (typeof value !== "number" || isNaN(value)) {
    return [false, "Mock capital must be a number"];
  }

  if (value <= 0) {
    return [false, "Mock capital must be greater than zero"];
  }

  if (value < 100000) {
    return [false, "Mock capital must be at least $100,000"];
  }

  return [true, ""];
}

/**
 * Validate reason input (audit trail requirement).
 *
 * @param reason String input from user
 * @returns Tuple of [isValid, errorMessage]
 */
export function validateReason(reason: unknown): [boolean, string] {
  if (typeof reason !== "string") {
    return [false, "Reason must be text"];
  }

  const trimmed = reason.trim();
  if (!trimmed) {
    return [false, "Reason cannot be empty"];
  }

  if (trimmed.length < 10) {
    return [false, "Reason must be at least 10 characters"];
  }

  if (trimmed.length > 500) {
    return [false, "Reason must not exceed 500 characters"];
  }

  return [true, ""];
}

/**
 * Format equity value for display in performance chart.
 *
 * @param value Numeric equity
 * @returns Formatted string, e.g. "$250,000"
 */
export function formatEquity(value: number | null): string {
  if (value === null || value === undefined) return "$0";

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

/**
 * Check if a strategy is near the end of its incubation window.
 *
 * @param daysElapsed Days since start
 * @param windowDays Total window (default 120)
 * @returns True if within last 2 weeks (14 days) of window
 */
export function isNearEndOfWindow(
  daysElapsed: number,
  windowDays: number = INCUBATION_WINDOW_DAYS
): boolean {
  return daysElapsed >= windowDays - 14;
}

/**
 * Check if a strategy has completed its incubation window.
 *
 * @param daysElapsed Days since start
 * @param windowDays Total window (default 120)
 * @returns True if window is complete
 */
export function isWindowComplete(
  daysElapsed: number,
  windowDays: number = INCUBATION_WINDOW_DAYS
): boolean {
  return daysElapsed >= windowDays;
}

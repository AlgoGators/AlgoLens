import { describe, it, expect } from "vitest";
import {
  calculateIncubationProgress,
  formatIncubationDate,
  formatMockCapital,
  validateMockCapital,
  validateReason,
  formatEquity,
  isNearEndOfWindow,
  isWindowComplete,
  INCUBATION_WINDOW_DAYS,
} from "./incubationUtils";

describe("incubationUtils", () => {
  describe("calculateIncubationProgress", () => {
    it("returns 0 at day 0", () => {
      expect(calculateIncubationProgress(0)).toBe(0);
    });

    it("returns 50 at day 60 (halfway through 120-day window)", () => {
      expect(calculateIncubationProgress(60)).toBe(50);
    });

    it("returns 100 at day 120 (end of window)", () => {
      expect(calculateIncubationProgress(120)).toBe(100);
    });

    it("caps progress at 100 if past window", () => {
      expect(calculateIncubationProgress(150)).toBe(100);
    });

    it("respects custom window size", () => {
      expect(calculateIncubationProgress(25, 50)).toBe(50);
    });

    it("handles zero window gracefully", () => {
      expect(calculateIncubationProgress(10, 0)).toBe(0);
    });
  });

  describe("formatIncubationDate", () => {
    it("formats ISO date string", () => {
      const result = formatIncubationDate("2026-07-26T12:00:00Z");
      expect(result).toMatch(/Jul 26, 2026/);
    });

    it("formats Date object", () => {
      const date = new Date(2026, 6, 26); // Month is 0-indexed
      const result = formatIncubationDate(date);
      expect(result).toMatch(/Jul 26, 2026/);
    });

    it("returns N/A for null", () => {
      expect(formatIncubationDate(null)).toBe("N/A");
    });

    it("returns Invalid for malformed date", () => {
      expect(formatIncubationDate("not a date")).toBe("Invalid");
    });
  });

  describe("formatMockCapital", () => {
    it("formats $250,000", () => {
      expect(formatMockCapital(250000)).toBe("$250,000");
    });

    it("formats $1,000,000", () => {
      expect(formatMockCapital(1000000)).toBe("$1,000,000");
    });

    it("formats $100,000", () => {
      expect(formatMockCapital(100000)).toBe("$100,000");
    });

    it("returns $0 for null", () => {
      expect(formatMockCapital(null)).toBe("$0");
    });

    it("returns $0 for undefined", () => {
      expect(formatMockCapital(undefined)).toBe("$0");
    });
  });

  describe("validateMockCapital", () => {
    it("accepts valid numeric string", () => {
      const [valid, msg] = validateMockCapital("250000");
      expect(valid).toBe(true);
      expect(msg).toBe("");
    });

    it("accepts valid number", () => {
      const [valid, msg] = validateMockCapital(250000);
      expect(valid).toBe(true);
      expect(msg).toBe("");
    });

    it("rejects zero", () => {
      const [valid, msg] = validateMockCapital(0);
      expect(valid).toBe(false);
      expect(msg).toContain("greater than zero");
    });

    it("rejects negative", () => {
      const [valid, msg] = validateMockCapital(-100000);
      expect(valid).toBe(false);
      expect(msg).toContain("greater than zero");
    });

    it("rejects too small (< $100k)", () => {
      const [valid, msg] = validateMockCapital(50000);
      expect(valid).toBe(false);
      expect(msg).toContain("at least $100,000");
    });

    it("rejects non-numeric string", () => {
      const [valid, msg] = validateMockCapital("not a number");
      expect(valid).toBe(false);
      expect(msg).toContain("must be a number");
    });
  });

  describe("validateReason", () => {
    it("accepts valid reason", () => {
      const [valid, msg] = validateReason("Testing new momentum strategy");
      expect(valid).toBe(true);
      expect(msg).toBe("");
    });

    it("rejects empty string", () => {
      const [valid, msg] = validateReason("");
      expect(valid).toBe(false);
      expect(msg).toContain("cannot be empty");
    });

    it("rejects whitespace only", () => {
      const [valid, msg] = validateReason("   ");
      expect(valid).toBe(false);
      expect(msg).toContain("cannot be empty");
    });

    it("rejects too short (< 10 chars)", () => {
      const [valid, msg] = validateReason("test");
      expect(valid).toBe(false);
      expect(msg).toContain("at least 10 characters");
    });

    it("rejects too long (> 500 chars)", () => {
      const longReason = "a".repeat(501);
      const [valid, msg] = validateReason(longReason);
      expect(valid).toBe(false);
      expect(msg).toContain("must not exceed 500 characters");
    });

    it("rejects non-string", () => {
      const [valid, msg] = validateReason(12345);
      expect(valid).toBe(false);
      expect(msg).toContain("must be text");
    });
  });

  describe("formatEquity", () => {
    it("formats large equity", () => {
      expect(formatEquity(1250000)).toBe("$1,250,000");
    });

    it("formats small equity", () => {
      expect(formatEquity(5000)).toBe("$5,000");
    });

    it("returns $0 for null", () => {
      expect(formatEquity(null)).toBe("$0");
    });
  });

  describe("isNearEndOfWindow", () => {
    it("returns false at day 100 (> 14 days remaining)", () => {
      expect(isNearEndOfWindow(100)).toBe(false);
    });

    it("returns true at day 110 (< 10 days remaining)", () => {
      expect(isNearEndOfWindow(110)).toBe(true);
    });

    it("returns true at day 120 (0 days remaining)", () => {
      expect(isNearEndOfWindow(120)).toBe(true);
    });

    it("respects custom window", () => {
      expect(isNearEndOfWindow(40, 50)).toBe(true); // 50 - 14 = 36
    });
  });

  describe("isWindowComplete", () => {
    it("returns false before window end", () => {
      expect(isWindowComplete(100)).toBe(false);
    });

    it("returns true at window end", () => {
      expect(isWindowComplete(120)).toBe(true);
    });

    it("returns true past window end", () => {
      expect(isWindowComplete(150)).toBe(true);
    });

    it("respects custom window", () => {
      expect(isWindowComplete(51, 50)).toBe(true);
    });
  });
});

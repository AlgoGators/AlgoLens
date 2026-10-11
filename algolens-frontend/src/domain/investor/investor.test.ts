import { describe, expect, it } from 'vitest';
import {
  checkReportFile,
  formatBytes,
  formatCompactMoney,
  formatWeight,
  reportKindLabel,
} from './investor';

describe('investor formatting', () => {
  it('formats money compactly with its sign', () => {
    expect(formatCompactMoney(1_234_567)).toBe('$1.23M');
    expect(formatCompactMoney(-250_000)).toBe('-$250.0K');
    expect(formatCompactMoney(950)).toBe('$950');
    expect(formatCompactMoney(2.5e9)).toBe('$2.50B');
  });

  it('formats weights and sizes', () => {
    expect(formatWeight(0.8621)).toBe('86.2%');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(2048)).toBe('2 KB');
    expect(formatBytes(3 * 1024 * 1024)).toBe('3.0 MB');
  });

  it('labels report kinds', () => {
    expect(reportKindLabel('quarterly')).toBe('Quarterly report');
    expect(reportKindLabel('memo')).toBe('memo');
  });
});

describe('checkReportFile', () => {
  it('accepts a PDF up to 10 MB', () => {
    expect(checkReportFile({ name: 'q3.pdf', size: 1000, type: 'application/pdf' })).toBeNull();
    expect(checkReportFile({ name: 'Q3.PDF', size: 1000, type: '' })).toBeNull();
  });

  it('refuses no file, empty, too large and non-PDF files', () => {
    expect(checkReportFile(null)).toMatch(/Choose/);
    expect(checkReportFile({ name: 'a.pdf', size: 0, type: 'application/pdf' })).toMatch(/empty/);
    expect(checkReportFile({ name: 'a.pdf', size: 11 * 1024 * 1024, type: 'application/pdf' })).toMatch(/10 MB/);
    expect(checkReportFile({ name: 'a.docx', size: 10, type: 'application/msword' })).toMatch(/PDF/);
  });
});

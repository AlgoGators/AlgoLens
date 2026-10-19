/**
 * The investor screen (D-25): the one portfolio and book the investor follows (the QT book by
 * default, or the model book an admin set, decision 13) on its latest PUBLISHED day, with its
 * record to that day, and the reports and letters an admin uploads. The server picks the
 * portfolio, the book and the day; nothing here widens that.
 */

export interface InvestorPosition {
  symbol: string;
  root: string;
  name: string;
  sector: string;
  quantity: number;
  price: number;
  notional: number;
  side: 'long' | 'short';
  /** Share of the book's gross (absolute) notional, 0..1. */
  weight: number;
}

export interface SectorAllocation {
  sector: string;
  gross_notional: number;
  net_notional: number;
  count: number;
  weight: number;
}

export interface InvestorPortfolio {
  portfolio_id: string;
  name: string;
  portfolio_group?: string | null;
  /** D-25: the row set followed ("qt" the desk's final book, "system" a model book). */
  book?: 'qt' | 'system';
  follows?: 'qt' | 'model';
  label?: string;
  /** No admin set a book: the investor follows the QT book (decision 13). */
  default?: boolean;
  performance?: InvestorPerformance;
  /** The published day shown (YYYY-MM-DD), or null when none is published yet. */
  as_of: string | null;
  gross_notional: number;
  positions: InvestorPosition[];
  allocation: SectorAllocation[];
}

export type ReportKind = 'monthly' | 'quarterly' | 'letter' | 'other';

export const REPORT_KINDS: { kind: ReportKind; label: string }[] = [
  { kind: 'monthly', label: 'Monthly report' },
  { kind: 'quarterly', label: 'Quarterly report' },
  { kind: 'letter', label: 'Letter' },
  { kind: 'other', label: 'Other' },
];

export interface InvestorReport {
  id: number;
  title: string;
  kind: ReportKind;
  period_label: string | null;
  filename: string;
  size_bytes: number;
  uploaded_by: string | null;
  uploaded_at: string | null;
  published: boolean;
}

export const MAX_REPORT_BYTES = 10 * 1024 * 1024;

export function reportKindLabel(kind: string): string {
  return REPORT_KINDS.find(k => k.kind === kind)?.label ?? kind;
}

/** '$1.2M', '$250K', '$950': a compact money figure for the allocation cards. */
export function formatCompactMoney(value: number): string {
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function formatWeight(weight: number): string {
  return `${(weight * 100).toFixed(1)}%`;
}

export function formatBytes(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${bytes} B`;
}

/** A client-side check before upload; the server checks again (PDF bytes, size). */
export function checkReportFile(file: { name: string; size: number; type: string } | null): string | null {
  if (!file) return 'Choose a PDF file';
  if (file.size === 0) return 'The file is empty';
  if (file.size > MAX_REPORT_BYTES) return 'The file is larger than 10 MB';
  const looksPdf = file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
  if (!looksPdf) return 'Only PDF files can be uploaded';
  return null;
}

export interface InvestorPerformance {
  /** The book's equity by day up to the published day shown. */
  curve: { date: string; equity: number }[];
  value: number | null;
  /** Since the first day of the record, as a fraction (0.02 = +2%). */
  return: number | null;
}

/** "QT book" or "Model book": what an investor follows, in their words. */
export function followsLabel(portfolio: InvestorPortfolio): string {
  return portfolio.follows === 'model' ? 'Model book' : 'QT book';
}

/** D-25: one (portfolio, book) an admin can set an investor to follow. */
export interface InvestorBookChoice {
  portfolio_id: string;
  book: 'qt' | 'system';
  follows: 'qt' | 'model';
  label: string;
  name: string;
}

export interface InvestorLinks {
  stored: boolean;
  choices: InvestorBookChoice[];
  links: { user_id: number; portfolio_id: string; book: 'qt' | 'system' }[];
}

/** The key of a choice for a <select> ("QT_A|qt"). */
export const choiceKey = (c: { portfolio_id: string; book: string }) => `${c.portfolio_id}|${c.book}`;

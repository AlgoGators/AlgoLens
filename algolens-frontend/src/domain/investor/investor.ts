/**
 * The investor screen: the qt book of each desk portfolio's latest PUBLISHED
 * day (the book that was e-mailed out), and the reports and letters an admin
 * uploads. The server picks the day and book; nothing here widens that.
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
  portfolio_group: string | null;
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

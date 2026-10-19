import React, { useEffect, useState } from 'react';
import { Download, FileText } from 'lucide-react';
import { useTheme } from '../../adapters/react/ThemeContext';
import { InvestorService } from '../../application/identity/screenService';
import {
  followsLabel,
  formatBytes,
  formatCompactMoney,
  formatWeight,
  reportKindLabel,
  type InvestorPortfolio,
  type InvestorReport,
} from '../../domain/investor/investor';
import { Card, SectionTitle } from '../ScreenFrame';

function formatDay(day: string | null): string {
  if (!day) return '';
  // A calendar date (YYYY-MM-DD): format it without a timezone shift.
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', {
    timeZone: 'UTC',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function formatTimestamp(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

/**
 * The investor screen (read-only): each desk portfolio's published book, as
 * positions and an allocation by sector, and the reports and letters.
 */
export function InvestorHome() {
  const { theme } = useTheme();
  const dark = theme === 'dark';
  const muted = dark ? 'text-gray-400' : 'text-gray-500';
  const [portfolios, setPortfolios] = useState<InvestorPortfolio[] | null>(null);
  const [reports, setReports] = useState<InvestorReport[] | null>(null);
  const [allocationError, setAllocationError] = useState<string | null>(null);
  const [reportsError, setReportsError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    InvestorService.allocation()
      .then(data => !cancelled && setPortfolios(data))
      .catch(err => !cancelled && setAllocationError(err instanceof Error ? err.message : String(err)));
    InvestorService.reports()
      .then(data => !cancelled && setReports(data))
      .catch(err => !cancelled && setReportsError(err instanceof Error ? err.message : String(err)));
    return () => {
      cancelled = true;
    };
  }, []);

  const download = async (report: InvestorReport) => {
    setDownloadError(null);
    setDownloading(report.id);
    try {
      await InvestorService.downloadReport(report);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : String(err));
    } finally {
      setDownloading(null);
    }
  };

  const rowBorder = dark ? 'border-gray-800' : 'border-gray-200';
  const headRow = dark ? 'bg-gray-900 border-gray-800 text-gray-400' : 'bg-gray-50 border-gray-200 text-gray-500';
  const hoverRow = dark ? 'hover:bg-gray-900' : 'hover:bg-gray-50';

  return (
    <div className="space-y-10">
      <div>
        <h1 className="text-2xl mb-1">Investor</h1>
        <p className={`text-sm ${muted}`}>
          Your portfolio as published: the positions sent out on the latest trading day, and its
          record to that day.
        </p>
      </div>

      {allocationError ? (
        <p className="text-sm text-red-500">Could not load the positions: {allocationError}</p>
      ) : !portfolios ? (
        <p className={muted}>Loading positions...</p>
      ) : portfolios.length === 0 ? (
        <p className={muted}>No portfolio is published to investors yet.</p>
      ) : (
        portfolios.map(portfolio => (
          <section key={portfolio.portfolio_id} className="space-y-6">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div>
                <h2 className="text-xl">{portfolio.name}</h2>
                {/* D-25: the book this investor follows (decision 13). */}
                <p className={`text-sm ${muted}`} data-testid="investor-follows">
                  You follow its {followsLabel(portfolio)}
                  {portfolio.default ? ' (the default)' : ''}.
                </p>
              </div>
              <span className={`text-sm ${muted}`}>
                {portfolio.as_of ? `As of ${formatDay(portfolio.as_of)}` : 'Nothing published yet'}
              </span>
            </div>

            {portfolio.as_of && (
              <>
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  <Card className="p-4">
                    <div className={`text-sm mb-1 ${muted}`}>Gross exposure</div>
                    <div className="text-2xl">{formatCompactMoney(portfolio.gross_notional)}</div>
                  </Card>
                  <Card className="p-4">
                    <div className={`text-sm mb-1 ${muted}`}>Positions</div>
                    <div className="text-2xl">{portfolio.positions.length}</div>
                  </Card>
                  <Card className="p-4 col-span-2 md:col-span-1">
                    <div className={`text-sm mb-1 ${muted}`}>Sectors</div>
                    <div className="text-2xl">{portfolio.allocation.length}</div>
                  </Card>
                </div>

                {portfolio.performance && portfolio.performance.value !== null && (
                  <div className="grid grid-cols-2 gap-4" data-testid="investor-performance">
                    <Card className="p-4">
                      <div className={`text-sm mb-1 ${muted}`}>Value</div>
                      <div className="text-2xl">{formatCompactMoney(portfolio.performance.value)}</div>
                    </Card>
                    <Card className="p-4">
                      <div className={`text-sm mb-1 ${muted}`}>
                        Return since {formatDay(portfolio.performance.curve[0].date)}
                      </div>
                      <div className="text-2xl">
                        {portfolio.performance.return === null
                          ? '-'
                          : `${portfolio.performance.return >= 0 ? '+' : ''}${(portfolio.performance.return * 100).toFixed(2)}%`}
                      </div>
                    </Card>
                  </div>
                )}

                <div>
                  <SectionTitle>Allocation by sector</SectionTitle>
                  <Card className="p-4 space-y-3">
                    {portfolio.allocation.map(bucket => (
                      <div key={bucket.sector}>
                        <div className="flex items-baseline justify-between gap-4 text-sm mb-1">
                          <span>{bucket.sector}</span>
                          <span className={muted}>
                            {formatWeight(bucket.weight)} · net {formatCompactMoney(bucket.net_notional)} ·{' '}
                            {bucket.count} {bucket.count === 1 ? 'position' : 'positions'}
                          </span>
                        </div>
                        <div className={`h-2 rounded-full ${dark ? 'bg-gray-800' : 'bg-gray-100'}`}>
                          <div
                            className="h-2 rounded-full bg-orange-500"
                            style={{ width: `${Math.max(bucket.weight * 100, 0.5)}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </Card>
                </div>

                <div>
                  <SectionTitle>Positions</SectionTitle>
                  <div className={`border rounded-lg overflow-x-auto ${rowBorder}`}>
                    <div className="min-w-[640px]">
                      <div className={`grid grid-cols-6 gap-4 p-4 text-sm border-b ${headRow}`}>
                        <div className="col-span-2">Instrument</div>
                        <div>Sector</div>
                        <div className="text-right">Quantity</div>
                        <div className="text-right">Notional</div>
                        <div className="text-right">Weight</div>
                      </div>
                      {portfolio.positions.map((position, index) => (
                        <div
                          key={position.symbol}
                          className={`grid grid-cols-6 gap-4 p-4 text-sm transition-colors ${hoverRow} ${
                            index !== portfolio.positions.length - 1 ? `border-b ${rowBorder}` : ''
                          }`}
                        >
                          <div className="col-span-2">
                            <div>{position.name}</div>
                            <div className={muted}>{position.root}</div>
                          </div>
                          <div className={muted}>{position.sector}</div>
                          <div className="text-right">
                            <span className={position.side === 'short' ? 'text-red-500' : 'text-green-500'}>
                              {position.quantity > 0 ? '+' : ''}
                              {position.quantity.toLocaleString('en-US')}
                            </span>
                          </div>
                          <div className="text-right">{formatCompactMoney(position.notional)}</div>
                          <div className="text-right">{formatWeight(position.weight)}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </>
            )}
          </section>
        ))
      )}

      <section>
        <SectionTitle>Reports and letters</SectionTitle>
        {downloadError && <p className="text-sm text-red-500 mb-3">Download failed: {downloadError}</p>}
        {reportsError ? (
          <p className="text-sm text-red-500">Could not load the reports: {reportsError}</p>
        ) : !reports ? (
          <p className={muted}>Loading reports...</p>
        ) : reports.length === 0 ? (
          <p className={muted}>No reports have been published yet.</p>
        ) : (
          <Card>
            {reports.map((report, index) => (
              <div
                key={report.id}
                className={`flex items-center justify-between gap-4 p-4 ${
                  index !== reports.length - 1 ? `border-b ${rowBorder}` : ''
                }`}
              >
                <div className="flex items-start gap-3 min-w-0">
                  <FileText className="w-5 h-5 mt-0.5 flex-shrink-0 text-orange-500" />
                  <div className="min-w-0">
                    <div className="truncate">{report.title}</div>
                    <div className={`text-sm ${muted}`}>
                      {reportKindLabel(report.kind)}
                      {report.period_label ? ` · ${report.period_label}` : ''} ·{' '}
                      {formatTimestamp(report.uploaded_at)} · {formatBytes(report.size_bytes)}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => download(report)}
                  disabled={downloading === report.id}
                  className="flex items-center gap-2 text-sm bg-orange-500 text-white px-3 py-1.5 rounded hover:bg-orange-600 transition-colors disabled:opacity-60 flex-shrink-0"
                >
                  <Download className="w-4 h-4" />
                  {downloading === report.id ? 'Downloading...' : 'Download'}
                </button>
              </div>
            ))}
          </Card>
        )}
      </section>
    </div>
  );
}

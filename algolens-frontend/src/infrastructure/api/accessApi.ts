import type { Screen } from '../../domain/identity/screens';
import type { InvestorPortfolio, InvestorReport } from '../../domain/investor/investor';
import { apiDownload, apiRequest } from './apiRequest';

export interface AdminUser {
  id: number;
  email: string;
  first_name: string | null;
  last_name: string | null;
  role: string | null;
  screens: Screen[];
}

export interface ScreenChange {
  id: number;
  screens: Screen[];
  granted: Screen[];
  revoked: Screen[];
}

/** Screen access (GET /api/me/screens) and the admin's user screens. */
export const AccessApi = {
  myScreens: () => apiRequest<unknown>('GET', '/api/me/screens'),
  users: () => apiRequest<{ users: AdminUser[] }>('GET', '/api/admin/users').then(r => r.users),
  setScreens: (userId: number, screens: Screen[]) =>
    apiRequest<ScreenChange>('PUT', `/api/admin/users/${userId}/screens`, { screens }),
};

/** The investor screen's reads and the admin's report management. */
export const InvestorApi = {
  allocation: () =>
    apiRequest<{ portfolios: InvestorPortfolio[] }>('GET', '/api/investor/allocation').then(r => r.portfolios),
  reports: () =>
    apiRequest<{ reports: InvestorReport[] }>('GET', '/api/investor/reports').then(r => r.reports),
  downloadReport: (report: InvestorReport) =>
    apiDownload(`/api/investor/reports/${report.id}/download`, report.filename),

  adminReports: () =>
    apiRequest<{ reports: InvestorReport[] }>('GET', '/api/admin/reports').then(r => r.reports),
  adminDownloadReport: (report: InvestorReport) =>
    apiDownload(`/api/admin/reports/${report.id}/download`, report.filename),
  uploadReport: (fields: { title: string; kind: string; periodLabel: string; file: File }) => {
    const form = new FormData();
    form.append('title', fields.title);
    form.append('kind', fields.kind);
    form.append('period_label', fields.periodLabel);
    form.append('file', fields.file, fields.file.name);
    return apiRequest<InvestorReport>('POST', '/api/admin/reports', form);
  },
  updateReport: (reportId: number, changes: { title?: string; published?: boolean }) =>
    apiRequest<InvestorReport>('PATCH', `/api/admin/reports/${reportId}`, changes),
};

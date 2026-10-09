import type {
  DeskCommand,
  DeskState,
  QuantityChange,
  SymbolChoice,
} from '../../domain/qt/desk';
import type { SettingChange, SettingsState, SettingsVersion } from '../../domain/qt/settings';
import { API_BASE_URL } from './httpClient';

/** An API error with its HTTP status (409 = not seeded / conflict, ...). */
export class DeskApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = 'DeskApiError';
  }
}

/** The JS-readable CSRF companion of the httpOnly session cookie. */
function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrf_access_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (method !== 'GET') headers['X-CSRF-TOKEN'] = csrfToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    credentials: 'include',
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data: any = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const message =
      (data && (data.error || data.msg)) || `${response.status} ${response.statusText}`;
    throw new DeskApiError(response.status, message);
  }
  return data as T;
}

const desk = (portfolioId: string) => `/portfolio/desk/${encodeURIComponent(portfolioId)}`;

export interface CommandResult {
  command: DeskCommand;
  /** The fast-path gRPC outcome, for display only; the row is the record. */
  agent: string;
}

export interface ApprovalPage {
  request: DeskCommand;
  decision: DeskCommand | null;
  table: { symbol: string; model: number | null; asked: number | null; given: number | null; moved_by: string | null }[];
  viewer: { email: string; approver_role: 'vp' | 'president' | null; is_requester: boolean };
}

export const DeskApi = {
  state: (portfolioId: string) => request<DeskState>('GET', desk(portfolioId)),
  symbols: async (portfolioId: string) =>
    (await request<{ symbols: SymbolChoice[] }>('GET', `${desk(portfolioId)}/symbols`)).symbols,
  save: (portfolioId: string, changes: QuantityChange[], reason: string) =>
    request<CommandResult>('POST', `${desk(portfolioId)}/save`, { changes, reason }),
  command: (id: number) => request<DeskCommand>('GET', `/portfolio/desk/commands/${id}`),
  requestOverride: (portfolioId: string, reason: string) =>
    request<CommandResult>('POST', `${desk(portfolioId)}/override-request`, { reason }),
  publish: (portfolioId: string) => request<CommandResult>('POST', `${desk(portfolioId)}/publish`, {}),
  settings: (portfolioId: string) => request<SettingsState>('GET', `${desk(portfolioId)}/settings`),
  saveSettings: async (portfolioId: string, changes: SettingChange[], reason: string) =>
    (await request<{ version: SettingsVersion }>('POST', `${desk(portfolioId)}/settings`, { changes, reason }))
      .version,
  revertSettings: async (portfolioId: string, version: number, reason: string) =>
    (await request<{ version: SettingsVersion }>('POST', `${desk(portfolioId)}/settings/revert`, { version, reason }))
      .version,
  approval: (token: string) => request<ApprovalPage>('POST', '/portfolio/desk/approval', { token }),
  decide: (token: string, approved: boolean, reason: string) =>
    request<CommandResult>('POST', '/portfolio/desk/approval/decide', {
      token,
      approved,
      reason: reason.trim() || null,
    }),
};

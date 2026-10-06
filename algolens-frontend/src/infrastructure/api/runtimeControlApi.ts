import { API_BASE_URL, fetchWithAuth, postWithAuth } from './httpClient';

export type RuntimeIntent = {
  id: number; registry_id: string; portfolio_id: string; engine_strategy_id: string;
  action: 'run' | 'stop'; status: 'pending' | 'approved' | 'rejected' | 'superseded';
  registry_revision: number; stale?: boolean; requested_by: string; request_reason: string;
  requested_at: string; approved_by: string | null; approval_reason: string | null; approved_at: string | null;
  financial_summary: { portfolio_id: string; initial_capital: number;
    allocations: { strategy: string; allocation: number }[] };
};
export type RuntimeAttempt = {
  id: string; intent_id: number; registry_revision: number; producer_version: string;
  run_date: string; started_at: string; finished_at: string | null;
  status: 'running' | 'applied' | 'failed'; outcome: 'published' | 'stopped' | null;
  publication_id: string | null; failure_code: string | null;
};
export type RuntimeStatus = {
  enabled: boolean; engine_enabled: null; scope_supported: boolean; approval_eligible: boolean;
  registry_revision: number; registry_lifecycle: string;
  intent: RuntimeIntent | null; approved_intent: RuntimeIntent | null; latest_attempt: RuntimeAttempt | null;
};
type Outcome = { outcome: 'saved' } | { outcome: 'rejected'; message: string };
const errors: Record<string, string> = {
  runtime_disabled: 'Next-run control is disabled.',
  runtime_approval_forbidden: 'You are not currently eligible to approve execution.',
  runtime_scope_unsupported: 'This complete strategy and book are not configured for execution control.',
  runtime_configuration_unavailable: 'The reviewed execution configuration is unavailable.',
  runtime_request_stale: 'This request is no longer current. Refresh and submit a new request.',
  runtime_lifecycle_conflict: 'Run requests require an active live strategy; stop requests require a retired strategy.',
  invalid_request: 'Check the selected action, book and required reason.',
};
const endpoint = (id: string) => `${API_BASE_URL}/portfolio/strategies/${encodeURIComponent(id)}/runtime`;
async function mutate(url: string, body: unknown): Promise<Outcome> {
  const response = await postWithAuth(url, body);
  const payload = await response.json().catch(() => ({}));
  if (response.ok && Number.isInteger(payload.intent?.id)) return { outcome: 'saved' };
  if (response.ok || response.status >= 500) throw new Error('Uncertain runtime mutation');
  return { outcome: 'rejected', message: errors[payload.code] ?? 'The request was refused. Refresh status before retrying.' };
}
export const RuntimeControlApi = {
  async status(id: string, book: string): Promise<RuntimeStatus> {
    const response = await fetchWithAuth(`${endpoint(id)}?portfolio_id=${encodeURIComponent(book)}`);
    const data = await response.json();
    if (typeof data.enabled !== 'boolean' || typeof data.approval_eligible !== 'boolean'
        || typeof data.scope_supported !== 'boolean' || data.engine_enabled !== null
        || !('intent' in data) || !('latest_attempt' in data)) throw new Error('Invalid runtime status');
    return data;
  },
  request(id: string, body: { action: 'run' | 'stop'; portfolio_id: string; reason: string }) {
    return mutate(`${endpoint(id)}/requests`, body);
  },
  approve(id: string, intentId: number, reason: string) {
    return mutate(`${endpoint(id)}/requests/${intentId}/approve`, { reason });
  },
};

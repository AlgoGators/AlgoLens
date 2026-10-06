// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { RuntimeControlPanel } from './RuntimeControlPanel';

const api = vi.hoisted(() => ({ status: vi.fn(), request: vi.fn(), approve: vi.fn() }));
vi.mock('../infrastructure/api/runtimeControlApi', () => ({ RuntimeControlApi: api }));
vi.mock('../adapters/react/ThemeContext', () => ({ useTheme: () => ({ theme: 'light' }) }));
const base = { enabled: false, engine_enabled: null, approval_eligible: false, scope_supported: false,
  intent: null, approved_intent: null, latest_attempt: null, registry_revision: 0, registry_lifecycle: 'live' };
const intent = { id: 12, registry_id: 'trend', portfolio_id: 'BOOK', engine_strategy_id: 'LIVE_TEST',
  action: 'run', status: 'pending', registry_revision: 0, stale: false, requested_by: '7', request_reason: 'Review',
  requested_at: '2026-09-22T12:00:00Z', approved_by: null, approval_reason: null, approved_at: null,
  financial_summary: { portfolio_id: 'BOOK', initial_capital: 1000,
    allocations: [{ strategy: 'TEST', allocation: 1 }] } };
beforeEach(() => { Object.values(api).forEach(fn => fn.mockReset()); api.status.mockResolvedValue(base); });
afterEach(cleanup);
function open() {
  render(<RuntimeControlPanel strategyId="trend" portfolioId="BOOK" strategyName="Trend" />);
  fireEvent.click(screen.getByRole('button', { name: 'Next-run status for Trend in BOOK' }));
}

it('loads only when expanded and states the disabled engine boundary honestly', async () => {
  render(<RuntimeControlPanel strategyId="trend" portfolioId="BOOK" strategyName="Trend" />);
  expect(api.status).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Next-run status for Trend in BOOK' }));
  expect(await screen.findByText(/Next-run control is disabled/)).toBeTruthy();
  expect(screen.getByText(/No engine acknowledgement has been recorded/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Submit runtime request' })).toBeNull();
});

it('shows the exact capital and allocation before an eligible admin approves', async () => {
  api.status.mockResolvedValue({ ...base, enabled: true, scope_supported: true, approval_eligible: true, intent });
  api.approve.mockResolvedValue({ outcome: 'saved' });
  open();
  await screen.findByText(/Configured capital: 1,000/);
  expect(screen.getByText('TEST: 100%')).toBeTruthy();
  const button = screen.getByRole('button', { name: 'Approve request #12' });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Reason for execution approval'), { target: { value: 'Reviewed exact allocation' } });
  fireEvent.click(button);
  await waitFor(() => expect(api.approve).toHaveBeenCalledWith('trend', 12, 'Reviewed exact allocation'));
  expect(api.request).not.toHaveBeenCalled();
});

it('does not show approval to a general member and submits only selected scope intent', async () => {
  api.status.mockResolvedValue({ ...base, enabled: true, scope_supported: true, intent });
  api.request.mockResolvedValue({ outcome: 'saved' });
  open();
  await screen.findByText(/Configured capital/);
  expect(screen.queryByRole('button', { name: /Approve request/ })).toBeNull();
  fireEvent.change(screen.getByLabelText('Reason for runtime request'), { target: { value: 'Next scheduled run' } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit runtime request' }));
  await waitFor(() => expect(api.request).toHaveBeenCalledWith('trend', {
    action: 'run', portfolio_id: 'BOOK', reason: 'Next scheduled run',
  }));
});

it('keeps a pending mutation single-flight and prevents hiding it', async () => {
  api.status.mockResolvedValue({ ...base, enabled: true, scope_supported: true, intent });
  api.request.mockReturnValue(new Promise(() => undefined));
  open();
  await screen.findByText(/Configured capital/);
  fireEvent.change(screen.getByLabelText('Reason for runtime request'), { target: { value: 'Review' } });
  const submit = screen.getByRole('button', { name: 'Submit runtime request' });
  fireEvent.click(submit); fireEvent.click(submit);
  expect(api.request).toHaveBeenCalledTimes(1);
  expect((screen.getByRole('button', { name: 'Next-run status for Trend in BOOK' }) as HTMLButtonElement).disabled).toBe(true);
});

it('requires refresh after an uncertain mutation and never automatically retries', async () => {
  api.status.mockResolvedValue({ ...base, enabled: true, scope_supported: true, intent });
  api.request.mockRejectedValue(new Error('private raw detail'));
  open();
  await screen.findByText(/Configured capital/);
  fireEvent.change(screen.getByLabelText('Reason for runtime request'), { target: { value: 'Review' } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit runtime request' }));
  expect((await screen.findByRole('alert')).textContent).toMatch(/outcome is uncertain/i);
  expect(screen.queryByText('private raw detail')).toBeNull();
  expect((screen.getByRole('button', { name: 'Submit runtime request' }) as HTMLButtonElement).disabled).toBe(true);
  expect(api.request).toHaveBeenCalledTimes(1);
});

it('distinguishes a failed old attempt from a new pending request', async () => {
  api.status.mockResolvedValue({ ...base, intent, latest_attempt: { id: 'attempt', intent_id: 9,
    status: 'failed', outcome: null, failure_code: 'publication_failed', run_date: '2026-09-22',
    started_at: '2026-09-22T12:00:00Z', finished_at: '2026-09-22T12:01:00Z',
    publication_id: null, producer_version: 'test', registry_revision: 0 } });
  open();
  expect(await screen.findByText('Request #12: pending approval')).toBeTruthy();
  expect(screen.getByText(/Engine attempt for request #9: failed/)).toBeTruthy();
  expect(screen.queryByText(/Request #12: applied/)).toBeNull();
});

it('does not discard an in-flight mutation when sibling lifecycle history refreshes', async () => {
  api.status.mockResolvedValue({ ...base, enabled: true, scope_supported: true, intent });
  api.request.mockReturnValue(new Promise(() => undefined));
  const view = render(<RuntimeControlPanel strategyId="trend" portfolioId="BOOK" strategyName="Trend" refreshKey={0} />);
  fireEvent.click(screen.getByRole('button', { name: 'Next-run status for Trend in BOOK' }));
  await screen.findByText(/Configured capital/);
  fireEvent.change(screen.getByLabelText('Reason for runtime request'), { target: { value: 'Review' } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit runtime request' }));
  view.rerender(<RuntimeControlPanel strategyId="trend" portfolioId="BOOK" strategyName="Trend" refreshKey={1} />);
  expect((screen.getByRole('button', { name: 'Next-run status for Trend in BOOK' }) as HTMLButtonElement).disabled).toBe(true);
  expect(api.request).toHaveBeenCalledTimes(1);
});

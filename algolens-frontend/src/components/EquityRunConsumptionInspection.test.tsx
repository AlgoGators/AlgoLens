/** @vitest-environment jsdom */
import React from 'react';
import '@testing-library/jest-dom/vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { EquityRunConsumptionInspection } from './EquityRunConsumptionInspection';
import { validateEquityRunConsumption } from '../domain/portfolio/equityRunConsumption';

const fixture = JSON.parse(readFileSync(resolve('../contracts/equity-inspection-v3-synthetic-available.json'), 'utf8')).publication.equity_run_consumption;
const missing = JSON.parse(readFileSync(resolve('../contracts/equity-inspection-v3-synthetic-unavailable.json'), 'utf8')).publication.equity_run_consumption;
afterEach(cleanup);
describe('visible equity setting evidence', () => {
  it('shows the exact book/date and all ten stage outcomes', () => {
    validateEquityRunConsumption(fixture, fixture.run_key);
    render(<EquityRunConsumptionInspection consumption={fixture} />);
    expect(screen.getByText(/Book: BOOK/)).toBeInTheDocument();
    expect(screen.getByText(/Run date: 2026-09-26/)).toBeInTheDocument();
    for (const name of Object.keys(fixture.stages)) {
      expect(screen.getByRole('button', { name: new RegExp(`Show ${name.replaceAll('_', ' ')} observations`) })).toBeInTheDocument();
    }
    expect(screen.getByText(/does not establish investor report readiness/i)).toBeInTheDocument();
  });
  it('shows exact recorded money text without numeric conversion', () => {
    const child = structuredClone(fixture);
    child.stages.result_assembly.reads.current_portfolio_value_exact = '100000.00000001';
    validateEquityRunConsumption(child, child.run_key);
    render(<EquityRunConsumptionInspection consumption={child} />);
    fireEvent.click(screen.getByRole('button', { name: /Show result assembly observations/ }));
    expect(screen.getByText('100000.00000001')).toBeInTheDocument();
  });
  it('preserves a recorded unavailable stage rather than displaying complete coverage', () => {
    validateEquityRunConsumption(missing, missing.run_key);
    render(<EquityRunConsumptionInspection consumption={missing} />);
    expect(screen.getByText(/Read coverage: unavailable/)).toBeInTheDocument();
    expect(screen.queryByText(/Read coverage: complete/)).not.toBeInTheDocument();
    expect(missing.unavailable_reason).not.toBeNull();
    expect(screen.getByText(new RegExp(missing.unavailable_reason!.replaceAll('_', ' ')))).toBeInTheDocument();
  });
  it('expands the actual execution owner and recorded cost without defaults', () => {
    render(<EquityRunConsumptionInspection consumption={fixture} />);
    fireEvent.click(screen.getByRole('button', { name: /Show execution observations/ }));
    expect(screen.getByText(/actual-fixture-ID/)).toBeInTheDocument();
    expect(screen.getByText(/EQUITY_MEAN_REVERSION/)).toBeInTheDocument();
    expect(screen.getByText('total_transaction_costs_exact')).toBeInTheDocument();
  });
  it('shows the actual risk pass and keeps internal charges separate from saved executions', () => {
    const child = structuredClone(fixture); child.stages.setup.reads.use_risk_management = true;
    const portfolio = child.stages.primary.reads.portfolio_invocation;
    portfolio.skip_execution_generation = false;
    portfolio.passes[0].reads.use_risk_management = true; portfolio.passes[0].risk_helper = 'returned_ok';
    portfolio.passes[0].risk = { call: 'returned_ok', skip: 'none', manager_source: 'external',
      reads: { capital_exact: '100000.00000001', var_limit: .05 } };
    portfolio.strategy_charges = [{ index: 0, purpose: 'per_strategy', strategy_id: 'LIVE_EQUITY_MEAN_REVERSION',
      symbol: 'STRATEGY_SYN', call: 'returned_ok', reads: { quantity: 1.25, reference_price: 20,
        input_source: 'internally_tracked', asset_lookup_path: 'exact_symbol' } }];
    portfolio.compatibility_charges = [{ index: 0, purpose: 'compatibility', strategy_id: '',
      symbol: 'COMPAT_SYN', call: 'returned_ok', reads: { quantity: 2, reference_price: 20,
        input_source: 'explicit_values', asset_lookup_path: 'fallback' } }];
    validateEquityRunConsumption(child, child.run_key);
    render(<EquityRunConsumptionInspection consumption={child} />);
    fireEvent.click(screen.getByRole('button', { name: /Show primary observations/ }));
    expect(screen.getByText(/Risk manager: external/)).toBeInTheDocument();
    expect(screen.getByText('100000.00000001')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Strategy internal cost calls' })).getByText(/STRATEGY_SYN/)).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Compatibility internal cost calls' })).getByText(/COMPAT_SYN/)).toBeInTheDocument();
    expect(screen.getByText(/These internal calls do not establish saved executions/)).toBeInTheDocument();
  });
  it('bounds the visible execution list and exposes the next records on request', () => {
    const child = structuredClone(fixture); const first = child.stages.execution.executions[0];
    child.stages.execution.executions = Array.from({ length: 26 }, (_, index) => ({ ...structuredClone(first), index, execution_id: `synthetic-${index}` }));
    validateEquityRunConsumption(child, child.run_key);
    render(<EquityRunConsumptionInspection consumption={child} />);
    fireEvent.click(screen.getByRole('button', { name: /Show execution observations/ }));
    expect(screen.getByText('Showing 25 of 26 executions.')).toBeInTheDocument();
    expect(screen.queryByText(/Execution 25:/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show more executions' }));
    expect(screen.getByText(/Execution 25: synthetic-25/)).toBeInTheDocument();
  });
});

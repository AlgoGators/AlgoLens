// @vitest-environment jsdom
import React from 'react';
import { readFileSync } from 'node:fs';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { validateConsumptionV2, type ConsumptionNode, type ConsumptionV2 } from '../domain/portfolio/consumptionInspection';
import { ConsumptionInspection } from './ConsumptionInspection';
import { CONSUMPTION_CATALOG } from '../domain/portfolio/consumptionCatalog';

const captured = JSON.parse(readFileSync(
  'src/infrastructure/api/__fixtures__/configurationInspectionV2Http/publish_required_complete-5bcf79c0c445.http.json',
  'utf8',
)).publication.consumption as ConsumptionV2;

describe('read-only consumption evidence presentation', () => {
  it('renders native equity observations from the shared synthetic-context property artifact', () => {
    const child = JSON.parse(readFileSync('../contracts/consumption-v2-equity-native.json', 'utf8')) as ConsumptionV2;
    const before = structuredClone(child);
    expect(validateConsumptionV2(child)).toBe(child);
    render(<ConsumptionInspection consumption={child} />);
    for (const button of screen.getAllByRole('button', { name: /^Show .* observations/ })) fireEvent.click(button);
    const nodes = child.nodes.filter(node => ['cost.estimate', 'cost.strategy_execution',
      'cost.compatibility_execution', 'cost.execution'].includes(node.consumer));
    expect(nodes).toHaveLength(4);
    for (const node of nodes) {
      fireEvent.click(screen.getByRole('button', { name: new RegExp(`Observation #${node.id}: ${node.consumer}`) }));
      const table = screen.getByRole('table', { name: `Observation #${node.id} setting reads` });
      expect(within(table).getAllByRole('rowheader')).toHaveLength(node.reads.length);
      for (const read of node.reads) {
        const row = within(table).getByRole('rowheader', { name: read.field }).closest('tr')!;
        expect(within(row).getByText(String(read.value))).toBeTruthy();
        expect(within(row).getByText(read.value_type)).toBeTruthy();
        expect(within(row).getByText(read.origin)).toBeTruthy();
      }
      expect(within(table).queryByRole('rowheader', { name: 'cost.charge.explicit_fee_per_contract' })).toBeNull();
      expect(within(table).queryByRole('rowheader', { name: 'cost.volatility.lambda' })).toBeNull();
    }
    expect(child).toEqual(before);
  });

  it('renders all 40 synthetic equity reads with exact false and negative values', () => {
    const child = (JSON.parse(readFileSync('../contracts/consumption-v2-cases.json', 'utf8')) as {
      accepted: { rich: ConsumptionV2 };
    }).accepted.rich;
    const equityFieldNames = new Set([
      'cost.spread.tick_constrained', 'cost.charge.commission_per_unit',
      'cost.charge.max_commission_pct', 'cost.charge.max_commission_per_order',
      'cost.charge.min_commission_per_order', 'cost.charge.apply_regulatory_fees',
      'cost.charge.sec_fee_per_million', 'cost.charge.finra_taf_per_share',
      'cost.charge.finra_taf_cap_per_trade', 'cost.charge.max_total_implicit_bps',
    ]);
    const fields = CONSUMPTION_CATALOG.fields.filter(spec => equityFieldNames.has(spec.field));
    expect(fields).toHaveLength(40);
    for (const spec of fields) {
      const node = child.nodes.find(item => item.consumer === spec.consumer)!;
      node.reads.push({ field: spec.field, value_type: spec.type,
        value: spec.type === 'bool' ? false : -7.875, origin: 'runtime_effective' });
    }
    const before = structuredClone(child);
    expect(validateConsumptionV2(child)).toBe(child);
    render(<ConsumptionInspection consumption={child} />);
    for (const button of screen.getAllByRole('button', { name: /^Show .* observations/ })) fireEvent.click(button);
    for (const consumer of new Set(fields.map(spec => spec.consumer))) {
      const node = child.nodes.find(item => item.consumer === consumer)!;
      fireEvent.click(screen.getByRole('button', { name: new RegExp(`Observation #${node.id}: ${consumer}`) }));
      const table = screen.getByRole('table', { name: `Observation #${node.id} setting reads` });
      for (const spec of fields.filter(item => item.consumer === consumer)) {
        const row = within(table).getByRole('rowheader', { name: spec.field }).closest('tr')!;
        expect(within(row).getByText(spec.type === 'bool' ? 'false' : '-7.875')).toBeTruthy();
        expect(within(row).getByText(spec.type)).toBeTruthy();
        expect(within(row).getByText('runtime_effective')).toBeTruthy();
      }
    }
    expect(child).toEqual(before);
  });

  it('keeps every present aria-controls target mounted through lazy expand and collapse', () => {
    render(<ConsumptionInspection consumption={captured} />);
    const stage = screen.getByRole('button', { name: /Show setup observations/ });
    const checkPresentTargets = () => {
      for (const button of screen.getAllByRole('button')) {
        const target = button.getAttribute('aria-controls');
        if (target !== null) expect(document.getElementById(target)).toBeTruthy();
      }
    };
    expect(stage.getAttribute('aria-expanded')).toBe('false');
    checkPresentTargets();
    fireEvent.click(stage);
    expect(stage.getAttribute('aria-expanded')).toBe('true');
    expect(document.getElementById(stage.getAttribute('aria-controls')!)).toBeTruthy();
    checkPresentTargets();
    const node = screen.getByRole('button', { name: /Observation #0: setup.selector/ });
    fireEvent.click(node);
    expect(node.getAttribute('aria-expanded')).toBe('true');
    expect(document.getElementById(node.getAttribute('aria-controls')!)).toBeTruthy();
    checkPresentTargets();
    fireEvent.click(node);
    expect(node.getAttribute('aria-expanded')).toBe('false');
    checkPresentTargets();
    fireEvent.click(stage);
    expect(stage.getAttribute('aria-expanded')).toBe('false');
    checkPresentTargets();
  });

  it('places every captured observation in its catalog stage and exposes exact typed reads', () => {
    render(<ConsumptionInspection consumption={captured} />);
    expect(screen.getAllByRole('heading', { level: 4 }).map(item => item.textContent)).toEqual([
      'Show setup observations — complete (reason: none)',
      'Show market input observations — complete (reason: none)',
      'Show cost history observations — complete (reason: none)',
      'Show preparation observations — complete (reason: none)',
      'Show primary observations — complete (reason: none)',
      'Show execution observations — complete (reason: none)',
      'Show diagnostics observations — complete (reason: none)',
      'Show control flow observations — complete (reason: none)',
    ]);
    for (const [stage, count] of [
      ['setup', 6], ['market input', 2], ['cost history', 0], ['preparation', 1],
      ['primary', 2], ['execution', 1], ['diagnostics', 2], ['control flow', 2],
    ] as const) expect(screen.getByText(`${count} recorded observations in ${stage}.`)).toBeTruthy();
    expect(screen.queryByRole('table', { name: /setting reads/ })).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: /Show setup observations/ }));
    fireEvent.click(screen.getByRole('button', { name: /Observation #2: setup.selection_entry/ }));
    expect(screen.getByText('Parent observation: #1')).toBeTruthy();
    expect(screen.getByText('Strategy: TREND')).toBeTruthy();
    expect(screen.getByText('enabled_live_present:').parentElement?.textContent).toContain('true');
    const enabled = screen.getByRole('rowheader', { name: 'setup.selection.enabled_live' }).closest('tr');
    expect(enabled?.textContent).toContain('true');
    expect(enabled?.textContent).toContain('bool');
    expect(enabled?.textContent).toContain('configured_strategy_leaf');
    const derived = screen.getByRole('rowheader', { name: 'setup.selection.effective_allocation' }).closest('tr');
    expect(derived?.textContent).toContain('derived');

    fireEvent.click(screen.getByRole('button', { name: /Observation #5: portfolio.registration/ }));
    const zero = screen.getByRole('rowheader', { name: 'portfolio.registration.min_allocation' }).closest('tr');
    expect(zero?.textContent).toContain('0');
    expect(zero?.textContent).toContain('runtime_effective');
    fireEvent.click(screen.getByRole('button', { name: /Show diagnostics observations/ }));
    fireEvent.click(screen.getByRole('button', { name: /Observation #13: risk.diagnostics/ }));
    const decimal = screen.getByRole('rowheader', { name: 'risk.capital' }).closest('tr');
    expect(decimal?.textContent).toContain('-92233720368.54775808');
    expect(decimal?.textContent).toContain('fixed_decimal8');
  });

  it('explains parser-admitted non-trading skips and missing stage evidence in a synthetic UI-only case', () => {
    const syntheticUiOnly = (JSON.parse(readFileSync('../contracts/consumption-v2-cases.json', 'utf8')) as {
      accepted: { non_trading_skip: ConsumptionV2 };
    }).accepted.non_trading_skip;
    expect(validateConsumptionV2(syntheticUiOnly)).toBe(syntheticUiOnly);
    render(<ConsumptionInspection consumption={syntheticUiOnly} />);
    for (const stage of ['preparation', 'primary']) {
      const button = screen.getByRole('button', {
        name: new RegExp(`Show ${stage} observations — skipped \\(reason: non_trading_day\\)`),
      });
      fireEvent.click(button);
      const body = document.getElementById(button.getAttribute('aria-controls')!);
      expect(within(body!).getByText('No observations recorded for this stage; coverage is skipped (reason: non_trading_day).')).toBeTruthy();
    }
    fireEvent.click(screen.getByRole('button', { name: /Show execution observations — partial/ }));
    expect(screen.getByText('No observations recorded for this stage; coverage is partial (reason: instrumentation_missing).')).toBeTruthy();
  });

  it('keeps repeat calls, symbols, false, zero and pairs distinct in a synthetic UI-only case', () => {
    const syntheticNodes: ConsumptionNode[] = [
      { id: 0, parent: null, kind: 'call', consumer: 'execution.history_update', symbol: 'ES', outcome: 'returned_ok', meta: {},
        reads: [
          { field: 'test.enabled', value: false, value_type: 'bool', origin: 'runtime_effective' },
          { field: 'test.threshold', value: 0, value_type: 'number', origin: 'derived' },
          { field: 'test.pairs', value: [[1, 2.5], [3, 4]], value_type: 'int32_number_pairs', origin: 'configured_strategy_leaf', symbol: 'ES' },
        ] },
      { id: 1, parent: null, kind: 'call', consumer: 'execution.history_update', symbol: 'NQ', outcome: 'returned_error', meta: {},
        reads: [{ field: 'test.pairs', value: [[5, 0]], value_type: 'int32_number_pairs', origin: 'runtime_effective', symbol: 'NQ' }] },
    ];
    render(<ConsumptionInspection consumption={{ ...captured, nodes: syntheticNodes }} />);
    fireEvent.click(screen.getByRole('button', { name: /Show cost history observations/ }));
    expect(screen.getByText('Showing 2 of 2 observations.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Observation #0: execution.history_update/ }));
    fireEvent.click(screen.getByRole('button', { name: /Observation #1: execution.history_update/ }));
    expect(screen.getByText('Symbol: ES')).toBeTruthy();
    expect(screen.getByText('Symbol: NQ')).toBeTruthy();
    const firstTable = screen.getByRole('table', { name: 'Observation #0 setting reads' });
    expect(within(firstTable).getByRole('rowheader', { name: 'test.enabled' }).closest('tr')?.textContent).toContain('false');
    expect(within(firstTable).getByRole('rowheader', { name: 'test.threshold' }).closest('tr')?.textContent).toContain('0');
    expect(within(firstTable).getByRole('rowheader', { name: 'test.pairs' }).closest('tr')?.textContent).toContain('[[1,2.5],[3,4]]');
    expect(within(firstTable).getByRole('rowheader', { name: 'test.pairs' }).closest('tr')?.textContent).toContain('ES');
    expect(within(screen.getByRole('table', { name: 'Observation #1 setting reads' }))
      .getByRole('rowheader', { name: 'test.pairs' }).closest('tr')?.textContent).toContain('[[5,0]]');
  });

  it('lazily mounts and pages all nodes and reads in a synthetic UI-only large list', () => {
    const nodes: ConsumptionNode[] = Array.from({ length: 60 }, (_, id) => ({
      id, parent: null, kind: 'call', consumer: 'setup.selector', outcome: 'returned_ok', meta: {},
      reads: id === 59 ? Array.from({ length: 120 }, (_, index) => ({
        field: `synthetic.read.${index}`, value: index, value_type: 'int32', origin: 'derived',
      })) : [],
    }));
    render(<ConsumptionInspection consumption={{ ...captured, nodes }} />);
    expect(screen.queryByRole('button', { name: /Observation #0:/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Show setup observations/ }));
    expect(screen.getByText('Showing 25 of 60 observations.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Observation #59:/ })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Show more setup observations' }));
    expect(screen.getByText('Showing 50 of 60 observations.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show more setup observations' }));
    expect(screen.getByText('Showing 60 of 60 observations.')).toBeTruthy();
    expect(screen.getAllByRole('button', { name: /Observation #\d+:/ })).toHaveLength(60);
    expect(screen.queryByRole('table', { name: 'Observation #59 setting reads' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Observation #59:/ }));
    const region = screen.getByRole('region', { name: 'Observation #59 setting reads table' });
    expect(region.tabIndex).toBe(0);
    expect(within(region).getAllByRole('rowheader')).toHaveLength(50);
    fireEvent.click(screen.getByRole('button', { name: 'Show more reads for observation #59' }));
    expect(within(region).getAllByRole('rowheader')).toHaveLength(100);
    fireEvent.click(screen.getByRole('button', { name: 'Show more reads for observation #59' }));
    expect(within(region).getAllByRole('rowheader')).toHaveLength(120);
    expect(within(region).getByRole('rowheader', { name: 'synthetic.read.119' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Show more reads for observation #59' })).toBeNull();
  });
});

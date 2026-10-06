import React, { useId, useState } from 'react';
import type { EquityRunConsumption, EquityRunStage } from '../domain/portfolio/equityRunConsumption';
import type { EquityPortfolioConsumption, EquityPortfolioCharge } from '../domain/portfolio/equityPortfolioConsumption';

const PAGE = 25;
const buttonClass = 'rounded border border-gray-400 px-2 py-1 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500';
const label = (value: string) => value.replaceAll('_', ' ');
function ReadValues({ reads }: { reads: Record<string, unknown> }) {
  if (Object.keys(reads).length === 0) return <p className="text-xs">No reads recorded here. Missing evidence does not show that a setting was unused.</p>;
  return <dl className="space-y-2 text-xs">
    {Object.entries(reads).map(([field, value]) => <div key={field} className="min-w-0">
      <dt className="font-mono font-semibold break-all">{field}</dt>
      <dd className="font-mono break-all">{field === 'strategy_invocation'
        ? <StrategyReads value={value as { symbols: Record<string, { reads: Record<string, unknown>; observed_state: Record<string, unknown> }> }} />
        : field === 'portfolio_invocation' ? <PortfolioReads value={value as EquityPortfolioConsumption} /> : String(value)}</dd>
    </div>)}
  </dl>;
}
function PagedRecords<T>({ values, name, render }: { values: T[]; name: string; render: (value: T, index: number) => React.ReactNode }) {
  const [shown, setShown] = useState(PAGE);
  return <div className="space-y-3 min-w-0">
    <p className="text-xs">Showing {Math.min(shown, values.length)} of {values.length} {name}.</p>
    {values.slice(0, shown).map((value, index) => <div key={index} className="rounded border border-gray-300 p-3 dark:border-gray-700">{render(value, index)}</div>)}
    {shown < values.length && <button type="button" className={buttonClass} onClick={() => setShown(count => count + PAGE)}>Show more {name}</button>}
  </div>;
}
function StrategyReads({ value }: { value: { symbols: Record<string, { reads: Record<string, unknown>; observed_state: Record<string, unknown> }> } }) {
  return <div className="space-y-2">
    <p>Recorded strategy call. This child covers the strategy invocation.</p>
    <PagedRecords name="strategy symbols" values={Object.entries(value.symbols)} render={([symbol, row]) => <>
      <p className="font-semibold">{symbol}</p><ReadValues reads={row.reads} />
      <p className="mt-2 font-semibold">Observed state</p><ReadValues reads={row.observed_state} />
    </>} />
  </div>;
}
function PortfolioCharges({ title, values }: { title: string; values: EquityPortfolioCharge[] }) {
  return <section aria-label={title} className="space-y-2">
    <h5 className="font-semibold">{title}</h5>
    <PagedRecords name={title.toLowerCase()} values={values} render={row => <>
      <p className="break-all">Call {row.index}: {row.symbol}; {label(row.call)}</p>
      {row.strategy_id && <p className="break-all">Engine: {row.strategy_id}</p>}
      <ReadValues reads={row.reads} />
    </>} />
  </section>;
}
function PortfolioReads({ value }: { value: EquityPortfolioConsumption }) {
  return <div className="space-y-3">
    <p>Recorded portfolio call: {label(value.outcome)}. Coverage: {value.available ? 'available' : 'unavailable'}.</p>
    {value.unavailable_reason && <p>Reason: {label(value.unavailable_reason)}</p>}
    <p>Execution generation skipped: {value.skip_execution_generation === null ? 'unobserved' : String(value.skip_execution_generation)}</p>
    <PagedRecords name="portfolio passes" values={value.passes} render={pass => <>
      <p className="font-semibold">Pass {pass.index}</p><ReadValues reads={pass.reads} />
      <p>Optimization helper: {label(pass.optimization_helper)}; Risk helper: {label(pass.risk_helper)}</p>
      <p>Risk call: {label(pass.risk.call)}; Skip: {label(pass.risk.skip)}</p>
      {pass.risk.manager_source !== undefined && <p>Risk manager: {pass.risk.manager_source}</p>}
      {pass.risk.lookback_period !== undefined && <p>Risk lookback: {pass.risk.lookback_period}</p>}
      <ReadValues reads={pass.risk.reads} />
    </>} />
    <p>These internal calls do not establish saved executions.</p>
    <PortfolioCharges title="Strategy internal cost calls" values={value.strategy_charges} />
    <PortfolioCharges title="Compatibility internal cost calls" values={value.compatibility_charges} />
  </div>;
}
function Stage({ name, stage }: { name: string; stage: EquityRunStage }) {
  const [expanded, setExpanded] = useState(false); const bodyId = useId();
  return <article className="min-w-0 border-t border-gray-300 py-3 dark:border-gray-700">
    <h4 className="text-sm font-semibold"><button type="button" aria-expanded={expanded}
      aria-controls={expanded ? bodyId : undefined} onClick={() => setExpanded(value => !value)} className="text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
      {expanded ? 'Hide' : 'Show'} {label(name)} observations — {label(stage.outcome)}
    </button></h4>
    {stage.skip_reason && <p className="text-xs">Skip reason: {label(stage.skip_reason)}</p>}
    {expanded && <div id={bodyId} className="mt-3 space-y-3 min-w-0">
      {name === 'corporate_actions' && stage.outcome === 'returned_ok' && stage.reads.path === 'proved_action_adjusted_prior' &&
        <p className="text-xs">These actions were recorded in the proved prior and next MODEL seed. This MODEL run did not reapply them.</p>}
      <ReadValues reads={stage.reads} />
      {Object.keys(stage.symbols).length > 0 && <PagedRecords name={`${label(name)} symbols`}
        values={Object.entries(stage.symbols)} render={([symbol, reads]) => <><p className="font-semibold break-all">{symbol}</p><ReadValues reads={reads} /></>} />}
      {name === 'execution' && <PagedRecords name="executions" values={stage.executions} render={row => <>
        <p className="text-xs break-all">Execution {row.index}: {row.execution_id}; symbol: {row.symbol}</p>
        <p className="text-xs break-all">Book: {row.portfolio_id}; strategy: {row.strategy_name}; engine: {row.strategy_id}</p>
        <ReadValues reads={row.reads} />
      </>} />}
    </div>}
  </article>;
}
export function EquityRunConsumptionInspection({ consumption }: { consumption: EquityRunConsumption }) {
  return <section aria-label="Equity settings recorded for this run" className="min-w-0 w-full space-y-2">
    <h3 className="text-base font-semibold">Equity settings recorded for this run</h3>
    <p className="text-sm break-all">Book: {consumption.run_key.portfolio_id}; Run date: {consumption.run_key.date}</p>
    <p className="text-sm">Read coverage: {consumption.complete ? 'complete' : 'unavailable'}</p>
    {consumption.unavailable_reason && <p role="status" className="text-sm">Reason: {label(consumption.unavailable_reason)}</p>}
    <p className="text-xs">Coverage describes recorded reads for this dated run. It does not establish investor report readiness, current holdings, activation, or financial correctness.</p>
    {Object.entries(consumption.stages).map(([name, stage]) => <Stage key={name} name={name} stage={stage} />)}
  </section>;
}

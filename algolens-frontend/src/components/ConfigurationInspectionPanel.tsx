import React, { useEffect, useState } from 'react';
import { ChevronDown, FileCheck2 } from 'lucide-react';
import type { InspectionField, InspectionResponse, TrendStage } from '../domain/portfolio/configurationInspection';
import { UnsupportedNumericRepresentationError } from '../domain/portfolio/configurationInspection';
import { getConfigurationInspection } from '../infrastructure/api/configurationInspectionApi';
import { useTheme } from '../adapters/react/ThemeContext';
import { counted } from '../domain/text/pluralize';
import { ConsumptionInspection } from './ConsumptionInspection';
import { EquityRunConsumptionInspection } from './EquityRunConsumptionInspection';

type Props = { registryId: string; portfolioId: string; userId?: string; allowed: boolean };
type View = { kind: 'loading' } | { kind: 'error'; message: string } |
  { kind: 'ready'; response: InspectionResponse };

const showValue = (value: unknown, state?: string): string => {
  if (state === 'omitted') return 'Omitted';
  if (state === 'absent_in_input') return 'Absent in input';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number' || typeof value === 'string') return String(value);
  return JSON.stringify(value) ?? '—';
};
const reasonLabels: Record<string, string> = {
  not_published: 'No published configuration for this book.',
  legacy_publication: 'No published configuration in this older publication.',
  unsupported_publication: 'This publication version is unavailable.',
  invalid_publication: 'This publication could not be inspected.',
  publication_date_mismatch: 'This publication date could not be verified.',
  scope_changed: 'This publication no longer matches the selected scope.',
  projection_invalid: 'Supplied configuration inspection was unavailable.',
  selected_stage_unavailable: 'Selected trend stages were unavailable.',
  capture_failed: 'Configuration capture was unavailable.',
};

function FieldTable({ fields }: { fields: InspectionField[] }) {
  return <div role="region" aria-label="Supplied inputs table" tabIndex={0}
    className="w-full max-w-full min-w-0 overflow-x-auto overscroll-x-contain focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
    <table className="min-w-[1120px] table-fixed text-left text-xs border-collapse">
      <caption className="text-left text-sm font-semibold py-2">Supplied inputs</caption>
      <colgroup><col className="w-[220px]" /><col className="w-[190px]" />
        <col className="w-[130px]" /><col className="w-[160px]" />
        <col className="w-[190px]" /><col className="w-[230px]" /></colgroup>
      <thead><tr className="border-b border-gray-300 dark:border-gray-700">
        <th scope="col" className="p-2">Path</th><th scope="col" className="p-2">Supplied value</th>
        <th scope="col" className="p-2">State</th><th scope="col" className="p-2">Unit</th>
        <th scope="col" className="p-2">Classification</th><th scope="col" className="p-2">Condition / reason</th>
      </tr></thead>
      <tbody>{fields.map(field => <tr key={field.path} className="border-b border-gray-200 dark:border-gray-800 align-top">
        <th scope="row" className="p-2 font-mono break-all">{field.path}</th>
        <td className="p-2 break-all">{showValue(field.value, field.value_state)}</td>
        <td className="p-2 break-all">{field.value_state}</td>
        <td className="p-2 break-all">{field.unit}</td>
        <td className="p-2 break-all">{field.classification}</td>
        <td className="p-2 break-all">{field.condition} / {field.reason}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}

function StageTable({ title, stage }: { title: string; stage: TrendStage }) {
  const units: Record<string, string> = {
    weight: 'multiplier', risk_target: 'annualized_volatility_fraction', fx_rate: 'currency_ratio',
    idm: 'multiplier', max_symbol_concentration: 'fraction', use_position_buffering: 'flag',
    carver_buffer_floor: 'contracts', carver_buffer_position_factor: 'fraction',
    ema_windows: 'short_long_bar_pairs', vol_lookback_short: 'bar_windows',
    vol_lookback_long: 'bar_windows', max_history_size: 'bar_records',
    fdm: 'rule_count_multiplier_pairs',
  };
  return <div role="region" aria-label={`${title} table`} tabIndex={0}
    className="w-full max-w-full min-w-0 overflow-x-auto overscroll-x-contain focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
    <table className="min-w-[660px] table-fixed text-left text-xs border-collapse">
      <caption className="text-left text-sm font-semibold py-2">{title}</caption>
      <colgroup><col className="w-[220px]" /><col className="w-[240px]" />
        <col className="w-[200px]" /></colgroup>
      <thead><tr className="border-b border-gray-300 dark:border-gray-700">
        <th scope="col" className="p-2">Trend input</th><th scope="col" className="p-2">Value</th>
        <th scope="col" className="p-2">Unit</th>
      </tr></thead>
      <tbody>{Object.entries(stage).map(([name, value]) =>
        <tr key={name} className="border-b border-gray-200 dark:border-gray-800">
          <th scope="row" className="p-2 font-mono break-all">{name}</th>
          <td className="p-2 break-all">{showValue(value)}</td>
          <td className="p-2 break-all">{units[name]}</td>
        </tr>)}</tbody>
    </table>
  </div>;
}

function Observation({ response }: { response: InspectionResponse }) {
  const publication = response.publication;
  if (!publication) {
    return <p role="status">{reasonLabels[response.reason] ?? 'No published configuration is available.'}</p>;
  }
  const identity = publication.identity;
  const ageMinutes = Math.max(0, Math.floor((Date.now() - Date.parse(publication.captured_at)) / 60000));
  const age = ageMinutes < 60 ? counted(ageMinutes, 'minute')
    : ageMinutes < 1440 ? counted(Math.floor(ageMinutes / 60), 'hour')
      : counted(Math.floor(ageMinutes / 1440), 'day');
  const selected = publication.selected_trend;
  const source = publication.configuration_selection;
  const composite = 'equity_multi_consumption' in publication ? publication.equity_multi_consumption : undefined;
  return <div className="space-y-5">
    <div className="text-sm space-y-1" aria-label="Completed configuration summary">
      <p>Completed run: <time dateTime={identity.run_date}>{identity.run_date}</time></p>
      <p>{!source ? 'Settings source and approved version were not recorded.' : source.source === 'file' ? 'File settings' : 'Approved configuration'}</p>
      {source?.version_id && <p>Approved version: <span className="font-mono">{source.version_id}</span></p>}
      {composite ? <>
        <p>{composite.coverage.primary === 'observed' ? 'Primary strategy and portfolio observations collected.' : 'Primary invocation skipped: non-trading day.'}</p>
        <p>Full run stages and account execution costs: Not collected. This does not mean unused or failed.</p>
      </> : <p>{publication.publication_schema_version === 1 ? 'Runtime observations: Not collected.' : 'Recorded runtime observations are available in the details, including any skipped or unavailable stages.'}</p>}
      <p>This summary describes the completed publication, not current active settings or an in-flight run.</p>
    </div>
    <details><summary className="cursor-pointer font-medium">Configuration and observation details</summary>
    <div className="space-y-5 mt-3">
    <div className="text-sm space-y-1">
      <p>Run date: {identity.run_date}</p>
      <p>Captured: <time dateTime={publication.captured_at}>{publication.captured_at}</time> UTC</p>
      <p>Publication recorded: <time dateTime={publication.publication_recorded_at}>{publication.publication_recorded_at}</time> UTC</p>
      <p>Read: <time dateTime={response.read_at}>{response.read_at}</time> UTC</p>
      <p>Observation age: {age}. This is a dated system publication, not a current running state.</p>
      <p>Build label: <span className="font-mono">{identity.producer_version}</span></p>
      <p>{identity.control_mode === 'controlled' ? 'Controlled publication' : 'Uncontrolled publication'}</p>
      {publication.publication_schema_version === 1 &&
        <p>Consumption not collected. Supplied inputs and selected trend stages do not prove a value was read during the run.</p>}
      <p>Read only. Supplied settings do not by themselves prove runtime use.</p>
    </div>
    {response.status === 'unavailable' &&
      <p role="status">{reasonLabels[response.reason] ?? 'No published configuration is available.'}</p>}
    {response.status === 'available' && (publication.publication_schema_version === 1 || publication.publication_schema_version === 2) && publication.supplied && selected && <>
    <FieldTable fields={publication.supplied.fields} />
    <div>
      <h3 className="text-base font-semibold">Selected trend stages</h3>
      <p className="text-xs">Shared resolver with the same inputs, followed by constructor normalization. Other runtime transformations are not shown.</p>
      <p className="text-xs">Slow concentration override: {selected.slow_concentration_override.state === 'absent'
        ? 'Absent' : `Present: ${selected.slow_concentration_override.value} fraction`}</p>
      {selected.strategies.length === 0 && <p>No selected known trend strategies were captured.</p>}
      {selected.strategies.map((strategy, index) => <div key={strategy.strategy_id} className="mt-4 border-t border-gray-300 dark:border-gray-700">
        <h4 className="font-medium break-all">#{index + 1} {strategy.strategy_id} — {strategy.strategy_type}</h4>
        <p className="text-xs">Selected allocation: {strategy.selected_allocation} fraction</p>
        <StageTable title="Factory-resolved trend inputs" stage={strategy.factory_resolved} />
        <StageTable title="Constructor-normalized trend inputs" stage={strategy.constructor_normalized} />
      </div>)}
    </div>
    </>}
    {(publication.publication_schema_version === 2 || publication.publication_schema_version === 4) && publication.consumption &&
      <ConsumptionInspection key={publication.identity.publication_id} consumption={publication.consumption} />}
    {(publication.publication_schema_version === 3 || publication.publication_schema_version === 5) && publication.equity_run_consumption &&
      <EquityRunConsumptionInspection key={publication.identity.publication_id} consumption={publication.equity_run_consumption} />}
    {(publication.publication_schema_version === 4 || publication.publication_schema_version === 5) && <>
      <h3 className="font-semibold">Supplied settings</h3>
      <p className="text-xs">Complete recorded settings. Consumption evidence for supplied values is not collected; use the observations above to inspect actual reads.</p>
      <div role="region" aria-label="Supplied settings" tabIndex={0} className="overflow-x-auto">
      <table className="text-xs text-left"><thead><tr><th>Setting</th><th>Value</th><th>Classification</th><th>Consumer</th></tr></thead>
        <tbody>{publication.supplied.fields.map(field => <tr key={field.path}>
          <th className="p-2 font-mono break-all">{field.path}</th><td className="p-2 break-all">{showValue(field.value)}</td>
          <td className="p-2">{field.classification}</td><td className="p-2">{field.consumer}</td>
        </tr>)}</tbody></table>
      </div>
      <p className="break-all">Baseline hash: {source?.base_sha256}</p>
      <p className="break-all">Effective hash: {source?.effective_sha256}</p>
      {composite && <details><summary>Primary invocation observations</summary><pre className="overflow-auto text-xs">{JSON.stringify(composite, null, 2)}</pre></details>}
    </>}
    </div></details>
  </div>;
}

function ScopedPanel({ registryId, portfolioId }: Pick<Props, 'registryId' | 'portfolioId'>) {
  const { theme } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [view, setView] = useState<View>({ kind: 'loading' });
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setView({ kind: 'loading' });
    void getConfigurationInspection(registryId, portfolioId, controller.signal).then(
      response => { if (current) setView({ kind: 'ready', response }); },
      error => {
        if (current) setView({ kind: 'error', message: error instanceof UnsupportedNumericRepresentationError
          ? error.message : 'Published configuration could not be loaded.' });
      },
    );
    return () => { current = false; controller.abort(); };
  }, [registryId, portfolioId, refresh]);
  const color = theme === 'dark'
    ? 'border-gray-700 bg-gray-900 text-gray-200 shadow-black/20'
    : 'border-gray-200 bg-white text-gray-800 shadow-gray-200/70';
  const muted = theme === 'dark' ? 'text-gray-400' : 'text-gray-500';
  const hover = theme === 'dark' ? 'hover:bg-gray-800/70' : 'hover:bg-gray-50';
  const badge = theme === 'dark'
    ? 'border-gray-700 bg-gray-800 text-gray-300'
    : 'border-gray-200 bg-gray-50 text-gray-600';
  return <section aria-label="Published configuration"
    className={`my-6 min-w-0 overflow-hidden rounded-xl border shadow-sm ${color}`}>
    <button type="button" aria-expanded={expanded} aria-controls="published-configuration-body"
      onClick={() => setExpanded(value => !value)}
      className={`group flex w-full items-start justify-between gap-4 px-4 py-4 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 ${hover}`}>
      <span className="flex min-w-0 items-start gap-3">
        <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border ${badge}`}>
          <FileCheck2 aria-hidden="true" className="h-4 w-4" />
        </span>
        <span className="min-w-0">
          <span className="flex items-center gap-1.5 font-semibold">
            Published configuration
            <ChevronDown aria-hidden="true"
              className={`h-4 w-4 shrink-0 transition-transform duration-200 ${expanded ? 'rotate-180' : ''}`} />
          </span>
          <span className={`mt-0.5 block text-xs font-normal ${muted}`}>
            Engine-recorded settings for this book
          </span>
          <span className="mt-2 flex flex-wrap gap-1.5 text-xs font-normal">
            <span className={`rounded-full border px-2 py-0.5 ${badge}`}>Registry: {registryId}</span>
            <span className={`max-w-full truncate rounded-full border px-2 py-0.5 ${badge}`}>Book: {portfolioId}</span>
          </span>
        </span>
      </span>
      <span className={`mt-1 shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide ${badge}`}>
        Read only
      </span>
    </button>
    {expanded && <div id="published-configuration-body"
      className={`border-t px-4 pb-4 pt-4 ${theme === 'dark' ? 'border-gray-700' : 'border-gray-200'}`}>
      <button type="button" onClick={() => {
        setView({ kind: 'loading' });
        setRefresh(value => value + 1);
      }} className={`mb-4 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${badge} ${hover}`}>
        Refresh published configuration
      </button>
      {view.kind === 'loading' && <p role="status">Loading published configuration…</p>}
      {view.kind === 'error' && <p role="alert">{view.message}</p>}
      {view.kind === 'ready' && <Observation response={view.response} />}
    </div>}
  </section>;
}

export function ConfigurationInspectionPanel({ registryId, portfolioId, userId, allowed }: Props) {
  if (!allowed || !registryId || !portfolioId) return null;
  // A changed identity gets a new instance in the same render, before effect cleanup.
  return <ScopedPanel key={JSON.stringify([registryId, portfolioId, userId, allowed])}
    registryId={registryId} portfolioId={portfolioId} />;
}

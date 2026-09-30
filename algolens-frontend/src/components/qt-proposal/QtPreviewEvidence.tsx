import type { QtPreview } from '../../domain/portfolio/qtPreview';
import { qtStyles, useQtDark } from './qtStyles';

function traceScalar(trace: string[], prefix: string): string | null {
  const matches = trace.filter(value => value.startsWith(prefix));
  return matches.length === 1 ? matches[0].slice(prefix.length) : null;
}

function actualIterations(trace: string[]): string | null {
  const value = traceScalar(trace, 'actual_iterations=');
  return value !== null && /^(0|[1-9]\d*)$/.test(value) && Number(value) <= 2147483647 ? value : null;
}

function diagnostic(value: unknown): value is string {
  return typeof value === 'string' && value.length <= 128 &&
    /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) && Number.isFinite(Number(value));
}

function bufferTrace(trace: string[]): { buffer_branch: string; solver_positions: string[] | null;
  continuous_buffered_positions: string[] | null; rounded_buffered_positions: string[] | null } | null {
  const records = trace.filter(value => value.startsWith('{'));
  if (records.length !== 1) return null;
  try {
    const value: unknown = JSON.parse(records[0]);
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
    const item = value as Record<string, unknown>;
    if (typeof item.buffer_branch !== 'string' ||
        !['not_reached', 'disabled', 'returned_prior', 'applied', 'failed'].includes(item.buffer_branch)) return null;
    const vector = (values: unknown): values is string[] | null => values === null ||
      (Array.isArray(values) && values.every(diagnostic));
    if (!vector(item.solver_positions) || !vector(item.continuous_buffered_positions) ||
        !vector(item.rounded_buffered_positions)) return null;
    return { buffer_branch: item.buffer_branch, solver_positions: item.solver_positions,
      continuous_buffered_positions: item.continuous_buffered_positions,
      rounded_buffered_positions: item.rounded_buffered_positions };
  } catch { return null; }
}

export function QtPreviewEvidence({ preview }: { preview: QtPreview }) {
  const ui = qtStyles(useQtDark());
  const sub = `space-y-2 rounded-lg border p-3 ${ui.border}`;
  const { optimizer, selected_risk: risk, selected_costs: costs } = preview.evaluation;
  const evaluated = optimizer.status === 'evaluated';
  const iterations = evaluated ? actualIterations(optimizer.trace) : null;
  const tracking = evaluated ? traceScalar(optimizer.trace, 'tracking_error=') : null;
  const buffer = evaluated ? bufferTrace(optimizer.trace) : null;
  const weight = (rows: typeof optimizer.current_weights, instrument: string, symbol: string) =>
    rows.find(row => row.instrument_type === instrument && row.symbol === symbol)?.weight_diagnostic ?? 'unavailable';
  return <section aria-label="QT preview evidence" className={ui.card}>
    <h3 className={ui.cardTitle}>Preview of my chosen quantities</h3>
    <p className={ui.callout(preview.availability === 'ready' && preview.confirmable ? 'success' : preview.availability === 'ready' ? 'warning' : 'danger')}>Evidence: {preview.availability}; confirmation {preview.confirmable ? 'available' : 'blocked'}.</p>
    {preview.unavailable_reasons.length > 0 && <p className={ui.callout('danger')}>Unavailable: {preview.unavailable_reasons.join(', ')}</p>}
    <section aria-label="Aggregate optimizer advice" className={sub}>
      <h4 className={ui.subTitle}>Aggregate optimizer advice</h4>
      <p className={ui.body}>Stage: {optimizer.status}. This advice is aggregate and does not change QT component quantities.</p>
      <p className={ui.body}>Actual optimizer iterations: {iterations ?? 'unavailable'}.</p>
      {evaluated && <>
        <p className={ui.body}>Tracking error: {diagnostic(tracking) ? tracking : 'unavailable'}; cost penalty: {optimizer.cost_penalty ?? 'unavailable'}.</p>
        {optimizer.solved_weights.length > 0 && <div className={ui.tableWrap}><table aria-label="Optimizer aggregate weights" className={`${ui.table} min-w-[480px]`}>
          <thead><tr><th className={ui.th}>Instrument</th><th className={ui.thRight}>Previous weight</th><th className={ui.thRight}>Proposed weight</th><th className={ui.thRight}>Solved weight</th></tr></thead>
          <tbody>{optimizer.solved_weights.map(row => <tr key={`${row.instrument_type}:${row.symbol}`} className={ui.tr}>
            <td className={ui.td}>{row.instrument_type} {row.symbol}</td>
            <td className={ui.tdNum}>{weight(optimizer.current_weights, row.instrument_type, row.symbol)}</td>
            <td className={ui.tdNum}>{weight(optimizer.target_weights, row.instrument_type, row.symbol)}</td>
            <td className={ui.tdNum}>{row.weight_diagnostic}</td>
          </tr>)}</tbody>
        </table></div>}
        {buffer && <>
          <p className={ui.body}>Buffer branch: {buffer.buffer_branch}.</p>
          <p className={`${ui.body} break-words`}>Solver weights: {buffer.solver_positions?.join(', ') ?? 'unavailable'}.</p>
          <p className={`${ui.body} break-words`}>Buffered weights before rounding: {buffer.continuous_buffered_positions?.join(', ') ?? 'unavailable'}.</p>
          <p className={`${ui.body} break-words`}>Buffered weights after rounding: {buffer.rounded_buffered_positions?.join(', ') ?? 'unavailable'}.</p>
        </>}
      </>}
      {optimizer.aggregate_bindings.map(binding => <p key={`${binding.instrument_type}:${binding.symbol}`} className={ui.body}>
        {binding.instrument_type} {binding.symbol}: previous net {binding.previous_net_quantity_exact};
        proposed net {binding.proposed_net_quantity_exact}; {binding.component_keys.length} owned components.
      </p>)}
      {optimizer.diagnostics.map((message, index) => <p key={index} className={ui.callout('warning')}>{message}</p>)}
    </section>
    <section aria-label="Selected book risk" className={sub}>
      <h4 className={ui.subTitle}>Selected book risk</h4>
      <p className={ui.badge(risk.status === 'evaluated' ? risk.passed ? 'success' : 'warning' : 'neutral')}>Stage: {risk.status}; {risk.status === 'evaluated' ? risk.passed ? 'passed' : 'known breach' : 'unavailable'}.</p>
      {risk.metrics.map((metric, index) => <p key={`${metric.code}:${index}`} className={`${ui.body} break-words`}>
        {metric.code}: {metric.value_diagnostic ?? 'unavailable'} {metric.unit}; source {metric.source_id ?? 'unavailable'}.
      </p>)}
      {risk.breaches.map((breach, index) => <p key={`${breach.code}:${index}`} className={ui.callout('danger')}>
        {breach.code}: actual {breach.actual_diagnostic ?? 'unavailable'}; limit {breach.limit_diagnostic ?? 'unavailable'}.
      </p>)}
      {risk.diagnostics.map((message, index) => <p key={index} className={ui.callout('warning')}>{message}</p>)}
    </section>
    <section aria-label="Selected book costs" className={sub}>
      <h4 className={ui.subTitle}>Selected book costs</h4>
      <p className={ui.body}>Stage: {costs.status}; estimated selected-book cost {costs.total_exact ?? 'unavailable'}.</p>
      {costs.by_component.map(component => <p key={JSON.stringify(component.key)} className={`${ui.body} break-words`}>
        {component.key.strategy_name} {component.key.symbol}: {component.prior_quantity_exact} to
        {component.selected_quantity_exact}; estimated cash cost {component.cash_cost_exact}; source {component.source_id ?? 'unavailable'}.
      </p>)}
      {costs.diagnostics.map((message, index) => <p key={index} className={ui.callout('warning')}>{message}</p>)}
    </section>
  </section>;
}

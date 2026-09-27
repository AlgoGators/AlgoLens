import React, { useId, useMemo, useState } from 'react';
import { CONSUMPTION_CATALOG } from '../domain/portfolio/consumptionCatalog';
import type { ConsumptionNode, ConsumptionRead, ConsumptionV2 } from '../domain/portfolio/consumptionInspection';

const NODE_PAGE = 25;
const READ_PAGE = 50;
const scrollClass = 'w-full max-w-full min-w-0 overflow-x-auto overscroll-x-contain focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500';

function recordedValue(value: ConsumptionRead['value']): string {
  // Fixed decimal values arrive as validated strings. Never pass them through Number.
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  return JSON.stringify(value);
}

function ReadTable({ node }: { node: ConsumptionNode }) {
  const [shown, setShown] = useState(READ_PAGE);
  if (node.reads.length === 0) return <p className="text-xs mt-2">No setting reads recorded for this observation. This does not prove that no setting was used.</p>;
  return <div className="mt-3 min-w-0">
    <p className="text-xs">Showing {Math.min(shown, node.reads.length)} of {node.reads.length} recorded reads.</p>
    <div role="region" aria-label={`Observation #${node.id} setting reads table`} tabIndex={0} className={scrollClass}>
      <table className="min-w-[720px] table-fixed text-left text-xs border-collapse">
        <caption className="text-left font-semibold py-2">Observation #{node.id} setting reads</caption>
        <colgroup><col className="w-[250px]" /><col className="w-[180px]" />
          <col className="w-[105px]" /><col className="w-[145px]" /><col className="w-[120px]" /></colgroup>
        <thead><tr className="border-b border-gray-300 dark:border-gray-700">
          <th scope="col" className="p-2">Field</th><th scope="col" className="p-2">Recorded value</th>
          <th scope="col" className="p-2">Value type</th><th scope="col" className="p-2">Origin</th>
          <th scope="col" className="p-2">Symbol</th>
        </tr></thead>
        <tbody>{node.reads.slice(0, shown).map((read, index) =>
          <tr key={`${read.field}:${read.symbol ?? ''}:${index}`} className="border-b border-gray-200 dark:border-gray-800 align-top">
            <th scope="row" className="p-2 font-mono break-all">{read.field}</th>
            <td className="p-2 font-mono break-all">{recordedValue(read.value)}</td>
            <td className="p-2 break-all">{read.value_type}</td>
            <td className="p-2 break-all">{read.origin}</td>
            <td className="p-2 break-all">{read.symbol ?? '—'}</td>
          </tr>)}</tbody>
      </table>
    </div>
    {shown < node.reads.length && <button type="button" onClick={() => setShown(count => Math.min(count + READ_PAGE, node.reads.length))}
      className="mt-2 rounded border border-gray-400 px-2 py-1 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
      Show more reads for observation #{node.id}
    </button>}
  </div>;
}

function NodeDetail({ node }: { node: ConsumptionNode }) {
  const [expanded, setExpanded] = useState(false);
  const bodyId = useId();
  return <article className="min-w-0 rounded border border-gray-300 p-3 dark:border-gray-700">
    <h5 className="font-medium text-sm break-all">
      <button type="button" aria-expanded={expanded} aria-controls={expanded ? bodyId : undefined} onClick={() => setExpanded(value => !value)}
        className="text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
        Observation #{node.id}: {node.consumer} ({node.kind}) {expanded ? '▾' : '▸'}
      </button>
    </h5>
    {expanded && <div id={bodyId} className="mt-2 min-w-0 space-y-1 text-xs break-all">
      <p>Parent observation: {node.parent === null ? 'root' : `#${node.parent}`}</p>
      <p>Consumer: {node.consumer}; {node.kind}{node.outcome ? `; outcome: ${node.outcome}` : ''}</p>
      {node.strategy !== undefined && <p>Strategy: {node.strategy}</p>}
      {node.symbol !== undefined && <p>Symbol: {node.symbol}</p>}
      {node.index !== undefined && <p>Index: {node.index}</p>}
      <div>
        <p className="font-semibold">Recorded metadata</p>
        {Object.entries(node.meta).length === 0 ? <p>None recorded.</p>
          : <dl className="space-y-1">{Object.entries(node.meta).map(([name, value]) =>
            <div key={name} className="flex flex-wrap gap-x-1"><dt className="font-mono">{name}:</dt><dd>{String(value)}</dd></div>)}</dl>}
      </div>
      <ReadTable node={node} />
    </div>}
  </article>;
}

function StageDetail({ stage, status, reason, nodes }: {
  stage: string; status: string; reason: string; nodes: ConsumptionNode[];
}) {
  const [expanded, setExpanded] = useState(false);
  const [shown, setShown] = useState(NODE_PAGE);
  const bodyId = useId();
  const label = stage.replaceAll('_', ' ');
  return <div className="min-w-0 border-t border-gray-300 py-3 dark:border-gray-700">
    <h4 className="font-semibold text-sm">
      <button type="button" aria-expanded={expanded} aria-controls={expanded ? bodyId : undefined} onClick={() => setExpanded(value => !value)}
        className="text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
        {expanded ? 'Hide' : 'Show'} {label} observations — {status} (reason: {reason})
      </button>
    </h4>
    <p className="text-xs">{nodes.length} recorded observations in {label}.</p>
    {expanded && <div id={bodyId} className="mt-2 min-w-0 space-y-3">
      <p className="text-xs">Showing {Math.min(shown, nodes.length)} of {nodes.length} observations.</p>
      {nodes.length === 0 && <p className="text-xs">No observations recorded for this stage; coverage is {status} (reason: {reason}).</p>}
      {nodes.slice(0, shown).map(node => <NodeDetail key={node.id} node={node} />)}
      {shown < nodes.length && <button type="button" onClick={() => setShown(count => Math.min(count + NODE_PAGE, nodes.length))}
        className="rounded border border-gray-400 px-2 py-1 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500">
        Show more {label} observations
      </button>}
    </div>}
  </div>;
}

export function ConsumptionInspection({ consumption }: { consumption: ConsumptionV2 }) {
  const byStage = useMemo(() => {
    const grouped = new Map<string, ConsumptionNode[]>(CONSUMPTION_CATALOG.stages.map(stage => [stage, []]));
    const catalogStage = new Map<string, string>(CONSUMPTION_CATALOG.consumers.map(row => [row.name, row.stage]));
    const stagesById = new Map<number, string>();
    for (const node of consumption.nodes) {
      const declared = catalogStage.get(node.consumer);
      const stage = declared === 'inherited' ? stagesById.get(node.parent!) : declared;
      if (!stage || !grouped.has(stage)) throw new Error('Validated consumption stage is unavailable.');
      stagesById.set(node.id, stage);
      grouped.get(stage)!.push(node);
    }
    return grouped;
  }, [consumption]);
  return <section aria-label="Settings actually used" className="min-w-0 w-full space-y-2">
    <h3 className="text-base font-semibold">Settings actually used</h3>
    <p className="text-sm">Coverage: {consumption.status}; reason: {consumption.reason}</p>
    <p className="text-xs">Recorded observations: {consumption.nodes.length}</p>
    <p className="text-xs">Coverage describes recorded reads in this instrumented profile for this dated publication. It does not establish current live state, all settings, successful trading, activation, or equity support.</p>
    <p className="text-xs">Observed reads are evidence of use, not proof of financial impact. Missing evidence is not proof that a setting was unused.</p>
    {consumption.status === 'unavailable' && consumption.nodes.length === 0 &&
      <p role="status" className="text-sm">No setting reads were recorded because consumption evidence is unavailable. Each stage below reports its own coverage reason.</p>}
    <div>{CONSUMPTION_CATALOG.stages.map(stage => {
      const coverage = consumption.coverage[stage];
      return <StageDetail key={stage} stage={stage} status={coverage.status} reason={coverage.reason}
        nodes={byStage.get(stage)!} />;
    })}</div>
  </section>;
}

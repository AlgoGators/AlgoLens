/** Closed validation of an already-parsed consumption v2 child. */
import { parseFixedDecimal8 } from '../numbers/fixedDecimal8';
import { CONSUMPTION_CATALOG } from './consumptionCatalog';

export type ConsumptionStatus = 'complete' | 'partial' | 'unavailable';
export type CoverageStatus = ConsumptionStatus | 'skipped';
export type ConsumptionReason = 'none' | 'non_trading_day' | 'nonfatal_error' |
  'incomplete_call' | 'unsupported_consumer' | 'instrumentation_missing' |
  'capacity_exceeded' | 'invalid_observed_value' | 'invalid_observed_identity';
export type ConsumptionOutcome = 'returned_ok' | 'returned_error' | 'threw' | 'incomplete';
export interface ConsumptionRead {
  field: string;
  value_type: string;
  value: unknown;
  origin: string;
  symbol?: string;
}
export interface ConsumptionNode {
  id: number;
  parent: number | null;
  kind: 'call' | 'scope';
  consumer: string;
  reads: ConsumptionRead[];
  meta: Record<string, string | boolean>;
  outcome?: ConsumptionOutcome;
  strategy?: string;
  symbol?: string;
  index?: number;
}
export interface ConsumptionV2 {
  version: 2;
  status: ConsumptionStatus;
  reason: ConsumptionReason;
  coverage: Record<string, { status: CoverageStatus; reason: ConsumptionReason }>;
  nodes: ConsumptionNode[];
}

export class ConsumptionProtocolError extends Error {
  readonly reason = 'invalid_consumption';
  constructor() {
    super('invalid_consumption');
    this.name = 'ConsumptionProtocolError';
  }
}

type ConsumerSpec = { name: string; kind: 'call' | 'scope'; stage: string; parents: readonly string[]; dimensions: readonly string[] };
type MetaSpec = { consumer: string; key: string; required: boolean; type: string };
type FieldSpec = { consumer: string; field: string; type: string; origins: readonly string[] };
type Catalog = {
  stages: readonly string[];
  statuses: Record<string, readonly string[]>;
  global_statuses: Record<string, readonly string[]>;
  limits: Record<string, number>;
  identity: { strategy: string; symbol: string };
  consumers: readonly ConsumerSpec[];
  metadata: readonly MetaSpec[];
  fields: readonly FieldSpec[];
};
const catalog = CONSUMPTION_CATALOG as unknown as Catalog;
const limit = catalog.limits;
const consumers = new Map(catalog.consumers.map(row => [row.name, row]));
const metadata = new Map<string, Map<string, MetaSpec>>();
const fields = new Map<string, Map<string, FieldSpec>>();
for (const row of catalog.metadata) {
  if (!metadata.has(row.consumer)) metadata.set(row.consumer, new Map());
  metadata.get(row.consumer)!.set(row.key, row);
}
for (const row of catalog.fields) {
  if (!fields.has(row.consumer)) fields.set(row.consumer, new Map());
  fields.get(row.consumer)!.set(row.field, row);
}
const strategyPattern = new RegExp(`^(?:${catalog.identity.strategy})$`);
const symbolPattern = new RegExp(`^(?:${catalog.identity.symbol})$`);
const priority = catalog.statuses.partial;
const symbolMapPrefixes = new Set([
  'strategy.sizing.symbol_limit.symbol', 'strategy.buffering.symbol_limit.symbol',
  'strategy.base_risk.trading_multiplier.symbol', 'strategy.position_limits.symbol',
]);
const singletonRoots = new Set([
  'setup.selector', 'setup.factory', 'runner.market_window', 'runner.market_fetch',
  'strategy.preparation', 'portfolio.primary', 'risk.diagnostics',
  'runner.non_trading_day', 'runner.benchmark',
]);
const uniquePerParent = new Set([
  'setup.controlled_validation', 'setup.ordinary_selection', 'strategy.history',
  'strategy.volatility', 'strategy.forecast', 'strategy.regime', 'strategy.sizing',
  'strategy.buffering', 'strategy.base_risk', 'strategy.position_limits',
  'portfolio.optimization', 'portfolio.symbol_collection',
  'portfolio.numeric_aggregation', 'portfolio.redistribution',
  'optimizer.primary', 'portfolio.risk', 'risk.primary', 'cost.estimate',
  'cost.history', 'cost.execution', 'setup.selection_entry', 'setup.factory_entry',
  'strategy.primary', 'portfolio.pass', 'portfolio.optimization_strategy',
  'portfolio.estimate', 'execution.batch', 'runner.pnl_finalization',
]);

function need(ok: unknown): asserts ok {
  if (!ok) throw new ConsumptionProtocolError();
}
function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
}
function array(value: unknown): value is unknown[] {
  return Array.isArray(value) && Object.getPrototypeOf(value) === Array.prototype;
}
function keys(value: unknown, required: readonly string[], optional: readonly string[] = []): asserts value is Record<string, unknown> {
  need(object(value));
  const names = Reflect.ownKeys(value);
  need(names.every(key => typeof key === 'string' && key.length <= limit.string_length));
  need(required.every(key => Object.hasOwn(value, key)) &&
    names.every(key => required.includes(key as string) || optional.includes(key as string)));
}
function integer(value: unknown, min: number, max: number): value is number {
  return typeof value === 'number' && Number.isFinite(value) && Number.isInteger(value) && value >= min && value <= max;
}
function number(value: unknown): value is number {
  // Finite binary64 does not imply safe-integer-only.
  return typeof value === 'number' && Number.isFinite(value);
}
function identity(value: unknown, pattern: RegExp): asserts value is string {
  need(typeof value === 'string' && value.length <= limit.identity_length && pattern.test(value));
}
function scalarString(value: unknown): value is string {
  return typeof value === 'string' && value.length <= limit.string_length;
}

/** Schema-aware fixed-depth admission, before indexes or serialization. */
function preflight(value: unknown): asserts value is ConsumptionV2 {
  keys(value, ['version', 'status', 'reason', 'coverage', 'nodes']);
  need(typeof value.version === 'number' && scalarString(value.status) && scalarString(value.reason));
  keys(value.coverage, catalog.stages);
  for (const stage of catalog.stages) {
    const row = value.coverage[stage];
    keys(row, ['status', 'reason']);
    need(scalarString(row.status) && scalarString(row.reason));
  }
  need(array(value.nodes) && value.nodes.length <= limit.nodes);
  let readCount = 0;
  let pairCount = 0;
  for (const node of value.nodes) {
    keys(node, ['id', 'parent', 'kind', 'consumer', 'reads', 'meta'], ['outcome', 'strategy', 'symbol', 'index']);
    for (const name of ['id', 'parent', 'index']) {
      if (Object.hasOwn(node, name)) need((name === 'parent' && node[name] === null) || typeof node[name] === 'number');
    }
    for (const name of ['kind', 'consumer', 'outcome', 'strategy', 'symbol']) {
      if (Object.hasOwn(node, name)) need(scalarString(node[name]));
    }
    need(object(node.meta) && Reflect.ownKeys(node.meta).length <= 5);
    for (const [key, member] of Object.entries(node.meta)) {
      need(key.length <= limit.string_length && (typeof member === 'boolean' || scalarString(member)));
    }
    need(array(node.reads) && node.reads.length <= limit.reads_per_node);
    readCount += node.reads.length;
    need(readCount <= limit.reads_total);
    for (const row of node.reads) {
      keys(row, ['field', 'value_type', 'value', 'origin'], ['symbol']);
      for (const name of ['field', 'value_type', 'origin', 'symbol']) {
        if (Object.hasOwn(row, name)) need(scalarString(row[name]));
      }
      if (['bool', 'number', 'int32', 'uint53'].includes(row.value_type as string)) {
        need(typeof row.value === (row.value_type === 'bool' ? 'boolean' : 'number'));
      } else if (['fixed_decimal8', 'benchmark_mode'].includes(row.value_type as string)) {
        need(scalarString(row.value));
      } else if (['int32_pairs', 'int32_number_pairs'].includes(row.value_type as string)) {
        need(array(row.value) && row.value.length <= limit.pairs_per_read);
        pairCount += row.value.length;
        need(pairCount <= limit.pairs_total);
        for (const pair of row.value) {
          need(array(pair) && pair.length === 2 && typeof pair[0] === 'number' && typeof pair[1] === 'number');
        }
      } else need(false);
    }
  }
}

function typed(value: unknown, kind: string, pairCount: { count: number }): void {
  switch (kind) {
    case 'bool': need(typeof value === 'boolean'); return;
    case 'number': need(number(value)); return;
    case 'int32': need(integer(value, -2147483648, 2147483647)); return;
    case 'uint53': need(integer(value, 0, Number.MAX_SAFE_INTEGER)); return;
    case 'fixed_decimal8': need(typeof value === 'string' && parseFixedDecimal8(value) === value); return;
    case 'benchmark_mode': need(value === 'live' || value === 'deferred'); return;
    case 'int32_pairs':
    case 'int32_number_pairs':
      need(array(value) && value.length <= limit.pairs_per_read);
      pairCount.count += value.length;
      need(pairCount.count <= limit.pairs_total);
      for (const pair of value) {
        need(array(pair) && pair.length === 2);
        typed(pair[0], 'int32', pairCount);
        typed(pair[1], kind === 'int32_pairs' ? 'int32' : 'number', pairCount);
      }
      return;
    default: need(false);
  }
}
function validateMeta(node: ConsumptionNode): void {
  const spec = metadata.get(node.consumer) ?? new Map<string, MetaSpec>();
  keys(node.meta, [...spec.values()].filter(row => row.required).map(row => row.key), [...spec.keys()]);
  for (const [key, value] of Object.entries(node.meta)) {
    const kind = spec.get(key)!.type;
    need(kind === 'bool' ? typeof value === 'boolean' : typeof value === 'string' && kind.slice(5).split(',').includes(value));
  }
}
function readRows(node: ConsumptionNode, pairCount: { count: number }, symbols: Set<string>): Map<string, ConsumptionRead> {
  const spec = fields.get(node.consumer) ?? new Map<string, FieldSpec>();
  const seen = new Set<string>();
  const found = new Map<string, ConsumptionRead>();
  const symbolMaps = new Map<string, Map<string, { present?: boolean; value?: unknown }>>();
  for (const row of node.reads) {
    const fieldSpec = spec.get(row.field);
    need(fieldSpec && row.value_type === fieldSpec.type && fieldSpec.origins.includes(row.origin));
    typed(row.value, fieldSpec.type, pairCount);
    const parts = row.field.split('.');
    const suffix = parts.at(-1)!;
    const prefix = parts.slice(0, -1).join('.');
    const mapField = symbolMapPrefixes.has(prefix) && (suffix === 'present' || suffix === 'value');
    if (Object.hasOwn(row, 'symbol')) {
      identity(row.symbol, symbolPattern);
      symbols.add(row.symbol);
      need(symbols.size <= limit.symbols && mapField);
      if (!symbolMaps.has(prefix)) symbolMaps.set(prefix, new Map());
      const entries = symbolMaps.get(prefix)!;
      if (!entries.has(row.symbol)) entries.set(row.symbol, {});
      entries.get(row.symbol)![suffix as 'present' | 'value'] = row.value as never;
    } else need(!mapField);
    const key = JSON.stringify([row.field, row.symbol ?? null]);
    need(!seen.has(key));
    seen.add(key);
    found.set(row.field, row);
  }
  for (const entries of symbolMaps.values()) {
    need(entries.size <= limit.collection_entries);
    for (const entry of entries.values()) need(typeof entry.present === 'boolean' && (entry.present || !Object.hasOwn(entry, 'value')));
  }
  return found;
}
function stageFor(node: ConsumptionNode, nodes: ConsumptionNode[]): string {
  const stage = consumers.get(node.consumer)!.stage;
  return stage === 'inherited' ? consumers.get(nodes[node.parent!].consumer)!.stage : stage;
}
function at(rows: Map<string, ConsumptionRead>, field: string): unknown {
  return rows.get(field)?.value;
}
function sameSet<T>(a: Set<T>, b: Set<T>): boolean {
  return a.size === b.size && [...a].every(item => b.has(item));
}
function minimumCause(causes: Set<string>): string | undefined {
  return priority.find(cause => causes.has(cause));
}

function relations(value: ConsumptionV2, found: Map<number, Map<string, ConsumptionRead>>,
  children: ConsumptionNode[][], stageNodes: Map<string, ConsumptionNode[]>, causes: Map<string, Set<string>>): void {
  const nodes = value.nodes;
  const byConsumer = new Map<string, ConsumptionNode[]>();
  for (const node of nodes) {
    if (!byConsumer.has(node.consumer)) byConsumer.set(node.consumer, []);
    byConsumer.get(node.consumer)!.push(node);
  }
  const all = (name: string) => byConsumer.get(name) ?? [];
  const only = (name: string) => all(name)[0];
  const selector = only('setup.selector');
  const factory = only('setup.factory');
  need(!factory || selector);
  need(!all('portfolio.registration').length || factory);
  need(!all('setup.controlled_validation').length || selector?.meta.mode === 'controlled');
  for (const entry of all('setup.selection_entry')) {
    const meta = entry.meta;
    const rows = found.get(entry.id)!;
    for (const [field, flag] of [
      ['setup.selection.enabled_live', 'enabled_live_read'],
      ['setup.selection.default_allocation', 'allocation_read'],
    ]) if (rows.has(field)) need(meta[flag] === true);
    need(!Object.hasOwn(meta, 'enabled_live_defaulted') || rows.has('setup.selection.enabled_live'));
    need(!Object.hasOwn(meta, 'allocation_defaulted') || rows.has('setup.selection.default_allocation'));
    const enabled = rows.get('setup.selection.enabled_live');
    if (enabled) {
      if (Object.hasOwn(meta, 'enabled_live_defaulted')) need(enabled.origin === (meta.enabled_live_defaulted ? 'code_default' : 'configured_strategy_leaf'));
      if (Object.hasOwn(meta, 'enabled_live_present')) need(enabled.origin === (meta.enabled_live_present ? 'configured_strategy_leaf' : 'code_default'));
      if (nodes[entry.parent!].consumer === 'setup.ordinary_selection') need(!Object.hasOwn(meta, 'enabled_live_defaulted'));
    }
    const allocation = rows.get('setup.selection.default_allocation');
    if (allocation && Object.hasOwn(meta, 'allocation_defaulted')) need(allocation.origin === (meta.allocation_defaulted ? 'code_default' : 'configured_strategy_leaf'));
    for (const [flag, read] of [['enabled_live_defaulted', 'enabled_live_read'], ['allocation_defaulted', 'allocation_read']]) {
      need(!meta[flag] || meta[read] === true);
    }
  }
  for (const entry of all('setup.factory_entry')) {
    const meta = entry.meta;
    need(meta.initialize === 'not_reached' || meta.construction === 'succeeded');
    need(meta.start === 'not_reached' || meta.initialize === 'succeeded');
    if (['construction', 'initialize', 'start'].some(key => meta[key] === 'failed')) causes.get('setup')!.add('nonfatal_error');
    else if (['construction', 'initialize', 'start'].some(key => meta[key] === 'attempted')) causes.get('setup')!.add('incomplete_call');
    if (meta.profile === 'unsupported') causes.get('setup')!.add('unsupported_consumer');
  }
  const registrations = all('portfolio.registration');
  const factoryStarted = new Set(all('setup.factory_entry').filter(n => n.meta.start === 'succeeded').map(n => n.strategy!));
  const registered = new Set(registrations.filter(n => n.outcome === 'returned_ok').map(n => n.strategy!));
  need([...registered].every(name => factoryStarted.has(name)));
  for (const name of ['strategy.preparation', 'strategy.primary', 'portfolio.optimization_strategy', 'execution.batch', 'cost.strategy_execution']) {
    need(all(name).every(node => registered.has(node.strategy!)));
  }
  const disabled = new Set(all('setup.selection_entry').filter(n => at(found.get(n.id)!, 'setup.selection.enabled_live') === false).map(n => n.strategy!));
  need([...all('setup.factory_entry'), ...registrations].every(n => !disabled.has(n.strategy!)));
  for (const node of registrations) {
    const rows = found.get(node.id)!;
    const get = (name: string) => at(rows, `portfolio.registration.${name}`);
    const initial = get('initial_allocation');
    const stored = get('stored_allocation');
    need(stored === undefined || (initial !== undefined && initial === stored));
    const minimum = get('min_allocation') as number | undefined;
    const maximum = get('max_allocation');
    need(maximum === undefined || minimum !== undefined);
    need(minimum === undefined || initial === undefined || (initial as number) >= minimum || maximum === undefined);
    const total = get('total_allocation') as number | undefined;
    if (total !== undefined && Object.hasOwn(node.meta, 'total_within_limit')) need(node.meta.total_within_limit === !(total > 1));
    for (const gate of ['optimization', 'risk']) {
      const requested = get(`requested_${gate}`);
      const rhs = get(`portfolio_${gate}`);
      const storedGate = get(`stored_${gate}`);
      need(requested !== false || rhs === undefined);
      need(rhs === undefined || requested === true);
      need(storedGate === undefined || requested !== undefined);
      need(storedGate === undefined || requested !== true || rhs !== undefined);
      need(storedGate === undefined || storedGate === Boolean(requested && rhs));
    }
  }
  for (const node of all('execution.history_update')) {
    if (!node.meta.cost_model_reached) need(children[node.id].length === 0 && !Object.hasOwn(node.meta, 'previous_close_source'));
    need(children[node.id].every(kid => kid.reads.length > 0));
  }
  for (const node of [...all('strategy.preparation'), ...all('strategy.primary')]) {
    const scopes = children[node.id].map(kid => kid.consumer);
    const profile = node.meta.profile;
    need(profile !== 'unsupported' || scopes.length === 0);
    need(profile !== 'base' || scopes.every(name => name === 'strategy.base_risk' || name === 'strategy.position_limits'));
    if (profile === 'unsupported') causes.get(stageFor(node, nodes))!.add('unsupported_consumer');
    for (const kid of children[node.id]) {
      if (kid.consumer === 'strategy.base_risk' || kid.consumer === 'strategy.position_limits') need(kid.meta.supported || kid.reads.length === 0);
      else need(kid.reads.length > 0);
    }
  }
  for (const node of all('portfolio.primary')) {
    if (node.meta.skip_execution_generation) need(children[node.id].every(kid => !['cost.strategy_execution', 'cost.compatibility_execution'].includes(kid.consumer)));
  }
  for (const node of all('portfolio.pass')) {
    const rows = found.get(node.id)!;
    for (const [gate, consumer] of [['portfolio.pass.use_optimization', 'portfolio.optimization'], ['portfolio.pass.use_risk_management', 'portfolio.risk']]) {
      const kids = children[node.id].filter(kid => kid.consumer === consumer);
      need(!kids.length || at(rows, gate) === true);
    }
  }
  for (const node of all('portfolio.optimization')) {
    if (node.meta.skip !== 'none') need(children[node.id].every(kid => kid.consumer !== 'optimizer.primary'));
    for (const kid of children[node.id]) {
      if (['portfolio.symbol_collection', 'portfolio.numeric_aggregation', 'portfolio.redistribution'].includes(kid.consumer)) {
        for (const part of children[kid.id]) {
          const rows = found.get(part.id)!;
          need(at(rows, 'portfolio.optimization.strategy.enabled') !== false || !rows.has('portfolio.optimization.strategy.allocation'));
        }
      }
    }
  }
  for (const node of all('portfolio.risk')) {
    if (node.meta.skip !== 'none' || node.meta.manager_source === 'absent') need(children[node.id].length === 0);
    if (children[node.id].length) {
      need(node.meta.manager_source === 'internal' || node.meta.manager_source === 'external');
      if (node.meta.manager_source === 'external') need(children[node.id][0].reads.every(row => row.origin === 'runtime_effective'));
    }
  }
  for (const node of all('optimizer.primary')) if (node.meta.buffer_branch === 'failed') causes.get('primary')!.add('nonfatal_error');
  for (const node of all('execution.batch')) {
    const state = node.meta.state;
    need((state === 'returned' && node.outcome === 'returned_ok') ||
      (['rejected_stream', 'invalid_argument'].includes(state as string) && node.outcome === 'returned_error') ||
      (state === 'entered' && (node.outcome === 'incomplete' || node.outcome === 'threw')));
    const attempts = children[node.id].filter(kid => kid.consumer === 'execution.attempt');
    need(attempts.every((kid, index) => kid.index === index));
    let removed = false;
    for (const attempt of attempts) {
      if (attempt.meta.branch === 'removed_position') removed = true;
      else need(!removed);
    }
    need(attempts.slice(0, -1).every(kid => kid.outcome === 'returned_ok'));
    need(state !== 'returned' || attempts.every(kid => kid.outcome === 'returned_ok'));
  }
  for (const node of all('execution.attempt')) {
    const meta = node.meta;
    need(meta.branch !== 'current_position' || meta.price_source !== 'previous_average_price');
    need(meta.branch !== 'removed_position' || meta.price_source !== 'current_average_price');
    need(!meta.returned || (meta.state === 'returned' && node.outcome === 'returned_ok'));
    need(meta.state !== 'returned' || meta.returned || node.outcome === 'incomplete');
    need(!['entered', 'cost_call_reached'].includes(meta.state as string) || ['incomplete', 'threw'].includes(node.outcome!));
    need(!['rejected_stream', 'rejected_id'].includes(meta.state as string) || (node.outcome === 'threw' && children[node.id].length === 0));
    need(['cost_call_reached', 'returned'].includes(meta.state as string) || children[node.id].length === 0);
    need(children[node.id].every(kid => kid.reads.length > 0 || Object.keys(kid.meta).length > 0));
  }
  for (const node of all('runner.pnl_finalization')) {
    const row = found.get(node.id)!.get('runner.pnl_finalization.strategy_allocation');
    if (row) need(row.origin === (node.meta.allocation_lookup === 'hit' ? 'selected_allocation' : 'code_default') && ['hit', 'fallback'].includes(node.meta.allocation_lookup as string));
  }
  const benchmark = only('runner.benchmark');
  if (benchmark) {
    const mode = at(found.get(benchmark.id)!, 'runner.benchmark.mode');
    const branch = benchmark.meta.branch;
    need(mode !== 'deferred' || branch === 'not_reached');
    need(mode !== 'live' || branch !== 'not_reached');
    if (branch === 'failed') causes.get('control_flow')!.add('nonfatal_error');
    else if (branch === 'attempted') causes.get('control_flow')!.add('incomplete_call');
  }
  const decision = only('runner.non_trading_day');
  const skipped = decision?.meta.skip_strategy_processing === true;
  for (const stage of ['preparation', 'primary']) {
    need((value.coverage[stage].status === 'skipped') === skipped);
    if (skipped) need(stageNodes.get(stage)!.length === 0);
  }
  for (const stage of catalog.stages) {
    const coverage = value.coverage[stage];
    if (coverage.status === 'unavailable') need(stageNodes.get(stage)!.length === 0);
    if (coverage.status === 'complete') need(causes.get(stage)!.size === 0);
  }
  if (value.coverage.setup.status === 'complete') {
    need(selector && factory && selector.outcome === 'returned_ok' && factory.outcome === 'returned_ok');
    need(sameSet(factoryStarted, registered));
  }
  if (value.coverage.market_input.status === 'complete') {
    const window = only('runner.market_window');
    const fetch = only('runner.market_fetch');
    need(window && found.get(window.id)!.has('runner.market_input.historical_days') && fetch?.outcome === 'returned_ok');
  }
  if (value.coverage.preparation.status === 'complete') need(only('strategy.preparation')?.outcome === 'returned_ok');
  if (value.coverage.primary.status === 'complete') {
    need(only('portfolio.primary')?.outcome === 'returned_ok');
    const calls = all('strategy.primary');
    need(calls.every(node => node.outcome === 'returned_ok'));
    need(sameSet(new Set(calls.map(n => n.strategy!)), registered));
  }
  if (value.coverage.execution.status === 'complete') {
    const batches = all('execution.batch');
    need(sameSet(new Set(batches.map(n => n.strategy!)), registered));
    need(batches.every(node => node.outcome === 'returned_ok'));
  }
  if (value.coverage.diagnostics.status === 'complete') need(only('risk.diagnostics')?.outcome === 'returned_ok');
  if (value.coverage.control_flow.status === 'complete') need(decision && benchmark && found.get(benchmark.id)!.has('runner.benchmark.mode'));
}

function validate(value: unknown): ConsumptionV2 {
  preflight(value);
  need(integer(value.version, 2, 2));
  need(catalog.global_statuses[value.status]?.includes(value.reason));
  for (const stage of catalog.stages) {
    const row = value.coverage[stage];
    need(catalog.statuses[row.status]?.includes(row.reason));
    need(row.status !== 'skipped' || stage === 'preparation' || stage === 'primary');
  }
  const nodes = value.nodes;
  if (value.status === 'unavailable') {
    need(nodes.length === 0 && catalog.stages.every(stage => value.coverage[stage].status === 'unavailable' && value.coverage[stage].reason === value.reason));
    return value;
  }
  need(catalog.stages.every(stage => value.coverage[stage].status !== 'unavailable' || ['instrumentation_missing', 'unsupported_consumer'].includes(value.coverage[stage].reason)));
  const children: ConsumptionNode[][] = nodes.map(() => []);
  const stageNodes = new Map(catalog.stages.map(stage => [stage, [] as ConsumptionNode[]]));
  const causes = new Map(catalog.stages.map(stage => [stage, new Set<string>()]));
  const found = new Map<number, Map<string, ConsumptionRead>>();
  const strategies = new Set<string>();
  const symbols = new Set<string>();
  const singletonSeen = new Set<string>();
  const seenNodes = new Set<string>();
  const collectionCounts = new Map<string, number>();
  const pairCount = { count: 0 };
  for (const [index, node] of nodes.entries()) {
    const spec = consumers.get(node.consumer);
    need(spec && integer(node.id, index, index) && node.kind === spec.kind);
    const parent = node.parent;
    if (parent === null) need(spec.parents.includes('ROOT'));
    else {
      need(integer(parent, 0, index - 1) && spec.parents.includes(nodes[parent].consumer));
      children[parent].push(node);
    }
    let depth = 1;
    for (let cursor = parent; cursor !== null; cursor = nodes[cursor].parent) depth++;
    need(depth <= limit.chain_depth);
    if (node.kind === 'call') need(['returned_ok', 'returned_error', 'threw', 'incomplete'].includes(node.outcome as string));
    else need(!Object.hasOwn(node, 'outcome'));
    for (const dimension of ['strategy', 'symbol', 'index'] as const) {
      need(Object.hasOwn(node, dimension) === spec.dimensions.includes(dimension));
      if (dimension === 'strategy' && node.strategy !== undefined) {
        identity(node.strategy, strategyPattern);
        strategies.add(node.strategy);
        need(strategies.size <= limit.strategies);
      } else if (dimension === 'symbol' && node.symbol !== undefined) {
        identity(node.symbol, symbolPattern);
        symbols.add(node.symbol);
        need(symbols.size <= limit.symbols);
      } else if (dimension === 'index' && node.index !== undefined) need(integer(node.index, 0, 4095));
    }
    for (let cursor = parent; cursor !== null; cursor = nodes[cursor].parent) {
      const ancestor = nodes[cursor];
      need(node.strategy === undefined || ancestor.strategy === undefined);
      need(node.symbol === undefined || ancestor.symbol === undefined);
      if (node.index !== undefined && ancestor.index !== undefined) {
        need(node.consumer === 'portfolio.estimate' && ancestor.consumer === 'portfolio.pass');
      }
    }
    const stage = stageFor(node, nodes);
    stageNodes.get(stage)!.push(node);
    if (singletonRoots.has(node.consumer)) {
      need(!singletonSeen.has(node.consumer));
      singletonSeen.add(node.consumer);
    }
    const key = JSON.stringify([node.consumer, parent, node.strategy ?? null, node.symbol ?? null, node.index ?? null]);
    if (uniquePerParent.has(node.consumer) || (node.consumer === 'portfolio.registration' && node.outcome === 'returned_ok')) {
      need(!seenNodes.has(key));
      seenNodes.add(key);
    }
    const collection = JSON.stringify([node.consumer, parent]);
    collectionCounts.set(collection, (collectionCounts.get(collection) ?? 0) + 1);
    need(collectionCounts.get(collection)! <= limit.collection_entries);
    if (node.consumer === 'portfolio.pass') need(node.index! < limit.passes);
    validateMeta(node);
    found.set(index, readRows(node, pairCount, symbols));
    if (node.kind === 'call') {
      const cause = node.outcome === 'incomplete' ? 'incomplete_call' :
        node.outcome === 'returned_error' || node.outcome === 'threw' ? 'nonfatal_error' : undefined;
      if (cause) causes.get(stage)!.add(cause);
    }
  }
  const passes = nodes.filter(node => node.consumer === 'portfolio.pass').map(node => node.index);
  need(passes.every((index, ordinal) => index === ordinal));
  for (const node of nodes.filter(node => node.consumer === 'portfolio.optimization')) {
    const estimates = children[node.id].filter(kid => kid.consumer === 'portfolio.estimate');
    need(estimates.every((kid, ordinal) => kid.index === ordinal));
  }
  relations(value, found, children, stageNodes, causes);
  for (const stage of catalog.stages) {
    const row = value.coverage[stage];
    const observed = minimumCause(causes.get(stage)!);
    if (row.status === 'partial') need(observed === undefined || priority.indexOf(row.reason) <= priority.indexOf(observed));
    else if (row.status === 'complete') need(observed === undefined);
    else if (row.status === 'skipped') need(stageNodes.get(stage)!.length === 0);
  }
  if (value.status === 'complete') need(catalog.stages.every(stage => ['complete', 'skipped'].includes(value.coverage[stage].status)));
  else {
    need(nodes.some(node => node.kind === 'call'));
    const reported = catalog.stages.filter(stage => ['partial', 'unavailable'].includes(value.coverage[stage].status)).map(stage => value.coverage[stage].reason);
    need(reported.length > 0 && value.reason === priority.find(reason => (reported as string[]).includes(reason)));
  }
  // Parsed reserialization cannot recover raw numeric spelling, underflow or duplicate keys.
  // A child below the cap does not prove the combined publication fits.
  const encoded = JSON.stringify(value);
  need(typeof encoded === 'string' && new TextEncoder().encode(encoded).byteLength <= limit.bytes);
  return value;
}

export function validateConsumptionV2(value: unknown): ConsumptionV2 {
  try {
    return validate(value);
  } catch {
    throw new ConsumptionProtocolError();
  }
}

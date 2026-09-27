import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { describe, expect, it } from 'vitest';
import { CONSUMPTION_CATALOG } from './consumptionCatalog';
import { ConsumptionProtocolError, validateConsumptionV2 } from './consumptionInspection';

type Mutable = Record<string, any>;
const cases = JSON.parse(readFileSync(new URL('../../../../contracts/consumption-v2-cases.json', import.meta.url), 'utf8')) as {
  accepted: Record<string, Mutable>;
  rejected: Mutable[];
};
const sharedCatalog = JSON.parse(readFileSync(new URL('../../../../contracts/consumption-v2-catalog.json', import.meta.url), 'utf8'));
const clone = <T>(value: T): T => structuredClone(value);
const ordinary = () => clone(cases.accepted.ordinary);
const rich = () => clone(cases.accepted.rich);
const equityConsumers = ['cost.estimate', 'cost.strategy_execution', 'cost.compatibility_execution', 'cost.execution'];
const equityFields = [
  ['cost.spread.tick_constrained', 'bool', false],
  ['cost.charge.commission_per_unit', 'number', -1.125],
  ['cost.charge.max_commission_pct', 'number', -2.25],
  ['cost.charge.max_commission_per_order', 'number', -3.375],
  ['cost.charge.min_commission_per_order', 'number', -4.5],
  ['cost.charge.apply_regulatory_fees', 'bool', false],
  ['cost.charge.sec_fee_per_million', 'number', -5.625],
  ['cost.charge.finra_taf_per_share', 'number', -6.75],
  ['cost.charge.finra_taf_cap_per_trade', 'number', -7.875],
  ['cost.charge.max_total_implicit_bps', 'number', -8.125],
] as const;
function locate(value: any, path: string): [any, string | number] {
  const parts = path.split('.');
  for (const part of parts.slice(0, -1)) value = Array.isArray(value) ? value[Number(part)] : value[part];
  const last = parts.at(-1)!;
  return [value, Array.isArray(value) ? Number(last) : last];
}
function reject(value: unknown): void {
  try {
    validateConsumptionV2(value);
    throw new Error('accepted malformed consumption');
  } catch (error) {
    expect(error).toBeInstanceOf(ConsumptionProtocolError);
    expect((error as ConsumptionProtocolError).reason).toBe('invalid_consumption');
    expect((error as Error).message).toBe('invalid_consumption');
  }
}
function setPath(child: any, path: string, value: unknown): void {
  const [parent, key] = locate(child, path);
  parent[key] = value;
}
function appendNode(child: Mutable, node: Mutable): number {
  const id = child.nodes.length;
  child.nodes.push({ id, ...node });
  return id;
}

describe('consumption v2 parsed-child protocol', () => {
  it('preserves the exact native equity cost artifact from a synthetic run projection context', () => {
    const bytes = readFileSync(new URL('../../../../contracts/consumption-v2-equity-native.json', import.meta.url));
    expect(createHash('sha256').update(bytes).digest('hex')).toBe('2ac342468114aecbdbebac97a82892d57617760d70ce75b66b1bf06f232d2e9d');
    const child = JSON.parse(bytes.toString('utf8')) as Mutable;
    const before = clone(child);
    expect(validateConsumptionV2(child)).toBe(child);
    const expected = {
      'cost.spread.tick_constrained': true,
      'cost.charge.commission_per_unit': 0.0035,
      'cost.charge.max_commission_pct': -1,
      'cost.charge.max_commission_per_order': 98765,
      'cost.charge.min_commission_per_order': 0.35,
      'cost.charge.apply_regulatory_fees': true,
      'cost.charge.sec_fee_per_million': 20.6,
      'cost.charge.finra_taf_per_share': 0.000195,
      'cost.charge.finra_taf_cap_per_trade': 9.79,
      'cost.charge.max_total_implicit_bps': 123,
    };
    for (const consumer of equityConsumers) {
      const nodes = child.nodes.filter((node: Mutable) => node.consumer === consumer);
      expect(nodes).toHaveLength(1);
      for (const [field, value] of Object.entries(expected)) {
        expect(nodes[0].reads.find((row: Mutable) => row.field === field)).toEqual({
          field, value_type: typeof value === 'boolean' ? 'bool' : 'number', value, origin: 'runtime_effective',
        });
      }
      expect(nodes[0].reads.some((row: Mutable) => row.field === 'cost.charge.explicit_fee_per_contract')).toBe(false);
      expect(nodes[0].reads.some((row: Mutable) => row.field.startsWith('cost.volatility.'))).toBe(false);
    }
    expect(validateConsumptionV2(child)).toBe(child);
    expect(child).toEqual(before);
  });

  it('reconciles the full static runtime catalog with the frozen shared JSON', () => {
    expect(CONSUMPTION_CATALOG).toEqual(sharedCatalog);
    expect(sharedCatalog.consumers).toHaveLength(42);
    expect(sharedCatalog.fields).toHaveLength(182);
    const covered = new Set(Object.values(cases.accepted).flatMap(child => child.nodes.map((node: Mutable) => node.consumer)));
    expect(covered).toEqual(new Set((sharedCatalog.consumers as Mutable[]).map(row => row.name)));
  });

  it.each(equityConsumers.flatMap(consumer => equityFields.map(([field, type, value]) =>
    [consumer, field, type, value] as const)))(
    'preserves synthetic equity read %s:%s exactly', (consumer, field, type, value) => {
      const child = rich();
      const node = child.nodes.find((item: Mutable) => item.consumer === consumer);
      expect(node).toBeDefined();
      node.reads.push({ field, value_type: type, value, origin: 'runtime_effective' });
      const before = clone(child);
      expect(validateConsumptionV2(child)).toBe(child);
      expect(child).toEqual(before);
      expect(node.reads.at(-1).value).toBe(value);
      expect(validateConsumptionV2(child)).toBe(child);
      expect(child).toEqual(before);
    },
  );

  it.each(Object.keys(cases.accepted))('returns unchanged synthetic shared case %s twice', name => {
    const child = clone(cases.accepted[name]);
    const before = clone(child);
    expect(validateConsumptionV2(child)).toBe(child);
    expect(child).toEqual(before);
    expect(validateConsumptionV2(child)).toBe(child);
  });

  it.each(cases.rejected.map(c => [c.name, c] as const))('rejects shared mutation %s', (_name, mutation) => {
    const child = clone(cases.accepted[mutation.base]);
    if (mutation.path) setPath(child, mutation.path, mutation.value);
    else {
      const [target, key] = locate(child, mutation.append_to);
      target[key].push(clone(mutation.item));
    }
    reject(child);
  });

  it('uses a fixed sanitized rejection', () => {
    reject(null);
    reject({ secret: 'DO-NOT-ECHO' });
    const child = ordinary();
    child.nodes[0].meta.mode = 'SECRET-CONFIG-NAME';
    const before = clone(child);
    reject(child);
    expect(child).toEqual(before);
  });

  it.each((sharedCatalog.fields as Mutable[]).map((spec): [string, Mutable] => [spec.consumer + ':' + spec.field, spec]))(
    'accepts field in its declared real consumer context %s', (_name, spec) => {
      const child = clone(cases.accepted[spec.consumer === 'setup.controlled_validation' ? 'controlled' : 'rich']);
      const node = child.nodes.find((item: Mutable) => item.consumer === spec.consumer);
      expect(node).toBeDefined();
      if (!node.reads.some((item: Mutable) => item.field === spec.field)) {
        let value: any = spec.type === 'bool' ? true :
          spec.type === 'fixed_decimal8' ? '1.25' :
          spec.type === 'benchmark_mode' ? 'deferred' :
          spec.type.includes('pairs') ? [] : 1;
        let origin = spec.consumer === 'risk.primary' ? 'runtime_effective' : spec.origins[0];
        if (spec.field === 'portfolio.registration.min_allocation') value = 0.1;
        if (spec.field === 'portfolio.registration.max_allocation') {
          node.reads.push({ field: 'portfolio.registration.min_allocation', value_type: 'number', value: 0.1, origin: 'app_config_effective' });
        }
        if (spec.field.startsWith('portfolio.registration.portfolio_') ||
          (spec.field.startsWith('portfolio.registration.stored_') && spec.field !== 'portfolio.registration.stored_allocation')) {
          const gate = spec.field.endsWith('optimization') ? 'optimization' : 'risk';
          node.reads.push({ field: 'portfolio.registration.requested_' + gate, value_type: 'bool', value: true, origin: 'app_config_effective' });
          if (spec.field.startsWith('portfolio.registration.stored_')) {
            node.reads.push({ field: 'portfolio.registration.portfolio_' + gate, value_type: 'bool', value: true, origin: 'app_config_effective' });
          }
        }
        const row: Mutable = { field: spec.field, value_type: spec.type, value, origin };
        if (spec.field.includes('.symbol.')) {
          row.symbol = 'YM';
          if (spec.field.endsWith('.value')) {
            node.reads.push({ field: spec.field.slice(0, -5) + 'present', value_type: 'bool', value: true, origin: 'runtime_effective', symbol: 'YM' });
          }
        }
        node.reads.push(row);
      }
      expect(validateConsumptionV2(child)).toBe(child);
    },
  );

  it.each([
    ['nodes.0.outcome', 'incomplete'], ['nodes.0.meta.mode', 'secret/path'],
    ['nodes.2.meta.enabled_live_read', false], ['nodes.2.reads.0.origin', 'code_default'],
    ['nodes.4.meta.initialize', 'attempted'], ['nodes.5.reads.1.value', 0.6],
    ['nodes.8.meta.cost_model_reached', false], ['nodes.10.meta.profile', 'unsupported'],
    ['nodes.13.index', 1], ['nodes.14.meta.state', 'rejected_stream'],
    ['nodes.17.meta.branch', 'succeeded'], ['coverage.primary.reason', 'incomplete_call'],
  ])('rejects ordinary semantic contradiction at %s', (path, value) => {
    const child = ordinary();
    setPath(child, path, value);
    reject(child);
  });

  it.each([
    ['nodes.18.parent', 11], ['nodes.18.strategy', 'ALPHA'],
    ['nodes.34.symbol', 'ES'], ['nodes.26.index', 0],
    ['nodes.38.reads.0.origin', 'app_config_effective'],
    ['nodes.37.reads.0.origin', 'derived'],
    ['nodes.18.reads.1.value', [[1, 2.5]]],
    ['nodes.24.reads.1.value', false],
    ['nodes.33.index', 1], ['nodes.40.meta.state', 'rejected_id'],
  ])('rejects rich semantic contradiction at %s', (path, value) => {
    const child = rich();
    setPath(child, path, value);
    reject(child);
  });

  it('preserves nested failure and benchmark failure in stage/global precedence', () => {
    const child = rich();
    child.nodes[34].outcome = 'returned_error';
    reject(child);
    child.coverage.primary = { status: 'partial', reason: 'incomplete_call' };
    reject(child);
    child.coverage.primary.reason = 'nonfatal_error';
    child.status = 'partial';
    child.reason = 'nonfatal_error';
    expect(validateConsumptionV2(child)).toBe(child);
    const benchmark = ordinary();
    benchmark.nodes[17].reads[0].value = 'live';
    benchmark.nodes[17].meta.branch = 'failed';
    reject(benchmark);
    benchmark.coverage.control_flow = { status: 'partial', reason: 'nonfatal_error' };
    benchmark.status = 'partial';
    benchmark.reason = 'nonfatal_error';
    expect(validateConsumptionV2(benchmark)).toBe(benchmark);
  });

  it('rejects unsupported read scopes and arbitrary missing/null/unknown members', () => {
    const child = ordinary();
    child.nodes[10].meta.profile = 'unsupported';
    child.coverage.preparation = { status: 'partial', reason: 'unsupported_consumer' };
    child.status = 'partial';
    child.reason = 'unsupported_consumer';
    expect(validateConsumptionV2(child)).toBe(child);
    appendNode(child, { parent: 10, kind: 'scope', consumer: 'strategy.history', reads: [], meta: {} });
    reject(child);
    for (const mutate of [
      (c: Mutable) => { delete c.nodes[0].meta.mode; },
      (c: Mutable) => { c.nodes[0].meta.mode = null; },
      (c: Mutable) => { c.nodes[0].meta.path = 'secret'; },
      (c: Mutable) => { c.nodes[0].reads = null; },
      (c: Mutable) => { c.nodes[0].id = '0'; },
    ]) {
      const candidate = ordinary();
      mutate(candidate);
      reject(candidate);
    }
  });

  it('enforces selection/default and registration short circuits', () => {
    let child = ordinary();
    child.nodes[2].reads.splice(1, 1);
    reject(child);
    child = ordinary();
    child.nodes[2].meta.enabled_live_defaulted = false;
    reject(child);
    child = ordinary();
    child.nodes[5].reads.push({ field: 'portfolio.registration.portfolio_optimization', value_type: 'bool', value: true, origin: 'app_config_effective' });
    reject(child);
    child = ordinary();
    child.nodes[5].reads.push({ field: 'portfolio.registration.max_allocation', value_type: 'number', value: 0.8, origin: 'app_config_effective' });
    reject(child);
  });

  it('requires all three optimization map participants to be registered', () => {
    for (const index of [28, 30, 32]) {
      const child = rich();
      child.nodes[index].strategy = 'OTHER';
      reject(child);
    }
  });

  it('preserves legal repeated attempt symbols and current-then-removed order', () => {
    const appendAttempt = (child: Mutable, branch: string, symbol: string) => {
      const batch = child.nodes.find((n: Mutable) => n.consumer === 'execution.batch');
      const index = child.nodes.filter((n: Mutable) => n.consumer === 'execution.attempt').length;
      appendNode(child, { parent: batch.id, kind: 'call', consumer: 'execution.attempt', reads: [],
        meta: { state: 'returned', branch, price_source: 'market_prices', returned: true },
        outcome: 'returned_ok', symbol, index });
    };
    for (const branches of [['current_position'], ['removed_position'], ['current_position', 'removed_position']]) {
      const child = ordinary();
      for (const branch of branches) appendAttempt(child, branch, 'ES');
      expect(validateConsumptionV2(child)).toBe(child);
    }
    const reversed = ordinary();
    appendAttempt(reversed, 'removed_position', 'NQ');
    appendAttempt(reversed, 'current_position', 'ES');
    reject(reversed);
  });

  it('accepts finite binary64 numbers beyond safe integers and rejects nonfinite numbers', () => {
    const child = rich();
    child.nodes[4].reads[1].value = Number.MAX_VALUE;
    expect(validateConsumptionV2(child)).toBe(child);
    child.nodes[4].reads[1].value = -Number.MAX_VALUE;
    expect(validateConsumptionV2(child)).toBe(child);
    for (const value of [NaN, Infinity, -Infinity, true, '1', null, 1n]) {
      child.nodes[4].reads[1].value = value;
      reject(child);
    }
    child.nodes[4].reads[1].value = 1;
    child.nodes[20].reads[0].value = [[1, Number.MAX_VALUE]];
    expect(validateConsumptionV2(child)).toBe(child);
  });

  it('checks distinct int32 and uint53 inclusive bounds', () => {
    for (const value of [-2147483648, 2147483647]) {
      const child = ordinary();
      child.nodes[6].reads[0].value = value;
      expect(validateConsumptionV2(child)).toBe(child);
    }
    for (const value of [-2147483649, 2147483648, 1.5, true, '1', null, NaN, Infinity]) {
      const child = ordinary();
      child.nodes[6].reads[0].value = value;
      reject(child);
    }
    for (const value of [0, Number.MAX_SAFE_INTEGER]) {
      const child = rich();
      child.nodes[9].reads[0].value = value;
      expect(validateConsumptionV2(child)).toBe(child);
    }
    for (const value of [-1, Number.MAX_SAFE_INTEGER + 1, 1.5, true, '1', null, NaN, Infinity]) {
      const child = rich();
      child.nodes[9].reads[0].value = value;
      reject(child);
    }
  });

  it('uses exact Decimal8 endpoints and rejects adjacent unit/lexical failures', () => {
    const child = rich();
    for (const value of ['-92233720368.54775808', '92233720368.54775807', '0', '1.25']) {
      child.nodes[24].reads[0].value = value;
      expect(validateConsumptionV2(child)).toBe(child);
    }
    for (const value of ['-92233720368.54775809', '92233720368.54775808', '-0', '1.20', '01', 1.25, null]) {
      child.nodes[24].reads[0].value = value;
      reject(child);
    }
  });

  it('rejects scalar containers before recursively traversing alias depth, and preserves legal pair aliases', () => {
    const child = rich();
    const pair = [8, 32];
    child.nodes[18].reads[1].value = [pair, pair, [8, 32]];
    expect(validateConsumptionV2(child)).toBe(child);
    let alias: unknown = 1;
    for (let i = 0; i < 4; i++) alias = Array(8).fill(alias);
    child.nodes[4].reads[1].value = alias;
    reject(child);
    const cycle: any[] = [];
    cycle.push(cycle);
    child.nodes[18].reads[1].value = cycle;
    reject(child);
  });

  it('accepts 32 selection identities and rejects the 33rd, including disabled definitions', () => {
    const child = ordinary();
    child.coverage.setup = { status: 'partial', reason: 'instrumentation_missing' };
    child.status = 'partial';
    child.reason = 'instrumentation_missing';
    for (let i = 1; i < 32; i++) {
      appendNode(child, { parent: 1, kind: 'scope', consumer: 'setup.selection_entry', reads: [
        { field: 'setup.selection.enabled_live', value_type: 'bool', value: false, origin: 'configured_strategy_leaf' },
      ], meta: { enabled_live_read: true, allocation_read: false, enabled_live_present: true }, strategy: `S${i}` });
    }
    expect(validateConsumptionV2(child)).toBe(child);
    appendNode(child, { parent: 1, kind: 'scope', consumer: 'setup.selection_entry', reads: [],
      meta: { enabled_live_read: false, allocation_read: false }, strategy: 'S32' });
    reject(child);
  });

  it('accepts 1024 distinct read-map symbols and rejects 1025', () => {
    const child = rich();
    for (let i = 0; i < 1022; i++) {
      child.nodes[22].reads.push({ field: 'strategy.sizing.symbol_limit.symbol.present',
        value_type: 'bool', value: false, origin: 'runtime_effective', symbol: `SYM${i}` });
    }
    expect(validateConsumptionV2(child)).toBe(child);
    child.nodes[22].reads.push({ field: 'strategy.sizing.symbol_limit.symbol.present',
      value_type: 'bool', value: false, origin: 'runtime_effective', symbol: 'ONE_MORE' });
    reject(child);
  });

  it('accepts 2048 repeated native charge invocations and rejects 2049', () => {
    const child = rich();
    for (let i = 0; i < 2047; i++) appendNode(child, {
      parent: 11, kind: 'call', consumer: 'cost.strategy_execution', reads: [], meta: {},
      outcome: 'returned_ok', strategy: 'ALPHA', symbol: 'ES',
    });
    expect(validateConsumptionV2(child)).toBe(child);
    appendNode(child, { parent: 11, kind: 'call', consumer: 'cost.strategy_execution',
      reads: [], meta: {}, outcome: 'returned_ok', strategy: 'ALPHA', symbol: 'ES' });
    reject(child);
  });

  it('accepts 128 pairs per read and rejects 129, while preserving duplicates', () => {
    const child = rich();
    child.nodes[18].reads[1].value = Array.from({ length: 128 }, () => [8, 32]);
    expect(validateConsumptionV2(child)).toBe(child);
    child.nodes[18].reads[1].value.push([8, 32]);
    reject(child);
  });

  it('rejects cheap over-limit node/read containers before secondary traversal', () => {
    const tooManyNodes = ordinary();
    tooManyNodes.nodes = Array(4097).fill(tooManyNodes.nodes[0]);
    reject(tooManyNodes);
    const tooManyReads = ordinary();
    tooManyReads.nodes[6].reads = Array(4097).fill(tooManyReads.nodes[6].reads[0]);
    reject(tooManyReads);
    const tooManyPasses = ordinary();
    for (let index = 1; index <= 5; index++) appendNode(tooManyPasses, {
      parent: 11, kind: 'scope', consumer: 'portfolio.pass', reads: [], meta: {}, index,
    });
    reject(tooManyPasses);
  });

  it('accepts 8192 total pairs and rejects 8193', () => {
    const child = ordinary();
    const primaryCalls = [12];
    for (let i = 1; i < 32; i++) {
      const strategy = `S${i}`;
      appendNode(child, { parent: 1, kind: 'scope', consumer: 'setup.selection_entry', strategy,
        reads: [{ field: 'setup.selection.enabled_live', value_type: 'bool', value: true, origin: 'configured_strategy_leaf' }],
        meta: { enabled_live_read: true, allocation_read: false, enabled_live_present: true } });
      appendNode(child, { parent: 3, kind: 'scope', consumer: 'setup.factory_entry', strategy, reads: [],
        meta: { construction: 'succeeded', initialize: 'succeeded', start: 'succeeded' } });
      appendNode(child, { parent: null, kind: 'call', consumer: 'portfolio.registration', strategy, reads: [],
        meta: {}, outcome: 'returned_ok' });
      primaryCalls.push(appendNode(child, { parent: 11, kind: 'call', consumer: 'strategy.primary', strategy, reads: [],
        meta: { profile: 'standard' }, outcome: 'returned_ok' }));
      appendNode(child, { parent: null, kind: 'call', consumer: 'execution.batch', strategy, reads: [],
        meta: { state: 'returned' }, outcome: 'returned_ok' });
    }
    for (const parent of primaryCalls) {
      for (const [consumer, field] of [
        ['strategy.history', 'strategy.history.ema_windows'],
        ['strategy.forecast', 'strategy.forecast.ema_windows'],
      ]) {
        appendNode(child, { parent, kind: 'scope', consumer, meta: {},
          reads: [{ field, value_type: 'int32_pairs', value: Array.from({ length: 128 }, () => [8, 32]),
            origin: 'constructor_effective' }] });
      }
    }
    expect(validateConsumptionV2(child)).toBe(child);
    child.nodes.at(-1).reads.push({ field: 'strategy.forecast.fdm', value_type: 'int32_number_pairs',
      value: [[1, 0.5]], origin: 'constructor_effective' });
    reject(child);
  });

  it('rejects a staged complete tree with only scopes and a retained unavailable prefix', () => {
    const child = ordinary();
    child.nodes = [{ id: 0, parent: null, kind: 'scope', consumer: 'runner.non_trading_day',
      reads: [], meta: { skip_strategy_processing: false } }];
    child.coverage = Object.fromEntries(stages.map(stage => [stage,
      stage === 'control_flow' ? { status: 'partial', reason: 'instrumentation_missing' } :
        { status: 'unavailable', reason: 'instrumentation_missing' }]));
    child.status = 'partial';
    child.reason = 'instrumentation_missing';
    reject(child);
    const fallback = clone(cases.accepted.unavailable_capacity_exceeded);
    fallback.nodes = [clone(cases.accepted.ordinary.nodes[0])];
    reject(fallback);
  });

  it('tests identity ASCII length, forbidden symbol and privacy by closed keys', () => {
    const child = ordinary();
    child.nodes[5].strategy = 'A'.repeat(64);
    reject(child); // cross-reference mismatch remains, so use a self-contained disabled entry
    const candidate = ordinary();
    appendNode(candidate, { parent: 1, kind: 'scope', consumer: 'setup.selection_entry', strategy: 'A'.repeat(64),
      reads: [], meta: { enabled_live_read: false, allocation_read: false } });
    expect(validateConsumptionV2(candidate)).toBe(candidate);
    candidate.nodes.at(-1).strategy += 'A';
    reject(candidate);
    candidate.nodes.at(-1).strategy = 'BAD\nNAME';
    reject(candidate);
    candidate.nodes.at(-1).strategy = 'BAD/NAME';
    reject(candidate);
    const privateField = ordinary();
    privateField.nodes[6].reads[0].field = 'runner.market_input.secret_path';
    reject(privateField);
    privateField.nodes[6].reads[0].field = 'runner.market_input.historical_days';
    privateField.nodes[6].reads[0].symbol = 'ES';
    reject(privateField);
  });

  it('rejects every required metadata key when missing and every metadata key with wrong type', () => {
    for (const spec of sharedCatalog.metadata as Mutable[]) {
      const base = spec.consumer === 'setup.controlled_validation' ? cases.accepted.controlled : cases.accepted.rich;
      const node = base.nodes.find((item: Mutable) => item.consumer === spec.consumer);
      expect(node, spec.consumer).toBeDefined();
      if (spec.required) {
        const child = clone(base);
        delete child.nodes[node.id].meta[spec.key];
        reject(child);
      }
      const child = clone(base);
      child.nodes[node.id].meta[spec.key] = spec.type === 'bool' ? 'true' : true;
      reject(child);
    }
  });

  it('accepts meaningful optional metadata and rejects cross-field implications', () => {
    const child = rich();
    child.nodes[8].meta.previous_close_source = 'stored_previous_close';
    expect(validateConsumptionV2(child)).toBe(child);
    child.nodes[8].meta.cost_model_reached = false;
    reject(child);
    const risk = rich();
    risk.nodes[36].meta.manager_source = 'absent';
    reject(risk);
    const attempt = rich();
    attempt.nodes[40].meta.price_source = 'current_average_price';
    expect(validateConsumptionV2(attempt)).toBe(attempt);
    attempt.nodes[40].meta.price_source = 'previous_average_price';
    reject(attempt);
    const stopped = ordinary();
    stopped.nodes[11].meta.skip_execution_generation = true;
    expect(validateConsumptionV2(stopped)).toBe(stopped);
    const active = rich();
    active.nodes[11].meta.skip_execution_generation = true;
    reject(active);
  });

  it('rejects duplicate phases, pass indices, estimate indices and strategy calls', () => {
    const phase = ordinary();
    appendNode(phase, { parent: 0, kind: 'scope', consumer: 'setup.ordinary_selection', reads: [], meta: {} });
    reject(phase);
    const pass = ordinary();
    appendNode(pass, { parent: 11, kind: 'scope', consumer: 'portfolio.pass', reads: [], meta: {}, index: 0 });
    reject(pass);
    const estimate = rich();
    appendNode(estimate, { parent: 26, kind: 'scope', consumer: 'portfolio.estimate', reads: [], meta: {}, symbol: 'NQ', index: 0 });
    reject(estimate);
    const strategyCall = ordinary();
    appendNode(strategyCall, { parent: 11, kind: 'call', consumer: 'strategy.primary', reads: [], meta: { profile: 'standard' }, outcome: 'returned_ok', strategy: 'ALPHA' });
    reject(strategyCall);
  });

  it('keeps skipped preparation and primary coupled to the observed non-trading decision', () => {
    const child = clone(cases.accepted.non_trading_skip);
    expect(child.coverage.preparation).toEqual({ status: 'skipped', reason: 'non_trading_day' });
    expect(child.coverage.primary).toEqual({ status: 'skipped', reason: 'non_trading_day' });
    expect(validateConsumptionV2(child)).toBe(child);
    const decision = child.nodes.find((node: Mutable) => node.consumer === 'runner.non_trading_day');
    decision.meta.skip_strategy_processing = false;
    reject(child);
  });
});

// Synthetic contract-capacity data with literal settings, not native producer output.
const stages = ['setup', 'market_input', 'cost_history', 'preparation', 'primary', 'execution', 'diagnostics', 'control_flow'];
const typicalStrategies = ['ALPHA', 'BETA', 'GAMMA'];
const typicalSymbols = Array.from({ length: 40 }, (_, i) => `SYM${String(i).padStart(2, '0')}`);
const costFields = [
  'cost.spread.baseline_spread_ticks', 'cost.spread.min_spread_ticks',
  'cost.spread.max_spread_ticks', 'cost.spread.spread_cost_multiplier',
  'cost.spread.tick_size', 'cost.volatility.lambda',
  'cost.volatility.min_multiplier', 'cost.volatility.max_multiplier',
  'cost.impact.min_adv', 'cost.impact.min_participation',
  'cost.impact.max_participation', 'cost.impact.max_impact_bps',
  'cost.charge.explicit_fee_per_contract', 'cost.charge.point_value',
];
const emaPairs = [[8, 32], [16, 64], [32, 128], [64, 256], [128, 512], [256, 1024]];
const fdmPairs = [[1, 0.5], [2, 0.75], [3, 1], [4, 1.25], [5, 1.5], [6, 1.75], [7, 2], [8, 2.25]];
const compactBytes = (value: unknown): number => new TextEncoder().encode(JSON.stringify(value)).byteLength;

function typicalChild(): Mutable {
  const child: Mutable = {
    version: 2, status: 'complete', reason: 'none',
    coverage: Object.fromEntries(stages.map(stage => [stage, { status: 'complete', reason: 'none' }])),
    nodes: [],
  };
  const nodes = child.nodes;
  const read = (field: string, value_type: string, value: unknown, origin: string, symbol?: string): Mutable => {
    const row: Mutable = { field, value_type, value, origin };
    if (symbol !== undefined) row.symbol = symbol;
    return row;
  };
  const add = (consumer: string, kind: 'call' | 'scope', parent: number | null = null,
    meta: Mutable = {}, reads: Mutable[] = [], extra: Mutable = {}): number => {
    const node: Mutable = { id: nodes.length, parent, kind, consumer, reads, meta };
    if (kind === 'call') node.outcome = 'returned_ok';
    Object.assign(node, extra);
    nodes.push(node);
    return node.id;
  };
  const charge = (consumer: string, kind: 'call' | 'scope', parent: number, meta: Mutable = {}, extra: Mutable = {}): number =>
    add(consumer, kind, parent, meta, costFields.map(field => read(field, 'number', 1, 'runtime_effective')), extra);
  const selector = add('setup.selector', 'call', null, { mode: 'ordinary' });
  const selection = add('setup.ordinary_selection', 'scope', selector);
  for (const strategy of typicalStrategies) {
    add('setup.selection_entry', 'scope', selection,
      { enabled_live_read: true, allocation_read: true, enabled_live_present: true, allocation_defaulted: false },
      [read('setup.selection.enabled_live', 'bool', true, 'configured_strategy_leaf'),
        read('setup.selection.default_allocation', 'number', 0.3, 'configured_strategy_leaf')],
      { strategy });
  }
  const factory = add('setup.factory', 'call');
  for (const strategy of typicalStrategies) {
    add('setup.factory_entry', 'scope', factory,
      { profile: 'standard', construction: 'succeeded', initialize: 'succeeded', start: 'succeeded' }, [], { strategy });
    add('portfolio.registration', 'call', null, {},
      [read('portfolio.registration.initial_allocation', 'number', 0.3, 'selected_allocation'),
        read('portfolio.registration.stored_allocation', 'number', 0.3, 'selected_allocation')], { strategy });
  }
  add('runner.market_window', 'scope', null, {},
    [read('runner.market_input.historical_days', 'int32', 250, 'app_config_effective')]);
  add('runner.market_fetch', 'call');
  for (const symbol of typicalSymbols) {
    const history = add('execution.history_update', 'call', null,
      { cost_model_reached: true, previous_close_source: 'initial_current_close' }, [], { symbol });
    add('cost.history', 'scope', history, {},
      [read('cost.impact_history.adv_lookback_days', 'uint53', 20, 'runtime_effective'),
        read('cost.spread_history.lookback_days', 'uint53', 20, 'runtime_effective')]);
  }
  const strategyScopes = (call: number): void => {
    for (const [consumer, field, kind, value] of [
      ['strategy.history', 'strategy.history.max_history_size', 'uint53', 500],
      ['strategy.volatility', 'strategy.volatility.vol_lookback_short', 'int32', 20],
      ['strategy.forecast', 'strategy.forecast.vol_lookback_short', 'int32', 20],
      ['strategy.regime', 'strategy.regime.vol_lookback_long', 'int32', 50],
    ] as const) {
      const rows = [read(field, kind, value, 'constructor_effective')];
      if (consumer === 'strategy.history') {
        rows.push(read('strategy.history.ema_windows', 'int32_pairs', clone(emaPairs), 'constructor_effective'));
      } else if (consumer === 'strategy.forecast') {
        rows.push(read('strategy.forecast.ema_windows', 'int32_pairs', clone(emaPairs), 'constructor_effective'));
        rows.push(read('strategy.forecast.fdm', 'int32_number_pairs', clone(fdmPairs), 'constructor_effective'));
      }
      add(consumer, 'scope', call, {}, rows);
    }
    for (const [consumer, prefix, origin, meta] of [
      ['strategy.sizing', 'strategy.sizing.symbol_limit.symbol', 'derived', {}],
      ['strategy.buffering', 'strategy.buffering.symbol_limit.symbol', 'derived', {}],
      ['strategy.base_risk', 'strategy.base_risk.trading_multiplier.symbol', 'runtime_effective', { supported: true }],
      ['strategy.position_limits', 'strategy.position_limits.symbol', 'derived', { supported: true }],
    ] as const) {
      const rows: Mutable[] = [];
      for (const symbol of typicalSymbols) {
        rows.push(read(prefix + '.present', 'bool', true, 'runtime_effective', symbol));
        rows.push(read(prefix + '.value', 'number', 1, origin, symbol));
      }
      add(consumer, 'scope', call, meta, rows);
    }
  };
  const preparation = add('strategy.preparation', 'call', null, { profile: 'standard' }, [], { strategy: 'ALPHA' });
  strategyScopes(preparation);
  const primary = add('portfolio.primary', 'call', null, { skip_execution_generation: false });
  for (const strategy of typicalStrategies) {
    const call = add('strategy.primary', 'call', primary, { profile: 'standard' }, [], { strategy });
    strategyScopes(call);
  }
  for (let passIndex = 0; passIndex < 5; passIndex++) {
    const pass = add('portfolio.pass', 'scope', primary, {},
      [read('portfolio.pass.use_optimization', 'bool', true, 'app_config_effective'),
        read('portfolio.pass.use_risk_management', 'bool', true, 'app_config_effective')], { index: passIndex });
    const optimization = add('portfolio.optimization', 'call', pass, { skip: 'none' },
      [read('portfolio.optimization.total_capital', 'fixed_decimal8', '1000000', 'derived')]);
    for (const phase of ['portfolio.symbol_collection', 'portfolio.numeric_aggregation', 'portfolio.redistribution']) {
      const scope = add(phase, 'scope', optimization);
      for (const strategy of typicalStrategies) {
        add('portfolio.optimization_strategy', 'scope', scope, {},
          [read('portfolio.optimization.strategy.enabled', 'bool', true, 'derived'),
            read('portfolio.optimization.strategy.allocation', 'number', 0.3, 'selected_allocation')], { strategy });
      }
    }
    typicalSymbols.forEach((symbol, index) => {
      const estimate = add('portfolio.estimate', 'scope', optimization, {}, [], { symbol, index });
      charge('cost.estimate', 'call', estimate, { asset_lookup: 'exact_symbol', input_source: 'explicit_values' });
    });
    add('optimizer.primary', 'call', optimization, { buffer_branch: 'disabled' },
      [read('optimizer.use_buffering', 'bool', false, 'app_config_effective')]);
    const risk = add('portfolio.risk', 'call', pass, { skip: 'none', manager_source: 'internal' });
    add('risk.primary', 'call', risk, {}, [read('risk.var_limit', 'number', 0.2, 'app_config_effective')]);
  }
  for (const strategy of typicalStrategies) for (const symbol of typicalSymbols) {
    charge('cost.strategy_execution', 'call', primary, { input_source: 'internally_tracked' }, { strategy, symbol });
  }
  for (const symbol of typicalSymbols) charge('cost.compatibility_execution', 'call', primary, {}, { symbol });
  for (const strategy of typicalStrategies) {
    const batch = add('execution.batch', 'call', null, { state: 'returned' }, [], { strategy });
    typicalSymbols.forEach((symbol, index) => {
      const attempt = add('execution.attempt', 'call', batch,
        { state: 'returned', branch: 'current_position', price_source: 'market_prices', returned: true },
        [], { symbol, index });
      charge('cost.execution', 'scope', attempt, { input_source: 'internally_tracked' });
    });
  }
  add('risk.diagnostics', 'call');
  add('runner.non_trading_day', 'scope', null, { skip_strategy_processing: false });
  add('runner.benchmark', 'scope', null, { branch: 'not_reached' },
    [read('runner.benchmark.mode', 'benchmark_mode', 'deferred', 'app_config_effective')]);
  return child;
}

describe('consumption v2 finite capacity', () => {
  it('accepts the full three-strategy, forty-symbol, five-pass synthetic workload', () => {
    const child = typicalChild();
    const named = (consumer: string) => child.nodes.filter((node: Mutable) => node.consumer === consumer);
    expect(typicalStrategies).toHaveLength(3);
    expect(typicalSymbols).toHaveLength(40);
    expect(named('portfolio.pass').map((node: Mutable) => node.index)).toEqual([0, 1, 2, 3, 4]);
    const calls = [...named('strategy.preparation'), ...named('strategy.primary')];
    expect(calls).toHaveLength(4);
    let parameterPairs = 0;
    for (const call of calls) {
      const scopes = child.nodes.filter((node: Mutable) => node.parent === call.id);
      expect(scopes).toHaveLength(8);
      for (const [consumer, field, kind, pairs] of [
        ['strategy.history', 'strategy.history.ema_windows', 'int32_pairs', emaPairs],
        ['strategy.forecast', 'strategy.forecast.ema_windows', 'int32_pairs', emaPairs],
        ['strategy.forecast', 'strategy.forecast.fdm', 'int32_number_pairs', fdmPairs],
      ] as const) {
        const scope = scopes.find((node: Mutable) => node.consumer === consumer);
        const rows = scope.reads.filter((row: Mutable) => row.field === field);
        expect(rows).toEqual([{ field, value_type: kind, value: pairs, origin: 'constructor_effective' }]);
        parameterPairs += rows[0].value.length;
      }
    }
    expect(parameterPairs).toBe(80);
    expect(named('execution.history_update')).toHaveLength(40);
    expect(named('cost.history')).toHaveLength(40);
    expect(named('portfolio.optimization_strategy')).toHaveLength(45);
    expect(named('portfolio.estimate')).toHaveLength(200);
    expect(named('execution.attempt')).toHaveLength(120);
    expect(['cost.estimate', 'cost.strategy_execution', 'cost.compatibility_execution', 'cost.execution']
      .map(name => named(name).length)).toEqual([200, 120, 40, 120]);
    const charges = child.nodes.filter((node: Mutable) => ['cost.estimate', 'cost.strategy_execution', 'cost.compatibility_execution', 'cost.execution'].includes(node.consumer));
    expect(charges.reduce((sum: number, node: Mutable) => sum + node.reads.length, 0)).toBe(6720);
    expect(child.nodes.filter((node: Mutable) => ['strategy.sizing', 'strategy.buffering', 'strategy.base_risk', 'strategy.position_limits'].includes(node.consumer))
      .reduce((sum: number, node: Mutable) => sum + node.reads.length, 0)).toBe(1280);
    expect(child.nodes).toHaveLength(1022);
    const reads = child.nodes.reduce((sum: number, node: Mutable) => sum + node.reads.length, 0);
    expect(reads).toBe(8237);
    const bytes = compactBytes(child);
    expect(bytes).toBe(1038202);
    expect(bytes + 131072).toBeLessThanOrEqual(2097152);
    expect(validateConsumptionV2(child)).toBe(child);
  });

  it('accepts the corrected typical child at the exact byte cap and rejects one byte more', () => {
    const child = typicalChild();
    const primary = child.nodes.find((node: Mutable) => node.consumer === 'portfolio.primary').id;
    let current = compactBytes(child);
    while (true) {
      const node = { id: child.nodes.length, parent: primary, kind: 'call',
        consumer: 'cost.strategy_execution',
        reads: costFields.map(field => ({ field, value_type: 'number', value: 1.2345678901234567e100, origin: 'runtime_effective' })),
        meta: { input_source: 'internally_tracked' }, outcome: 'returned_ok', strategy: 'ALPHA', symbol: 'SYM00' };
      const increment = 1 + compactBytes(node);
      if (current + increment > 2097152) break;
      child.nodes.push(node);
      current += increment;
    }
    const deficit = 2097152 - current;
    const adjustable = child.nodes.filter((node: Mutable) => ['cost.estimate', 'cost.strategy_execution', 'cost.compatibility_execution', 'cost.execution'].includes(node.consumer))
      .flatMap((node: Mutable) => node.reads.filter((row: Mutable) => row.value === 1));
    expect(adjustable.length).toBeGreaterThan(deficit);
    for (const row of adjustable.slice(0, deficit)) row.value = 10;
    expect(compactBytes(child)).toBe(2097152);
    expect(child.nodes.length).toBeLessThanOrEqual(4096);
    expect(child.nodes.reduce((sum: number, node: Mutable) => sum + node.reads.length, 0)).toBeLessThanOrEqual(16384);
    expect(validateConsumptionV2(child)).toBe(child);
    adjustable[deficit].value = 10;
    expect(compactBytes(child)).toBe(2097153);
    reject(child);
  });
});

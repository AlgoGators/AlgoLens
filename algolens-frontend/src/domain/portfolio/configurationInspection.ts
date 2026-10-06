/** Closed inspection protocol. This catalog validates observations; it never computes defaults. */
import { validateConsumptionV2, type ConsumptionV2 } from './consumptionInspection';
import { validateEquityRunConsumption, type EquityRunConsumption } from './equityRunConsumption';
export class InspectionProtocolError extends Error {
  constructor() { super('Published configuration response is unavailable.'); }
}
export class UnsupportedNumericRepresentationError extends Error {
  constructor() { super('Published configuration uses an unsupported numeric representation.'); }
}

type RecordValue = Record<string, unknown>;
export type InspectionField = {
  path: string; scope: 'exact'; classification: string; reason: string;
  condition: string; value_type: string; unit: string; value_origin: string;
  value_state: 'included' | 'absent_in_input' | 'omitted'; value?: unknown;
};
export type TrendStage = Record<string, number | boolean | number[][]>;
export type SelectedTrend = {
  schema_version: 1; provenance: 'shared_resolver_same_inputs';
  slow_concentration_override: { state: 'absent' } | { state: 'present'; value: number };
  strategies: Array<{
    strategy_id: string; strategy_type: string; selected_allocation: number;
    factory_resolved: TrendStage; constructor_normalized: TrendStage;
  }>;
};
type PublicationBase = {
  profile: string; authority: string; stream: string;
  identity: { registry_id: string; registry_revision: number; engine_strategy_id: string;
    portfolio_id: string; run_date: string; capture_id: string; publication_id: string;
    runtime_attempt_id: string | null; producer_version: string; control_mode: string };
  captured_at: string; publication_recorded_at: string; status: string; reason: string;
};
type FuturesPublication = PublicationBase & {
  supplied: { fields: InspectionField[] } | null; selected_trend: SelectedTrend | null;
} & (
  { publication_schema_version: 1; consumption: { status: 'not_collected' } } |
  { publication_schema_version: 2; consumption: ConsumptionV2 }
);
export type Publication = FuturesPublication | (PublicationBase & {
  publication_schema_version: 3; equity_run_consumption: EquityRunConsumption;
  supplied?: never; selected_trend?: never; consumption?: never;
});
export type InspectionResponse = {
  api_version: 1; scope: { registry_id: string; portfolio_id: string };
  read_at: string; status: 'available' | 'unavailable'; reason: string;
  publication: Publication | null;
};

const PROFILE = 'live_portfolio_runner_futures';
const fixedText = `
/portfolio_id|read_only_metadata|identity_metadata|metadata_only|string|identity|not_projected|omitted
/initial_capital|source_supported_config_input|source_reader|source_path|number|account_currency|app_config_member|included
/reserve_capital_pct|unsupported_in_profile|stored_metadata_only|no_active_profile_reader|number|fraction|app_config_member|included
/benchmark_mode|source_supported_config_input|source_reader|benchmark_stage|enum_string|mode|app_config_member|included
/execution/commission_rate|unsupported_in_profile|not_wired_to_futures_cost_model|no_active_profile_reader|number|unverified_rate|app_config_member|included
/execution/slippage_bps|unsupported_in_profile|not_wired_to_futures_cost_model|no_active_profile_reader|number|basis_points|app_config_member|included
/execution/position_limit_backtest|unsupported_in_profile|backtest_only|no_active_profile_reader|number|contracts|app_config_member|included
/execution/position_limit_live|source_supported_config_input|source_reader|base_position_validation|number|contracts|app_config_member|included
/optimization/tau|source_supported_config_input|source_reader|optimizer_succeeded_and_buffering_enabled|number|risk_scale|app_config_member|included
/optimization/capital|read_only_metadata|derived_alias|metadata_only|number|account_currency|app_config_member|included
/optimization/cost_penalty_scalar|source_supported_config_input|source_reader|optimizer_enabled|number|multiplier|app_config_member|included
/optimization/asymmetric_risk_buffer|unsupported_in_profile|no_active_reader|no_active_profile_reader|number|unverified_buffer_fraction|app_config_member|included
/optimization/max_iterations|source_supported_config_input|source_reader|optimizer_enabled|integer|iterations|app_config_member|included
/optimization/convergence_threshold|source_supported_config_input|source_reader|optimizer_enabled|number|objective_difference|app_config_member|included
/optimization/use_buffering|source_supported_config_input|source_reader|optimizer_enabled|boolean|flag|app_config_member|included
/optimization/buffer_size_factor|source_supported_config_input|source_reader|optimizer_succeeded_and_buffering_enabled|number|multiplier|app_config_member|included
/optimization/version|read_only_metadata|version_metadata|metadata_only|string|config_version|not_projected|omitted
/risk/var_limit|source_supported_config_input|source_reader|risk_enabled|number|annualized_volatility_fraction|app_config_member|included
/risk/jump_risk_limit|source_supported_config_input|source_reader|risk_enabled|number|fraction|app_config_member|included
/risk/corr_shock_threshold|unsupported_in_profile|inactive_alternative|no_active_profile_reader|number|annualized_volatility_fraction|app_config_member|included
/risk/jump_shock_threshold|unsupported_in_profile|inactive_alternative|no_active_profile_reader|number|annualized_volatility_fraction|app_config_member|included
/risk/max_gross_leverage|source_supported_config_input|source_reader|risk_enabled|number|leverage_multiple|app_config_member|included
/risk/max_net_leverage|source_supported_config_input|source_reader|risk_enabled|number|leverage_multiple|app_config_member|included
/risk/capital|read_only_metadata|derived_alias|metadata_only|number|account_currency|app_config_member|included
/risk/version|read_only_metadata|version_metadata|metadata_only|string|config_version|not_projected|omitted
/risk/max_drawdown|source_supported_config_input|source_reader|base_strategy_risk_check|number|fraction|app_config_member|included
/risk/max_leverage|source_supported_config_input|diagnostic_reader|base_strategy_risk_check|number|leverage_multiple|app_config_member|included
/risk_defaults/confidence_level|source_supported_config_input|source_reader|risk_enabled|number|probability|app_config_member|included
/risk_defaults/lookback_period|source_supported_config_input|source_reader|risk_enabled|integer|bar_records|app_config_member|included
/risk_defaults/max_correlation|source_supported_config_input|source_reader|risk_enabled|number|absolute_correlation|app_config_member|included
/backtest/lookback_years|unsupported_in_profile|backtest_only|no_active_profile_reader|integer|years|app_config_member|included
/backtest/store_trade_details|unsupported_in_profile|backtest_only|no_active_profile_reader|boolean|flag|app_config_member|included
/live/historical_days|source_supported_config_input|source_reader|source_path|integer|calendar_days|app_config_member|included
/strategy_defaults/fdm|unsupported_in_profile|blocked_default_fallback|no_active_profile_reader|integer_number_pairs|rule_count_multiplier_pairs|app_config_member|included
/strategy_defaults/max_strategy_allocation|source_supported_config_input|source_reader|allocation_validation|number|fraction|app_config_member|included
/strategy_defaults/min_strategy_allocation|source_supported_config_input|source_reader|allocation_validation|number|fraction|app_config_member|included
/strategy_defaults/use_optimization|source_supported_config_input|source_reader|source_path|boolean|flag|app_config_member|included
/strategy_defaults/use_risk_management|source_supported_config_input|source_reader|source_path|boolean|flag|app_config_member|included
/strategy_defaults/carver_buffer_floor|source_supported_config_input|source_reader|strategy_config_present_leaf_absent_and_buffering_enabled|number|contracts|app_config_member|included
/strategy_defaults/carver_buffer_position_factor|source_supported_config_input|source_reader|strategy_config_present_leaf_absent_and_buffering_enabled|number|fraction|app_config_member|included
`;
const strategyText = `
enabled_live|source_supported_config_input|source_reader|strategy_selection|boolean|flag|configured_strategy_leaf
default_allocation|source_supported_config_input|source_reader|strategy_selection|number|fraction|configured_strategy_leaf
enabled_backtest|unsupported_in_profile|backtest_only|no_active_profile_reader|boolean|flag|configured_strategy_leaf
type|source_supported_config_input|source_reader|strategy_dispatch|enum_string|strategy_type|configured_strategy_leaf
config/weight|source_supported_config_input|source_reader|selected_known_strategy_buffering_enabled|number|multiplier|configured_strategy_leaf
config/risk_target|source_supported_config_input|source_reader|selected_known_strategy|number|annualized_volatility_fraction|configured_strategy_leaf
config/idm|source_supported_config_input|source_reader|selected_known_strategy|number|multiplier|configured_strategy_leaf
config/max_symbol_concentration|source_supported_config_input|source_reader|selected_known_strategy|number|fraction|configured_strategy_leaf
config/use_position_buffering|source_supported_config_input|source_reader|selected_known_strategy|boolean|flag|configured_strategy_leaf
config/carver_buffer_floor|source_supported_config_input|source_reader|selected_known_strategy_buffering_enabled|number|contracts|configured_strategy_leaf
config/carver_buffer_position_factor|source_supported_config_input|source_reader|selected_known_strategy_buffering_enabled|number|fraction|configured_strategy_leaf
config/ema_windows|source_supported_config_input|source_reader|selected_known_strategy|integer_pairs|short_long_bar_pairs|configured_strategy_leaf
config/vol_lookback_short|source_supported_config_input|source_reader|selected_known_strategy|integer|bar_windows|configured_strategy_leaf
config/vol_lookback_long|source_supported_config_input|source_reader|selected_known_strategy|integer|bar_windows|configured_strategy_leaf
config/fx_rate|unsupported_in_profile|typed_member_not_input_wired|no_active_profile_reader|number|currency_ratio|not_projected
config/max_history_size|unsupported_in_profile|typed_member_not_input_wired|no_active_profile_reader|integer|bar_records|not_projected
config/fdm|unsupported_in_profile|typed_member_not_input_wired|no_active_profile_reader|integer_number_pairs|rule_count_multiplier_pairs|not_projected
`;
type Spec = string[];
const catalog = (text: string) => new Map(text.trim().split('\n').map(line => {
  const [path, ...spec] = line.split('|');
  return [path, spec] as [string, Spec];
}));
const fixed = catalog(fixedText);
const strategies = catalog(strategyText);
const trendKinds: Record<string, string> = {
  weight: 'number', risk_target: 'number', fx_rate: 'number', idm: 'number',
  max_symbol_concentration: 'number', use_position_buffering: 'boolean',
  carver_buffer_floor: 'number', carver_buffer_position_factor: 'number',
  ema_windows: 'integer_pairs', vol_lookback_short: 'integer',
  vol_lookback_long: 'integer', max_history_size: 'unsigned64',
  fdm: 'integer_number_pairs',
};
const types = new Set(['TrendFollowingStrategy', 'TrendFollowingFastStrategy', 'TrendFollowingSlowStrategy']);
const unavailableReasons = new Set(['not_published', 'legacy_publication', 'unsupported_publication',
  'invalid_publication', 'publication_date_mismatch', 'scope_changed']);
const captureReasons = new Set(['projection_invalid', 'selected_stage_unavailable', 'capture_failed']);
const id = /^[A-Za-z0-9_-]{1,128}$/;
const build = /^[A-Za-z0-9._-]{1,128}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const utc = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?Z$/;
const fail = (): never => { throw new InspectionProtocolError(); };
function check(value: unknown): asserts value { if (!value) fail(); }
const object = (value: unknown): RecordValue => {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return fail();
  return value as RecordValue;
};
const keys = (value: unknown, expected: string[]): RecordValue => {
  const row = object(value);
  check(Object.keys(row).sort().join('|') === [...expected].sort().join('|'));
  return row;
};
const validDate = (year: number, month: number, day: number): boolean => {
  if (year < 1 || year > 9999 || month < 1 || month > 12 || day < 1) return false;
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return day <= days[month - 1];
};
const timestamp = (value: unknown): string => {
  check(typeof value === 'string');
  const parts = utc.exec(value);
  check(parts && validDate(Number(parts[1]), Number(parts[2]), Number(parts[3])) &&
    Number(parts[4]) <= 23 && Number(parts[5]) <= 59 && Number(parts[6]) <= 59);
  return value as string;
};
const compareUtc = (left: string, right: string): number => {
  const a = left.slice(0, 19); const b = right.slice(0, 19);
  if (a !== b) return a < b ? -1 : 1;
  const fraction = (value: string) => value.slice(19, -1).replace(/^\./, '');
  const af = fraction(left); const bf = fraction(right);
  const length = Math.max(af.length, bf.length);
  const ap = af.padEnd(length, '0'); const bp = bf.padEnd(length, '0');
  return ap === bp ? 0 : ap < bp ? -1 : 1;
};
const number = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const integer = (value: unknown, unsigned64 = false): value is number =>
  number(value) && Number.isSafeInteger(value) &&
  (unsigned64 ? value >= 0 : value >= -2147483648 && value <= 2147483647);
const valueIs = (value: unknown, kind: string, path: string,
  nonIntegerTokens: Set<string>, jsonPath: string): void => {
  if (kind === 'number') return check(number(value));
  if (kind === 'integer' || kind === 'unsigned64') {
    return check(integer(value, kind === 'unsigned64') && !nonIntegerTokens.has(jsonPath));
  }
  if (kind === 'boolean') return check(typeof value === 'boolean');
  if (kind === 'enum_string') return check(path === '/benchmark_mode' ? value === 'live' || value === 'deferred' : types.has(value as string));
  if (kind === 'string') return fail();
  if (kind === 'integer_pairs' || kind === 'integer_number_pairs') {
    check(Array.isArray(value));
    for (const [index, pair] of (value as unknown[]).entries()) {
      check(Array.isArray(pair) && pair.length === 2);
      valueIs((pair as unknown[])[0], 'integer', '', nonIntegerTokens, `${jsonPath}/${index}/0`);
      valueIs((pair as unknown[])[1], kind === 'integer_pairs' ? 'integer' : 'number',
        '', nonIntegerTokens, `${jsonPath}/${index}/1`);
    }
    return;
  }
  fail();
};
const validateField = (raw: unknown, path: string, spec: Spec,
  nonIntegerTokens: Set<string>, jsonPath: string, state?: string): InspectionField => {
  const row = object(raw);
  const actualState = row.value_state;
  check(actualState === (state ?? spec[6]) || (!state && spec.length === 6 &&
    (actualState === 'included' || actualState === 'absent_in_input')));
  keys(row, ['path', 'scope', 'classification', 'reason', 'condition', 'value_type',
    'unit', 'value_origin', 'value_state', ...(actualState === 'included' ? ['value'] : [])]);
  check(row.path === path && row.scope === 'exact');
  const descriptors = ['classification', 'reason', 'condition', 'value_type', 'unit', 'value_origin'];
  check(descriptors.every((key, index) => typeof row[key] === 'string' && row[key] === spec[index]));
  if (actualState === 'included') valueIs(row.value, spec[3], path, nonIntegerTokens, `${jsonPath}/value`);
  return row as unknown as InspectionField;
};
const validateSupplied = (raw: unknown, nonIntegerTokens: Set<string>) => {
  const supplied = keys(raw, ['projection_version', 'profile', 'coverage', 'authority', 'consumption_evidence', 'fields']);
  check(supplied.projection_version === 1 && !nonIntegerTokens.has('/publication/supplied/projection_version') &&
    supplied.profile === PROFILE &&
    supplied.coverage === 'current_typed_fields_and_known_strategy_leaves' &&
    supplied.authority === 'inspection_only' && supplied.consumption_evidence === 'not_collected');
  check(Array.isArray(supplied.fields));
  const fields = supplied.fields as unknown[];
  const paths = fields.map(row => object(row).path);
  check(paths.every(path => typeof path === 'string'));
  check(paths.every((path, i) => i === 0 || (paths[i - 1] as string) < (path as string)));
  const byPath = new Map(paths.map((path, i) => [path, fields[i]]));
  const indexByPath = new Map(paths.map((path, i) => [path, i]));
  for (const [path, spec] of fixed) validateField(byPath.get(path), path, spec,
    nonIntegerTokens, `/publication/supplied/fields/${indexByPath.get(path)}`);
  const definitions = new Map<string, Set<string>>();
  for (const path of paths as string[]) {
    if (fixed.has(path)) continue;
    const match = /^\/strategies\/([A-Za-z0-9_-]{1,128})\/(.+)$/.exec(path);
    check(match);
    const suffixes = definitions.get(match![1]) ?? new Set<string>();
    suffixes.add(match![2]); definitions.set(match![1], suffixes);
  }
  check(definitions.size <= 1024);
  for (const [sid, suffixes] of definitions) {
    const root = `/strategies/${sid}/`;
    const type = object(byPath.get(root + 'type'));
    const unknown = type.reason === 'unknown_strategy_type';
    const expected = unknown ? ['enabled_live', 'default_allocation', 'enabled_backtest', 'type'] : [...strategies.keys()];
    check(expected.length === suffixes.size && expected.every(suffix => suffixes.has(suffix)));
    for (const suffix of expected) {
      const path = root + suffix;
      const spec = unknown && suffix === 'type'
        ? ['unsupported_in_profile', 'unknown_strategy_type', 'no_active_profile_reader',
          'enum_string', 'strategy_type', 'not_projected', 'omitted']
        : strategies.get(suffix)!;
      validateField(byPath.get(path), path, spec, nonIntegerTokens,
        `/publication/supplied/fields/${indexByPath.get(path)}`,
        spec[5] === 'not_projected' ? 'omitted' : undefined);
    }
  }
  check(fields.length === fixed.size + [...definitions.values()].reduce((n, set) => n + set.size, 0));
  return { supplied, definitions, byPath };
};
const validateStage = (raw: unknown, nonIntegerTokens: Set<string>, jsonPath: string): void => {
  const stage = keys(raw, Object.keys(trendKinds));
  for (const [key, kind] of Object.entries(trendKinds)) {
    valueIs(stage[key], kind, '', nonIntegerTokens, `${jsonPath}/${key}`);
  }
};

type JsonScan = { nonIntegerTokens: Set<string>; unsafeIntegerTokens: Set<string>; publicationBytes: number | null };
const jsonPointer = (base: string, key: string): string =>
  `${base}/${key.replace(/~/g, '~0').replace(/\//g, '~1')}`;

// One lexical pass keeps numeric spelling and the exact child span before JSON.parse rounds numbers.
const scanJson = (raw: string): JsonScan => {
  const nonIntegerTokens = new Set<string>();
  const unsafeIntegerTokens = new Set<string>();
  let publicationBytes: number | null = null;
  let i = 0;
  const numberToken = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
  const space = () => {
    while (raw[i] === ' ' || raw[i] === '\n' || raw[i] === '\r' || raw[i] === '\t') i++;
  };
  const readString = (): string => {
    if (raw[i] !== '"') return fail();
    const start = i++;
    let escaped = false;
    while (i < raw.length) {
      const char = raw[i++];
      if (escaped) { escaped = false; continue; }
      if (char === '\\') { escaped = true; continue; }
      if (char === '"') return JSON.parse(raw.slice(start, i)) as string;
    }
    return fail();
  };
  const value = (pointer: string): void => {
    space();
    const start = i;
    if (raw[i] === '{') {
      i++; space();
      const seen = new Set<string>();
      if (raw[i] !== '}') {
        while (true) {
          const key = readString();
          if (seen.has(key)) fail();
          seen.add(key);
          space(); if (raw[i++] !== ':') fail();
          value(jsonPointer(pointer, key));
          space();
          if (raw[i] !== ',') break;
          i++; space();
        }
      }
      if (raw[i++] !== '}') fail();
    } else if (raw[i] === '[') {
      i++; space();
      let index = 0;
      if (raw[i] !== ']') {
        while (true) {
          value(`${pointer}/${index++}`);
          space();
          if (raw[i] !== ',') break;
          i++; space();
        }
      }
      if (raw[i++] !== ']') fail();
    } else if (raw[i] === '"') {
      readString();
    } else if (raw.startsWith('true', i)) i += 4;
    else if (raw.startsWith('false', i)) i += 5;
    else if (raw.startsWith('null', i)) i += 4;
    else {
      numberToken.lastIndex = i;
      const match = numberToken.exec(raw);
      if (!match) fail();
      const token = match![0];
      const parsed = Number(token);
      if (Number.isFinite(parsed) && Number.isInteger(parsed) && !Number.isSafeInteger(parsed)) {
        unsafeIntegerTokens.add(pointer);
      }
      if (/[.eE]/.test(token)) nonIntegerTokens.add(pointer);
      i = numberToken.lastIndex;
    }
    if (pointer === '/publication') {
      if (i - start > 2 * 1024 * 1024) fail();
      publicationBytes = new TextEncoder().encode(raw.slice(start, i)).byteLength;
      if (publicationBytes > 2 * 1024 * 1024) fail();
    }
  };
  try {
    value(''); space();
    if (i !== raw.length) fail();
  } catch (error) {
    if (error instanceof UnsupportedNumericRepresentationError || error instanceof InspectionProtocolError) throw error;
    fail();
  }
  return { nonIntegerTokens, unsafeIntegerTokens, publicationBytes };
};

export function parseConfigurationInspection(raw: string, registryId: string, portfolioId: string): InspectionResponse {
  const lexical = scanJson(raw);
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { return fail(); }
  // Route only the lexical refusal here; the full publication and child still require validation.
  const candidate = parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
    ? (parsed as RecordValue).publication : null;
  const candidateVersion = candidate !== null && typeof candidate === 'object' && !Array.isArray(candidate)
    ? (candidate as RecordValue).publication_schema_version : null;
  for (const pointer of lexical.unsafeIntegerTokens) {
    const permittedChild = (candidateVersion === 2 && pointer.startsWith('/publication/consumption/')) ||
      (candidateVersion === 3 && pointer.startsWith('/publication/equity_run_consumption/'));
    if (!permittedChild) {
      throw new UnsupportedNumericRepresentationError();
    }
  }
  const result = keys(parsed, ['api_version', 'scope', 'read_at', 'status', 'reason', 'publication']);
  const scope = keys(result.scope, ['registry_id', 'portfolio_id']);
  check(result.api_version === 1 && !lexical.nonIntegerTokens.has('/api_version') &&
    scope.registry_id === registryId && scope.portfolio_id === portfolioId);
  const readAt = timestamp(result.read_at);
  check(compareUtc(readAt, new Date(Date.now()).toISOString()) <= 0);
  check(result.status === 'available' || result.status === 'unavailable');
  if (result.status === 'unavailable' && result.publication === null) {
    check(unavailableReasons.has(result.reason as string));
    return result as unknown as InspectionResponse;
  }
  const pub = keys(result.publication, candidateVersion === 3
    ? ['publication_schema_version', 'profile', 'authority', 'stream', 'identity', 'captured_at',
       'publication_recorded_at', 'status', 'reason', 'equity_run_consumption']
    : ['publication_schema_version', 'profile', 'authority', 'stream',
    'identity', 'captured_at', 'publication_recorded_at', 'status', 'reason', 'supplied',
    'selected_trend', 'consumption']);
  check(lexical.publicationBytes !== null && lexical.publicationBytes <= 2 * 1024 * 1024);
  check((pub.publication_schema_version === 1 || pub.publication_schema_version === 2 || pub.publication_schema_version === 3) &&
    !lexical.nonIntegerTokens.has('/publication/publication_schema_version') &&
    pub.profile === (pub.publication_schema_version === 3 ? 'live_equity_mean_reversion' : PROFILE) &&
    pub.authority === 'inspection_only' && pub.stream === 'system');
  // The scanner only deferred child tokens; no v2 value is admitted until this succeeds.
  if (pub.publication_schema_version === 2) {
    try { validateConsumptionV2(pub.consumption); } catch { fail(); }
    check(new TextEncoder().encode(JSON.stringify(pub)).byteLength <= 2 * 1024 * 1024);
  }
  const identity = keys(pub.identity, ['registry_id', 'registry_revision', 'engine_strategy_id',
    'portfolio_id', 'run_date', 'capture_id', 'publication_id', 'runtime_attempt_id',
    'producer_version', 'control_mode']);
  check(typeof identity.registry_id === 'string' && id.test(identity.registry_id));
  check(typeof identity.engine_strategy_id === 'string' && id.test(identity.engine_strategy_id));
  check(typeof identity.portfolio_id === 'string' && id.test(identity.portfolio_id));
  check(identity.registry_id === registryId && identity.portfolio_id === portfolioId);
  check(integer(identity.registry_revision) &&
    !lexical.nonIntegerTokens.has('/publication/identity/registry_revision') &&
    (identity.registry_revision as number) >= 0);
  check(typeof identity.run_date === 'string' && /^\d{4}-\d\d-\d\d$/.test(identity.run_date));
  const runDate = identity.run_date as string;
  check(validDate(Number(runDate.slice(0, 4)), Number(runDate.slice(5, 7)), Number(runDate.slice(8, 10))) &&
    compareUtc(`${runDate}T00:00:00Z`, readAt) <= 0);
  check(typeof identity.capture_id === 'string' && uuid.test(identity.capture_id));
  check(identity.capture_id === identity.publication_id);
  check(typeof identity.producer_version === 'string' && build.test(identity.producer_version));
  check(identity.control_mode === 'controlled' || identity.control_mode === 'uncontrolled');
  check(identity.control_mode === 'controlled'
    ? identity.runtime_attempt_id === identity.publication_id
    : identity.runtime_attempt_id === null);
  const captured = timestamp(pub.captured_at);
  const recorded = timestamp(pub.publication_recorded_at);
  check(compareUtc(captured, recorded) <= 0 && compareUtc(recorded, readAt) <= 0 &&
    compareUtc(`${runDate}T00:00:00Z`, recorded) <= 0);
  if (pub.publication_schema_version === 3) {
    check(identity.engine_strategy_id === 'LIVE_EQUITY_MEAN_REVERSION');
    try {
      validateEquityRunConsumption(pub.equity_run_consumption, {
        portfolio_id: portfolioId, strategy_id: 'LIVE_EQUITY_MEAN_REVERSION',
        strategy_name: 'EQUITY_MEAN_REVERSION', date: runDate,
      }, lexical.nonIntegerTokens);
    } catch { fail(); }
    const equity = pub.equity_run_consumption as EquityRunConsumption;
    check(pub.status === result.status && pub.reason === result.reason &&
      pub.status === (equity.available ? 'available' : 'unavailable') &&
      pub.reason === (equity.available ? 'none' : 'consumption_unavailable'));
    check(!equity.available || identity.producer_version !== 'unversioned');
    return result as unknown as InspectionResponse;
  }
  if (pub.publication_schema_version === 1) {
    const consumption = keys(pub.consumption, ['status']);
    check(consumption.status === 'not_collected');
  }
  check(pub.status === result.status && pub.reason === result.reason);
  if (pub.status === 'unavailable') {
    check(captureReasons.has(pub.reason as string) && pub.supplied === null && pub.selected_trend === null);
    check(identity.producer_version !== 'unversioned' || pub.reason === 'capture_failed');
    return result as unknown as InspectionResponse;
  }
  check(pub.status === 'available' && pub.reason === 'none' && identity.producer_version !== 'unversioned');
  const { definitions, byPath } = validateSupplied(pub.supplied, lexical.nonIntegerTokens);
  const trend = keys(pub.selected_trend, ['schema_version', 'provenance', 'slow_concentration_override', 'strategies']);
  check(trend.schema_version === 1 &&
    !lexical.nonIntegerTokens.has('/publication/selected_trend/schema_version') &&
    trend.provenance === 'shared_resolver_same_inputs');
  const override = object(trend.slow_concentration_override);
  if (override.state === 'absent') keys(override, ['state']);
  else { keys(override, ['state', 'value']); check(override.state === 'present');
    valueIs(override.value, 'number', '', lexical.nonIntegerTokens,
      '/publication/selected_trend/slow_concentration_override/value'); }
  check(Array.isArray(trend.strategies) && trend.strategies.length <= definitions.size);
  const selected = new Set<string>();
  for (const [index, rawItem] of (trend.strategies as unknown[]).entries()) {
    const item = keys(rawItem, ['strategy_id', 'strategy_type', 'selected_allocation',
      'factory_resolved', 'constructor_normalized']);
    check(typeof item.strategy_id === 'string' && id.test(item.strategy_id) &&
      definitions.has(item.strategy_id) && !selected.has(item.strategy_id));
    const sid = item.strategy_id as string;
    selected.add(sid);
    const typeRow = object(byPath.get(`/strategies/${sid}/type`));
    check(typeRow.value_state === 'included'
      ? item.strategy_type === typeRow.value && types.has(item.strategy_type as string)
      : typeRow.value_state === 'absent_in_input' && item.strategy_type === 'TrendFollowingStrategy');
    const enabled = object(byPath.get(`/strategies/${sid}/enabled_live`));
    check(enabled.value_state === 'included' && enabled.value === true);
    valueIs(item.selected_allocation, 'number', '', lexical.nonIntegerTokens,
      `/publication/selected_trend/strategies/${index}/selected_allocation`);
    validateStage(item.factory_resolved, lexical.nonIntegerTokens,
      `/publication/selected_trend/strategies/${index}/factory_resolved`);
    validateStage(item.constructor_normalized, lexical.nonIntegerTokens,
      `/publication/selected_trend/strategies/${index}/constructor_normalized`);
  }
  return result as unknown as InspectionResponse;
}

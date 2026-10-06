/** Pure, fail-closed qt-workflow/v1 display and state boundary. */
import { parseFixedDecimal8 } from '../numbers/fixedDecimal8';
import { normalizeDecimal8Input } from './positionEdit';

export type QtComponentKey = {
  portfolio_id: string; strategy_id: string; strategy_name: string;
  date: string; symbol: string; portfolio_type: string;
};
export type QtAssetType = 'EQUITY' | 'FUTURE';
export type QtEmptyOwnerChoice = {
  schema_version: 'qt-empty-owner-choice/v2'; model_publication_id: string;
  owner_document_digest: string; configured_owner_names: [string];
};
export type QtSelectionRow = {
  key: QtComponentKey; quantity_exact: string;
  basis_status: 'preserved_source' | 'unfilled'; average_price_exact: string | null;
  asset_type: QtAssetType; editable: boolean;
  origin: 'verified_model_seed' | 'verified_qt_decision' | 'reconciled_legacy_draft' | 'qt_draft' | 'immutable';
};
export type QtProposal = {
  schema_version: 'qt-workflow/v1' | 'qt-workflow/v2'; book_id: string; source_day: string;
  empty_owner?: QtEmptyOwnerChoice;
  capability: { required: boolean; available: boolean; version: number | null };
  workflow_state: 'ready' | 'provenance_unresolved' | 'workflow_unavailable';
  read_only_reason: string | null;
  action_grants: { can_save_draft: boolean; can_confirm: boolean; can_approve: boolean };
  source_digest: string | null; provenance_digest: string | null;
  seed_publication_id: string | null; seed_rows: QtSelectionRow[]; saved_qt_rows: QtSelectionRow[];
};
export type QtDraft = {
  schema_version: 'qt-workflow/v1' | 'qt-workflow/v2'; book_id: string; source_day: string;
  empty_owner?: QtEmptyOwnerChoice;
  successor?: { decision_id: string; attempt_id: string; preview_id: string; publication_digest: string };
  state: 'absent' | 'saved' | 'consumed' | 'stale' | 'provenance_unresolved';
  draft_id: string | null; draft_revision: number; draft_digest: string | null;
  source_digest: string | null; provenance_digest: string | null; rationale: string | null; selection_rows: QtSelectionRow[];
};
export type QtEvaluation = {
  optimizer: {
    status: string; evaluated_book_digest: string | null;
    aggregate_bindings: Array<{ instrument_type: string; symbol: string; component_keys: QtComponentKey[];
      previous_net_quantity_exact: string; proposed_net_quantity_exact: string }>;
    current_weights: QtWeight[]; target_weights: QtWeight[]; solved_weights: QtWeight[];
    trace: string[]; cost_penalty: string | null; diagnostics: string[]; config_source_id: string | null;
  };
  selected_risk: {
    status: string; evaluated_book_digest: string | null; passed: boolean | null;
    breaches: Array<{ code: string; limit_diagnostic: string | null; actual_diagnostic: string | null }>;
    metrics: Array<{ code: string; value_diagnostic: string | null; unit: string; source_id: string | null }>;
    config_source_id: string | null; market_snapshot_id: string | null; diagnostics: string[];
  };
  selected_costs: {
    status: string; evaluated_book_digest: string | null;
    by_component: Array<{ key: QtComponentKey; prior_quantity_exact: string;
      selected_quantity_exact: string; cash_cost_exact: string; source_id: string | null }>;
    total_exact: string | null; diagnostics: string[];
  };
};
export type QtWeight = { instrument_type: string; symbol: string; weight_diagnostic: string };
export type QtPreview = {
  schema_version: 'qt-workflow/v1'; book_id: string; source_day: string; preview_id: string;
  payload_digest: string; optimizer_book_digest: string; selected_book_digest: string;
  draft_id: string; draft_revision: number; source_digest: string; provenance_digest: string;
  read_set_digest: string; availability: 'ready' | 'unavailable'; confirmable: boolean;
  requires_override: boolean; selection_rows: QtSelectionRow[];
  unavailable_reasons: string[]; evaluation: QtEvaluation;
};
export type QtDecision = {
  schema_version: 'qt-workflow/v1'; book_id: string; preview_id: string; decision_id: string;
  request_id: string | null; status: 'pending_override' | 'confirmed_decision';
  selected_book_digest: string; read_set_digest: string;
  approvals: Array<{ person_id: string; display_label: string; user_id: string; approved_at: string }>;
  approvals_count: number; required_approvals: 2; can_approve: boolean;
  receipt: null | { status: 'pending' | 'processed' | 'failed'; published_book_digest: string | null;
    report_eligibility: { status: 'eligible' | 'unavailable'; reason_codes: string[]; row_manifest_digest: string | null } };
  report_ready: boolean; report_blocked_reasons: string[];
};

const keyFields = ['portfolio_id', 'strategy_id', 'strategy_name', 'date', 'symbol', 'portfolio_type'] as const;
const hex64 = /^[0-9a-f]{64}$/;
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const diagnosticPattern = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;
const accountPattern = /^(?:0|[1-9][0-9]*)$/;
const utcStamp = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/;
const approverIds = new Set(['john_riley', 'xander_robbins', 'hemdutt_rao', 'dominick_dupuoy']);

function fail(): never { throw new Error('invalid_qt_payload'); }
function object(value: unknown, fields: readonly string[]): Record<string, unknown> {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) fail();
  const item = value as Record<string, unknown>;
  if (Object.keys(item).length !== fields.length || fields.some(field => !Object.prototype.hasOwnProperty.call(item, field))) fail();
  return item;
}
function array(value: unknown): unknown[] {
  if (!Array.isArray(value) || value.length > 4096) fail();
  return value;
}
function string(value: unknown, nonempty = true): string {
  if (typeof value !== 'string' || value.length > 4096 || (nonempty && !value)) fail();
  try { encodeURIComponent(value); } catch { fail(); }
  return value;
}
function optionalString(value: unknown): string | null { return value === null ? null : string(value); }
function bool(value: unknown): boolean { if (typeof value !== 'boolean') fail(); return value; }
function integer(value: unknown, minimum = 0): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < minimum) fail();
  return value;
}
function literal<T extends string>(value: unknown, choices: readonly T[]): T {
  if (typeof value !== 'string' || !choices.includes(value as T)) fail();
  return value as T;
}
function digest(value: unknown): string { const result = string(value); if (!hex64.test(result)) fail(); return result; }
function optionalDigest(value: unknown): string | null { return value === null ? null : digest(value); }
function id(value: unknown): string { const result = string(value); if (!uuid.test(result)) fail(); return result; }
function optionalId(value: unknown): string | null { return value === null ? null : id(value); }
function exact(value: unknown): string { return parseFixedDecimal8(value); }
function optionalExact(value: unknown): string | null { return value === null ? null : exact(value); }
function diagnostic(value: unknown): string {
  const result = string(value);
  if (!diagnosticPattern.test(result)) fail();
  const numeric = Number(result);
  if (!Number.isFinite(numeric) || (numeric === 0 && !/^[-]?0(?:\.0+)?(?:[eE][+-]?[0-9]+)?$/.test(result))) fail();
  return result;
}
function optionalDiagnostic(value: unknown): string | null { return value === null ? null : diagnostic(value); }
function date(value: unknown): string {
  const result = string(value);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(result) || Number.isNaN(Date.parse(`${result}T00:00:00Z`)) ||
      new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result) fail();
  return result;
}
function strings(value: unknown): string[] { return array(value).map(item => string(item, false)); }
function schema(value: unknown): 'qt-workflow/v1' { return literal(value, ['qt-workflow/v1']); }
function choiceObject(value: unknown, fields: readonly string[], allowSuccessor = false): Record<string, unknown> {
  const version = (value as { schema_version?: unknown } | null)?.schema_version;
  const consumed = allowSuccessor && (value as { state?: unknown } | null)?.state === 'consumed';
  const item = object(value, version === 'qt-workflow/v2' ?
    [...fields, 'empty_owner', ...(consumed ? ['successor'] : [])] : fields);
  literal(item.schema_version, ['qt-workflow/v1', 'qt-workflow/v2']);
  return item;
}
function emptyOwner(value: unknown): QtEmptyOwnerChoice {
  const item = object(value, ['schema_version', 'model_publication_id', 'owner_document_digest', 'configured_owner_names']);
  literal(item.schema_version, ['qt-empty-owner-choice/v2']);
  id(item.model_publication_id); digest(item.owner_document_digest);
  if (item.model_publication_id === '00000000-0000-0000-0000-000000000000') fail();
  const owners = array(item.configured_owner_names);
  if (owners.length !== 1) fail();
  const owner = string(owners[0]);
  if (!owner.trim() || new TextEncoder().encode(owner).length > 256) fail();
  return item as QtEmptyOwnerChoice;
}
function key(value: unknown): QtComponentKey {
  const item = object(value, keyFields);
  for (const field of keyFields) string(item[field]);
  date(item.date);
  return item as QtComponentKey;
}
export function qtComponentKey(value: QtComponentKey): string {
  return JSON.stringify(keyFields.map(field => value[field]));
}
export function qtContextKey(actorId: string, bookId: string, sourceDay: string): string {
  return JSON.stringify([actorId, bookId, sourceDay]);
}
export function normalizeQtSelectionInput(value: string, assetType: QtAssetType): string {
  const quantity = normalizeDecimal8Input(value);
  if (assetType === 'FUTURE' && quantity.includes('.')) fail();
  if (assetType !== 'FUTURE' && assetType !== 'EQUITY') fail();
  return quantity;
}
function rows(value: unknown, book: string, day: string, streams: readonly string[]): QtSelectionRow[] {
  const seen = new Set<string>();
  return array(value).map(raw => {
    const item = object(raw, ['key', 'quantity_exact', 'basis_status', 'average_price_exact', 'asset_type', 'editable', 'origin']);
    const component = key(item.key);
    if (component.portfolio_id !== book || component.date !== day || !streams.includes(component.portfolio_type)) fail();
    const identity = qtComponentKey(component);
    if (seen.has(identity)) fail();
    seen.add(identity);
    const quantity = exact(item.quantity_exact);
    const assetType = literal(item.asset_type, ['EQUITY', 'FUTURE']);
    if (assetType === 'FUTURE' && quantity.includes('.')) fail();
    const basis = literal(item.basis_status, ['preserved_source', 'unfilled']);
    const price = optionalExact(item.average_price_exact);
    if ((basis === 'unfilled') !== (price === null) || (price !== null && price.startsWith('-'))) fail();
    bool(item.editable);
    literal(item.origin, ['verified_model_seed', 'verified_qt_decision', 'reconciled_legacy_draft', 'qt_draft', 'immutable']);
    return item as QtSelectionRow;
  });
}
function detached<T>(value: T): T { return structuredClone(value); }

export function decodeQtProposal(value: unknown): QtProposal {
  const item = choiceObject(value, ['schema_version', 'book_id', 'source_day', 'capability', 'workflow_state', 'read_only_reason', 'action_grants', 'source_digest', 'provenance_digest', 'seed_publication_id', 'seed_rows', 'saved_qt_rows']);
  const book = string(item.book_id); const day = date(item.source_day);
  const capability = object(item.capability, ['required', 'available', 'version']);
  bool(capability.required); bool(capability.available);
  if (capability.version !== null) integer(capability.version, 1);
  const workflow = literal(item.workflow_state, ['ready', 'provenance_unresolved', 'workflow_unavailable']);
  optionalString(item.read_only_reason);
  const grants = object(item.action_grants, ['can_save_draft', 'can_confirm', 'can_approve']);
  Object.values(grants).forEach(bool);
  optionalDigest(item.source_digest); optionalDigest(item.provenance_digest); optionalId(item.seed_publication_id);
  const seed = rows(item.seed_rows, book, day, ['qt_proposal']);
  const saved = rows(item.saved_qt_rows, book, day, ['qt']);
  if (seed.some(row => row.origin !== 'verified_model_seed')) fail();
  if (workflow === 'ready' && (!capability.available || !item.seed_publication_id || !item.source_digest || !item.provenance_digest)) fail();
  if (workflow !== 'ready' && (grants.can_save_draft || grants.can_confirm)) fail();
  if (item.schema_version === 'qt-workflow/v2') {
    const owner = emptyOwner(item.empty_owner);
    if (workflow !== 'ready' || !capability.required || seed.length || saved.length ||
        owner.model_publication_id !== item.seed_publication_id) fail();
  }
  return detached(item as QtProposal);
}

export function decodeQtDraft(value: unknown): QtDraft {
  const legacy = value !== null && typeof value === 'object' && !Array.isArray(value) &&
    !Object.prototype.hasOwnProperty.call(value, 'rationale') ? { ...value, rationale: null } : value;
  const item = choiceObject(legacy, ['schema_version', 'book_id', 'source_day', 'state', 'draft_id', 'draft_revision', 'draft_digest', 'source_digest', 'provenance_digest', 'rationale', 'selection_rows'], true);
  const book = string(item.book_id); const day = date(item.source_day);
  const state = literal(item.state, item.schema_version === 'qt-workflow/v2' ?
    ['absent', 'saved', 'consumed'] : ['absent', 'saved', 'stale', 'provenance_unresolved']);
  optionalId(item.draft_id); const revision = integer(item.draft_revision);
  optionalDigest(item.draft_digest); optionalDigest(item.source_digest); optionalDigest(item.provenance_digest);
  const rationale = optionalString(item.rationale);
  if (rationale !== null && (!rationale.trim() || rationale !== rationale.trim() || new TextEncoder().encode(rationale).length > 1000)) fail();
  const selection = rows(item.selection_rows, book, day, ['qt_proposal', 'qt']);
  if (state === 'absent' && (revision !== 0 || item.draft_id !== null || item.draft_digest !== null)) fail();
  if ((state === 'saved' || state === 'consumed') && (revision < 1 || !item.draft_id || !item.draft_digest || !item.source_digest || !item.provenance_digest)) fail();
  if (item.schema_version === 'qt-workflow/v2') {
    emptyOwner(item.empty_owner);
    if (selection.length || !item.source_digest || !item.provenance_digest) fail();
    if (state === 'consumed') {
      const successor = object(item.successor, ['decision_id', 'attempt_id', 'preview_id', 'publication_digest']);
      for (const field of ['decision_id', 'attempt_id', 'preview_id']) {
        id(successor[field]);
        if (successor[field] === '00000000-0000-0000-0000-000000000000') fail();
      }
      digest(successor.publication_digest);
    }
  }
  return detached(item as QtDraft);
}

export function qtEmptyOwnerMatches(proposal: QtProposal | null, draft: QtDraft | null): boolean {
  const owner = proposal?.empty_owner;
  const selected = draft?.empty_owner;
  return proposal?.schema_version === 'qt-workflow/v2' && draft?.schema_version === 'qt-workflow/v2' &&
    !!owner && !!selected && proposal.workflow_state === 'ready' &&
    (draft.state === 'absent' || draft.state === 'saved' || draft.state === 'consumed') &&
    proposal.book_id === draft.book_id && proposal.source_day === draft.source_day &&
    !!proposal.source_digest && proposal.source_digest === draft.source_digest &&
    !!proposal.provenance_digest && proposal.provenance_digest === draft.provenance_digest &&
    !proposal.seed_rows.length && !proposal.saved_qt_rows.length && !draft.selection_rows.length &&
    owner.model_publication_id === proposal.seed_publication_id &&
    owner.model_publication_id === selected.model_publication_id &&
    owner.owner_document_digest === selected.owner_document_digest &&
    owner.configured_owner_names.length === 1 && selected.configured_owner_names.length === 1 &&
    owner.configured_owner_names[0] === selected.configured_owner_names[0];
}
function choiceAuthorityMatches(proposal: QtProposal | null, draft: QtDraft | null): boolean {
  return (proposal?.schema_version !== 'qt-workflow/v2' && draft?.schema_version !== 'qt-workflow/v2') ||
    qtEmptyOwnerMatches(proposal, draft);
}
function emptyOwnerIdentity(proposal: QtProposal): string {
  return JSON.stringify([proposal.schema_version, proposal.empty_owner?.model_publication_id,
    proposal.empty_owner?.owner_document_digest, proposal.empty_owner?.configured_owner_names]);
}

function weights(value: unknown): QtWeight[] {
  return array(value).map(raw => {
    const item = object(raw, ['instrument_type', 'symbol', 'weight_diagnostic']);
    string(item.instrument_type); string(item.symbol); diagnostic(item.weight_diagnostic);
    return item as QtWeight;
  });
}
function evaluation(value: unknown, book: string, day: string): QtEvaluation {
  const item = object(value, ['optimizer', 'selected_risk', 'selected_costs']);
  const optimizer = object(item.optimizer, ['status', 'evaluated_book_digest', 'aggregate_bindings', 'current_weights', 'target_weights', 'solved_weights', 'trace', 'cost_penalty', 'diagnostics', 'config_source_id']);
  literal(optimizer.status, ['evaluated', 'disabled', 'unavailable', 'failed', 'partial']);
  optionalDigest(optimizer.evaluated_book_digest);
  const bindingIds = new Set<string>();
  array(optimizer.aggregate_bindings).forEach(raw => {
    const binding = object(raw, ['instrument_type', 'symbol', 'component_keys', 'previous_net_quantity_exact', 'proposed_net_quantity_exact']);
    const instrument = string(binding.instrument_type); const symbol = string(binding.symbol);
    const scope = JSON.stringify([instrument, symbol]);
    if (bindingIds.has(scope)) fail();
    bindingIds.add(scope);
    const components = new Set<string>();
    array(binding.component_keys).forEach(rawKey => {
      const component = key(rawKey);
      if (component.portfolio_id !== book || component.date !== day || component.portfolio_type !== 'qt_proposal' || component.symbol !== symbol) fail();
      const identity = qtComponentKey(component);
      if (components.has(identity)) fail();
      components.add(identity);
    });
    exact(binding.previous_net_quantity_exact); exact(binding.proposed_net_quantity_exact);
  });
  weights(optimizer.current_weights); weights(optimizer.target_weights); weights(optimizer.solved_weights);
  strings(optimizer.trace); optionalDiagnostic(optimizer.cost_penalty);
  strings(optimizer.diagnostics); optionalString(optimizer.config_source_id);

  const risk = object(item.selected_risk, ['status', 'evaluated_book_digest', 'passed', 'breaches', 'metrics', 'config_source_id', 'market_snapshot_id', 'diagnostics']);
  literal(risk.status, ['evaluated', 'disabled', 'unavailable', 'failed', 'partial']);
  optionalDigest(risk.evaluated_book_digest);
  if (risk.passed !== null) bool(risk.passed);
  array(risk.breaches).forEach(raw => {
    const breach = object(raw, ['code', 'limit_diagnostic', 'actual_diagnostic']);
    string(breach.code); optionalDiagnostic(breach.limit_diagnostic); optionalDiagnostic(breach.actual_diagnostic);
  });
  array(risk.metrics).forEach(raw => {
    const metric = object(raw, ['code', 'value_diagnostic', 'unit', 'source_id']);
    string(metric.code); optionalDiagnostic(metric.value_diagnostic); string(metric.unit); optionalString(metric.source_id);
  });
  optionalString(risk.config_source_id); optionalString(risk.market_snapshot_id); strings(risk.diagnostics);

  const costs = object(item.selected_costs, ['status', 'evaluated_book_digest', 'by_component', 'total_exact', 'diagnostics']);
  literal(costs.status, ['evaluated', 'disabled', 'unavailable', 'failed', 'partial']);
  optionalDigest(costs.evaluated_book_digest);
  const seen = new Set<string>();
  array(costs.by_component).forEach(raw => {
    const component = object(raw, ['key', 'prior_quantity_exact', 'selected_quantity_exact', 'cash_cost_exact', 'source_id']);
    const k = key(component.key);
    if (k.portfolio_id !== book || k.date !== day || !['qt_proposal', 'qt'].includes(k.portfolio_type)) fail();
    const identity = qtComponentKey(k);
    if (seen.has(identity)) fail();
    seen.add(identity);
    exact(component.prior_quantity_exact); exact(component.selected_quantity_exact); exact(component.cash_cost_exact);
    optionalString(component.source_id);
  });
  optionalExact(costs.total_exact); strings(costs.diagnostics);
  return item as QtEvaluation;
}

/* Python's canonical v1 projection sorts object names and full-key arrays. */
const keyedArrays = new Set(['selection_rows', 'seed_rows', 'saved_qt_rows', 'component_keys', 'by_component']);
function canonical(value: unknown, field = ''): unknown {
  if (Array.isArray(value)) {
    const mapped = value.map(item => canonical(item, field));
    if (keyedArrays.has(field)) mapped.sort((a, b) => {
      const ak = ((a as Record<string, unknown>).key ?? a) as QtComponentKey;
      const bk = ((b as Record<string, unknown>).key ?? b) as QtComponentKey;
      return qtComponentKey(ak) < qtComponentKey(bk) ? -1 : qtComponentKey(ak) > qtComponentKey(bk) ? 1 : 0;
    });
    if (field === 'aggregate_bindings') mapped.sort((a, b) => {
      const x = a as { instrument_type: string; symbol: string };
      const y = b as { instrument_type: string; symbol: string };
      const ax = JSON.stringify([x.instrument_type, x.symbol]); const ay = JSON.stringify([y.instrument_type, y.symbol]);
      return ax < ay ? -1 : ax > ay ? 1 : 0;
    });
    return mapped;
  }
  if (value !== null && typeof value === 'object') {
    const item = value as Record<string, unknown>;
    return Object.fromEntries(Object.keys(item).sort().map(name => [name, canonical(item[name], name)]));
  }
  return value;
}
/** Synchronous SHA-256 keeps decoding pure in browser and Node. */
function sha256(message: string): string {
  const data = new TextEncoder().encode(message);
  const bitLength = data.length * 8;
  const size = Math.ceil((data.length + 9) / 64) * 64;
  const bytes = new Uint8Array(size);
  bytes.set(data); bytes[data.length] = 0x80;
  const view = new DataView(bytes.buffer);
  view.setUint32(size - 8, Math.floor(bitLength / 0x100000000));
  view.setUint32(size - 4, bitLength >>> 0);
  const primes: number[] = [];
  for (let n = 2; primes.length < 64; n++) if (primes.every(p => n % p !== 0)) primes.push(n);
  const fractional = (number: number) => Math.floor((number % 1) * 0x100000000) >>> 0;
  const constants = primes.map(p => fractional(Math.cbrt(p)));
  const h = primes.slice(0, 8).map(p => fractional(Math.sqrt(p)));
  const rotate = (x: number, n: number) => (x >>> n) | (x << (32 - n));
  for (let offset = 0; offset < size; offset += 64) {
    const words = new Uint32Array(64);
    for (let i = 0; i < 16; i++) words[i] = view.getUint32(offset + i * 4);
    for (let i = 16; i < 64; i++) {
      const a = words[i - 15]; const b = words[i - 2];
      words[i] = (words[i - 16] + (rotate(a, 7) ^ rotate(a, 18) ^ (a >>> 3)) + words[i - 7] + (rotate(b, 17) ^ rotate(b, 19) ^ (b >>> 10))) >>> 0;
    }
    let [a, b, c, d, e, f, g, j] = h;
    for (let i = 0; i < 64; i++) {
      const s1 = rotate(e, 6) ^ rotate(e, 11) ^ rotate(e, 25);
      const choice = (e & f) ^ (~e & g);
      const t1 = (j + s1 + choice + constants[i] + words[i]) >>> 0;
      const s0 = rotate(a, 2) ^ rotate(a, 13) ^ rotate(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (s0 + majority) >>> 0;
      j = g; g = f; f = e; e = (d + t1) >>> 0; d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    [a, b, c, d, e, f, g, j].forEach((word, i) => { h[i] = (h[i] + word) >>> 0; });
  }
  return h.map(word => word.toString(16).padStart(8, '0')).join('');
}
function hash(value: unknown): string { return sha256(JSON.stringify(canonical(value))); }
function bookDigest(selection: QtSelectionRow[]): string {
  return hash({ selection_rows: selection.map(row => ({
    key: { ...row.key, portfolio_type: 'qt' }, quantity_exact: row.quantity_exact,
  })) });
}
function scaled(value: string): bigint {
  const negative = value.startsWith('-');
  const [integer, fractional = ''] = (negative ? value.slice(1) : value).split('.');
  const magnitude = BigInt(integer) * 100000000n + BigInt(fractional.padEnd(8, '0'));
  return negative ? -magnitude : magnitude;
}

export function decodeQtPreview(value: unknown): QtPreview {
  const item = object(value, ['schema_version', 'book_id', 'source_day', 'preview_id', 'payload_digest', 'optimizer_book_digest', 'selected_book_digest', 'draft_id', 'draft_revision', 'source_digest', 'provenance_digest', 'read_set_digest', 'availability', 'confirmable', 'requires_override', 'selection_rows', 'unavailable_reasons', 'evaluation']);
  schema(item.schema_version); const book = string(item.book_id); const day = date(item.source_day);
  id(item.preview_id); digest(item.payload_digest); digest(item.optimizer_book_digest); digest(item.selected_book_digest);
  id(item.draft_id); integer(item.draft_revision, 1);
  digest(item.source_digest); digest(item.provenance_digest); digest(item.read_set_digest);
  const availability = literal(item.availability, ['ready', 'unavailable']);
  const confirmable = bool(item.confirmable); const override = bool(item.requires_override);
  const selection = rows(item.selection_rows, book, day, ['qt_proposal', 'qt']);
  const reasons = strings(item.unavailable_reasons);
  const evidence = evaluation(item.evaluation, book, day);
  if (bookDigest(selection) !== item.selected_book_digest) fail();
  if (hash(Object.fromEntries(Object.entries(item).filter(([name]) => name !== 'payload_digest'))) !== item.payload_digest) fail();
  if (availability === 'unavailable' && (confirmable || override || reasons.length === 0)) fail();
  if (override && !confirmable) fail();
  const { optimizer, selected_risk: risk, selected_costs: costs } = evidence;
  if (optimizer.status === 'evaluated' && optimizer.evaluated_book_digest !== item.optimizer_book_digest) fail();
  if (risk.status === 'evaluated' && risk.evaluated_book_digest !== item.selected_book_digest) fail();
  if (costs.status === 'evaluated' && costs.evaluated_book_digest !== item.selected_book_digest) fail();
  if (availability === 'ready') {
    if (!confirmable || reasons.length || risk.status !== 'evaluated' || costs.status !== 'evaluated' ||
        risk.passed === null || costs.total_exact === null || !risk.config_source_id || !risk.market_snapshot_id ||
        risk.metrics.some(metric => metric.value_diagnostic === null || !metric.source_id) ||
        risk.breaches.some(breach => breach.limit_diagnostic === null || breach.actual_diagnostic === null) ||
        costs.by_component.some(component => !component.source_id) || risk.passed === override ||
        (risk.breaches.length > 0) !== override) fail();
    const selected = new Map(selection.filter(row => row.editable).map(row => [qtComponentKey(row.key), row.quantity_exact]));
    const costed = new Map(costs.by_component.map(row => [qtComponentKey(row.key), row.selected_quantity_exact]));
    if (selected.size !== costed.size || [...selected].some(([k, qty]) => costed.get(k) !== qty)) fail();
    if (costs.by_component.reduce((sum, row) => sum + scaled(row.cash_cost_exact), 0n) !== scaled(costs.total_exact)) fail();
  }
  return detached(item as QtPreview);
}

export function decodeQtDecision(value: unknown): QtDecision {
  const item = object(value, ['schema_version', 'book_id', 'preview_id', 'decision_id', 'request_id', 'status', 'selected_book_digest', 'read_set_digest', 'approvals', 'approvals_count', 'required_approvals', 'can_approve', 'receipt', 'report_ready', 'report_blocked_reasons']);
  schema(item.schema_version); string(item.book_id); id(item.preview_id); id(item.decision_id); optionalId(item.request_id);
  const status = literal(item.status, ['pending_override', 'confirmed_decision']);
  digest(item.selected_book_digest); digest(item.read_set_digest);
  const people = new Set<string>(); const users = new Set<string>();
  const approvals = array(item.approvals);
  approvals.forEach(raw => {
    const approval = object(raw, ['person_id', 'display_label', 'user_id', 'approved_at']);
    const person = string(approval.person_id); string(approval.display_label);
    const user = string(approval.user_id); const stamp = string(approval.approved_at);
    const parsed = new Date(stamp);
    if (!approverIds.has(person) || people.has(person) || !accountPattern.test(user) || users.has(user) ||
        BigInt(user) > 9223372036854775807n || !utcStamp.test(stamp) || Number.isNaN(parsed.valueOf()) ||
        parsed.toISOString().slice(0, 19) !== stamp.slice(0, 19)) fail();
    people.add(person); users.add(user);
  });
  const count = integer(item.approvals_count); if (count !== approvals.length || item.required_approvals !== 2) fail();
  bool(item.can_approve); const ready = bool(item.report_ready); const reasons = strings(item.report_blocked_reasons);
  let receipt: Record<string, unknown> | null = null;
  if (item.receipt !== null) {
    receipt = object(item.receipt, ['status', 'published_book_digest', 'report_eligibility']);
    literal(receipt.status, ['pending', 'processed', 'failed']);
    optionalDigest(receipt.published_book_digest);
    const eligibility = object(receipt.report_eligibility, ['status', 'reason_codes', 'row_manifest_digest']);
    literal(eligibility.status, ['eligible', 'unavailable']);
    strings(eligibility.reason_codes); optionalDigest(eligibility.row_manifest_digest);
    if (receipt.status === 'processed' && receipt.published_book_digest !== item.selected_book_digest) fail();
    if (receipt.status !== 'processed' && eligibility.status === 'eligible') fail();
  }
  if (status === 'pending_override' && (!item.request_id || count >= 2 || receipt !== null || ready)) fail();
  if (status === 'confirmed_decision' && item.request_id !== null && count !== 2) fail();
  if (ready) {
    const eligibility = receipt?.report_eligibility as Record<string, unknown> | undefined;
    if (!receipt || receipt.status !== 'processed' || receipt.published_book_digest !== item.selected_book_digest ||
        eligibility?.status !== 'eligible' || eligibility.row_manifest_digest === null || reasons.length) fail();
  } else if (reasons.length === 0) fail();
  return detached(item as QtDecision);
}

export type QtBookDecision = { schema_version: 'qt-workflow/v1'; book_id: string; source_day: string;
  decision: QtDecision | null; preview: QtPreview | null };

export function qtDecisionMatchesPreview(decision: QtDecision, preview: QtPreview): boolean {
  return decision.book_id === preview.book_id && decision.preview_id === preview.preview_id &&
    decision.selected_book_digest === preview.selected_book_digest && decision.read_set_digest === preview.read_set_digest &&
    preview.availability === 'ready' && preview.confirmable &&
    preview.requires_override === (decision.request_id !== null) &&
    (decision.status !== 'confirmed_decision' || !preview.requires_override ||
      (decision.approvals_count === 2 && decision.approvals.length === 2));
}

export function decodeQtBookDecision(value: unknown): QtBookDecision {
  const item = object(value, ['schema_version', 'book_id', 'source_day', 'decision', 'preview']);
  schema(item.schema_version);
  const book = string(item.book_id); const day = date(item.source_day);
  if (item.decision === null && item.preview === null) return detached(item as QtBookDecision);
  if (item.decision === null || item.preview === null) fail();
  const decision = decodeQtDecision(item.decision); const preview = decodeQtPreview(item.preview);
  if (preview.book_id !== book || preview.source_day !== day || !qtDecisionMatchesPreview(decision, preview)) fail();
  return { schema_version: 'qt-workflow/v1', book_id: book, source_day: day, decision, preview };
}

export type QtPhase = 'loading' | 'editing' | 'saving' | 'evaluating' | 'reviewing' | 'confirming' |
  'uncertain' | 'pending_override' | 'processing' | 'processed' | 'report_blocked' | 'unavailable';
export type QtState = {
  context: string; generation: number; phase: QtPhase;
  selection: Readonly<Record<string, string>>;
  proposal: QtProposal | null; draft: QtDraft | null; preview: QtPreview | null; decision: QtDecision | null;
};
export type QtEvent =
  | { type: 'context_changed'; context: string }
  | { type: 'proposal_loaded'; context: string; generation: number; proposal: QtProposal }
  | { type: 'draft_loaded'; context: string; generation: number; draft: QtDraft }
  | { type: 'edited'; context: string; selection: Readonly<Record<string, string>> }
  | { type: 'save_started' | 'evaluation_started' | 'confirmation_started'; context: string; generation: number }
  | { type: 'draft_saved'; context: string; generation: number; draft: QtDraft }
  | { type: 'preview_loaded'; context: string; generation: number; preview: QtPreview }
  | { type: 'decision_loaded'; context: string; generation: number; decision: QtDecision }
  | { type: 'uncertain' | 'unavailable'; context: string; generation: number };

export function makeQtState(context: string): QtState {
  return { context, generation: 0, phase: 'loading', selection: {}, proposal: null, draft: null, preview: null, decision: null };
}
function scope(state: QtState, book: string, day?: string): boolean {
  const [, contextBook, contextDay] = JSON.parse(state.context) as [string, string, string];
  return contextBook === book && (day === undefined || contextDay === day);
}
function selectionOf(rows: QtSelectionRow[]): Readonly<Record<string, string>> {
  return Object.fromEntries(rows.map(row => [qtComponentKey(row.key), row.quantity_exact]));
}
function sameSelection(selection: Readonly<Record<string, string>>, rows: QtSelectionRow[]): boolean {
  const expected = selectionOf(rows);
  return Object.keys(selection).length === Object.keys(expected).length &&
    Object.entries(expected).every(([identity, quantity]) => selection[identity] === quantity);
}
function canEditUnavailablePreview(state: QtState): boolean {
  const { proposal, draft, preview } = state;
  return state.phase === 'unavailable' && !!proposal && !!draft && !!preview &&
    proposal.workflow_state === 'ready' && proposal.capability.available && proposal.action_grants.can_save_draft &&
    draft.state === 'saved' && preview.availability === 'unavailable' &&
    proposal.book_id === draft.book_id && proposal.book_id === preview.book_id &&
    proposal.source_day === draft.source_day && proposal.source_day === preview.source_day &&
    proposal.source_digest !== null && proposal.source_digest === draft.source_digest &&
    proposal.provenance_digest !== null && proposal.provenance_digest === draft.provenance_digest &&
    preview.draft_id === draft.draft_id && preview.draft_revision === draft.draft_revision &&
    preview.source_digest === draft.source_digest && preview.provenance_digest === draft.provenance_digest &&
    sameSelection(state.selection, draft.selection_rows) && sameSelection(state.selection, preview.selection_rows);
}
export function reduceQtState(state: QtState, event: QtEvent): QtState {
  if (event.type === 'context_changed') return event.context === state.context ? state :
    { ...makeQtState(event.context), generation: state.generation + 1 };
  if (event.context !== state.context) return state;
  if ('generation' in event && event.generation !== state.generation) return state;
  switch (event.type) {
    case 'proposal_loaded':
      if (!scope(state, event.proposal.book_id, event.proposal.source_day)) return state;
      if (state.proposal && (state.proposal.source_digest !== event.proposal.source_digest ||
          state.proposal.provenance_digest !== event.proposal.provenance_digest ||
          state.proposal.seed_publication_id !== event.proposal.seed_publication_id ||
          emptyOwnerIdentity(state.proposal) !== emptyOwnerIdentity(event.proposal))) {
        return { ...state, proposal: event.proposal, selection: {}, draft: null, preview: null, decision: null,
          generation: state.generation + 1, phase: event.proposal.workflow_state === 'ready' ? 'loading' : 'unavailable' };
      }
      return { ...state, proposal: event.proposal, phase: event.proposal.workflow_state === 'ready' ? 'editing' : 'unavailable' };
    case 'draft_loaded':
      if (!choiceAuthorityMatches(state.proposal, event.draft))
        return { ...state, phase: 'unavailable', draft: null, preview: null, decision: null };
      if (!scope(state, event.draft.book_id, event.draft.source_day) ||
          (state.proposal && (state.proposal.source_digest !== event.draft.source_digest || state.proposal.provenance_digest !== event.draft.provenance_digest))) return state;
      if (state.draft && (state.draft.draft_id !== event.draft.draft_id ||
          state.draft.draft_revision !== event.draft.draft_revision || state.draft.draft_digest !== event.draft.draft_digest)) {
        return { ...state, draft: event.draft, selection: selectionOf(event.draft.selection_rows),
          preview: null, decision: null, generation: state.generation + 1,
          phase: event.draft.state === 'saved' || event.draft.state === 'absent' || event.draft.state === 'consumed' ? 'editing' : 'unavailable' };
      }
      return { ...state, draft: event.draft, selection: selectionOf(event.draft.selection_rows),
        phase: event.draft.state === 'saved' || event.draft.state === 'absent' || event.draft.state === 'consumed' ? 'editing' : 'unavailable' };
    case 'edited':
      if (state.phase !== 'editing' && state.phase !== 'reviewing' && state.phase !== 'evaluating' &&
          state.phase !== 'saving' && !canEditUnavailablePreview(state)) return state;
      return { ...state, phase: 'editing', selection: { ...event.selection }, preview: null, decision: null, generation: state.generation + 1 };
    case 'save_started': return state.phase === 'editing' ?
      { ...state, generation: state.generation + 1, phase: 'saving', preview: null, decision: null } : state;
    case 'draft_saved':
      if (!choiceAuthorityMatches(state.proposal, event.draft))
        return { ...state, phase: 'unavailable', draft: null, preview: null, decision: null };
      if (!scope(state, event.draft.book_id, event.draft.source_day) || event.draft.state !== 'saved' ||
          (state.draft && event.draft.draft_revision <= state.draft.draft_revision)) return state;
      return { ...state, phase: 'editing', draft: event.draft, selection: selectionOf(event.draft.selection_rows),
        preview: null, decision: null, generation: state.generation + 1 };
    case 'evaluation_started': return { ...state, generation: state.generation + 1, phase: 'evaluating', preview: null, decision: null };
    case 'preview_loaded':
      if (!scope(state, event.preview.book_id, event.preview.source_day) || !state.draft ||
          event.preview.draft_id !== state.draft.draft_id || event.preview.draft_revision !== state.draft.draft_revision ||
          event.preview.source_digest !== state.draft.source_digest || event.preview.provenance_digest !== state.draft.provenance_digest ||
          !sameSelection(state.selection, event.preview.selection_rows) ||
          !sameSelection(selectionOf(state.draft.selection_rows), event.preview.selection_rows)) return state;
      return { ...state, preview: event.preview, decision: null,
        phase: event.preview.availability === 'ready' ? 'reviewing' : 'unavailable' };
    case 'confirmation_started': return canConfirmQt(state) ? { ...state, generation: state.generation + 1, phase: 'confirming' } : state;
    case 'decision_loaded':
      if (!scope(state, event.decision.book_id) || !state.preview ||
          !qtDecisionMatchesPreview(event.decision, state.preview)) return state;
      return { ...state, decision: event.decision, phase: event.decision.status === 'pending_override' ? 'pending_override' :
        event.decision.receipt?.status === 'processed' ?
          (event.decision.report_ready ? 'processed' : 'report_blocked') :
          event.decision.receipt?.status === 'failed' ? 'unavailable' : 'processing' };
    case 'uncertain': return { ...state, phase: 'uncertain' };
    case 'unavailable': return { ...state, phase: 'unavailable', preview: null, decision: null };
  }
}
export function canConfirmQt(state: QtState): boolean {
  const { proposal, draft, preview } = state;
  return state.phase === 'reviewing' && !!proposal?.action_grants.can_confirm && proposal.workflow_state === 'ready' &&
    choiceAuthorityMatches(proposal, draft) &&
    !!draft && draft.state === 'saved' && !!preview && preview.availability === 'ready' && preview.confirmable &&
    preview.draft_id === draft.draft_id && preview.draft_revision === draft.draft_revision &&
    preview.source_digest === draft.source_digest && preview.provenance_digest === draft.provenance_digest &&
    proposal.source_digest === draft.source_digest && proposal.provenance_digest === draft.provenance_digest &&
    preview.book_id === proposal.book_id && preview.source_day === proposal.source_day &&
    sameSelection(state.selection, preview.selection_rows) &&
    sameSelection(selectionOf(draft.selection_rows), preview.selection_rows);
}

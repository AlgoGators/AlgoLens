"""Finalization-only market in the API successor proof and the lineage loader (isolated predicates).

Equity day 2, lane A1.  ``_prove_successor`` is driven for real; only the parts that are not under test
(the closed successor shape, native recomputation, the anchor record, SQL time parsing) are stubbed.
"""
from datetime import datetime
from hashlib import sha256

import pytest

import algolens.infrastructure.portfolio.qt_equity_finalization_evidence as evidence
import algolens.infrastructure.portfolio.qt_equity_finalization_proof as proof
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes

FIN_SCHEMA = 'qt-equity-finalization-market/v1'
V1_SCHEMA = 'qt-equity-accounting-market/v1'
DECISION = '40000000-0000-4000-8000-000000000001'
FIN = 'b0000000-0000-4000-8000-000000000001'
MARKET = 'b1000000-0000-4000-8000-000000000001'
MODEL = 'a1000000-0000-4000-8000-000000000001'
SEEDS = []
MODEL_ROW = {'portfolio_id': 'EQ', 'source_day': '2026-09-25', 'publication_id': MODEL,
             'system_components': SEEDS, 'seed_digest': qt_digest_v1({'seed_rows': SEEDS})}
OUTPUT = {'schema_version': 'qt-equity-accounting/v1', 'executions': []}


@pytest.fixture()
def isolated(monkeypatch):
    core = proof._original_core
    monkeypatch.setattr(proof, '_closed_successor', lambda successor, decision: None)
    monkeypatch.setattr(core, '_sql_time', lambda value: datetime.fromisoformat(str(value)))
    monkeypatch.setattr(core, '_captured_authority', lambda node, output: ({'a': 1}, 'd' * 64))
    monkeypatch.setattr(proof, 'verify_equity_finalization_recomputation', lambda *args, **kwargs: None)
    monkeypatch.setattr(proof, '_prove_anchor_record', lambda *args: None)
    monkeypatch.setattr(proof, 'original_equity_financial_projection', lambda output: {})
    # Only the market row's seal is real here (a sealed row is part of the finalization-only rule).
    real = core._row_digest
    monkeypatch.setattr(core, '_row_digest', lambda row: real(row) if row.get('source_id') == MARKET else None)


def sealed(row):
    row['content_digest'] = sha256(canonical_qt_input_bytes(row['payload'])).hexdigest()
    return row


def node(schema, column, payload_model, model, *, tamper_digest=False, extra_key=None):
    meta = {'producer_id': 'p', 'policy_version': 'v'}
    d = {'decision_id': DECISION, 'book_id': 'EQ', 'source_day': '2026-09-24', 'model_publication_id': MODEL}
    successor = {'schema_version': 'qt-equity-desk-finalization/v1', 'decision_id': DECISION,
                 'valuation_day': '2026-09-25', 'finalization_id': FIN}
    payload = {'schema_version': schema, 'calculation_version': 'qt-equity-main08b15c/v1', 'book_id': 'EQ',
               'source_day': '2026-09-25', 'model_publication_id': payload_model, 'previous_day': '2026-09-24',
               'valuation_time': '2026-09-25T00:00:00Z', 'day_mode': 'open', 'currency': 'USD', 'cost_config': {},
               'instruments': [], 'actions_source_id': 'qt-actions/x', 'actions_source_digest': 'a' * 64}
    if extra_key:
        payload[extra_key] = 1
    f = {'decision_id': DECISION, 'book_id': 'EQ', 'source_day': '2026-09-24', 'valuation_day': '2026-09-25',
         'finalization_id': FIN, 'market_source_id': MARKET, 'source_version': 'qt-finalization/' + FIN,
         'input_digest': 'i' * 64, 'output_digest': 'o' * 64, 'policy_revision': 1,
         'created_at': '2026-09-25T12:00:00+00:00', 'payload': successor, **meta}
    m = sealed({'source_id': MARKET, 'book_id': 'EQ', 'source_day': '2026-09-25', 'model_publication_id': column,
                'policy_revision': 1, 'as_of': '2026-09-25T11:00:00+00:00', 'valid_until': '2026-09-25T13:00:00+00:00',
                'created_at': '2026-09-25T11:30:00+00:00', 'payload': payload, 'source_version': 'market-1', **meta})
    if tamper_digest:
        m['content_digest'] = '0' * 64
    events = {'purpose': 'actions', 'book_id': 'EQ', 'source_day': '2026-09-25', 'source_id': 'qt-actions/x',
              'content_digest': 'a' * 64, 'policy_revision': 1, 'payload': {'events': []}, **meta}
    accounting = {'input_row': {'input_id': 'x', 'content_digest': 'i' * 64,
                                'payload': {'schema_version': 'qt-equity-accounting-input/v1'}, **meta},
                  'content_digest': 'o' * 64,
                  'finalization_row': {'source_id': 'qt-finalization/prev', 'content_digest': 'p' * 64},
                  'successor': {'transition_row': f, 'market_row': m, 'model_publication': model,
                                'actions_row': events, 'anchor_row': {}, 'basis_rows': []}}
    return {'decision': d, 'accounting': accounting, 'observation': {'content_digest': 'q' * 64}}


def prove(*args, **kwargs):
    return proof._prove_successor(node(*args, **kwargs), OUTPUT, lambda authority: None)


def test_finalization_only_market_admits_a_successor_without_a_model(isolated):
    assert prove(FIN_SCHEMA, None, None, None)['finalization_id'] == FIN


@pytest.mark.parametrize('column,payload_model,model', [
    (MODEL, MODEL, MODEL_ROW), (None, MODEL, None), (None, None, MODEL_ROW), (MODEL, None, None), (MODEL, MODEL, None)])
def test_finalization_only_market_cannot_carry_a_model(isolated, column, payload_model, model):
    with pytest.raises(ValueError):
        prove(FIN_SCHEMA, column, payload_model, model)


def test_finalization_only_market_row_must_be_sealed_and_closed(isolated):
    with pytest.raises(ValueError):
        prove(FIN_SCHEMA, None, None, None, tamper_digest=True)
    with pytest.raises(ValueError):
        prove(FIN_SCHEMA, None, None, None, extra_key='model_seed_digest')


def test_accounting_market_still_requires_its_model(isolated):
    with pytest.raises(ValueError):
        prove(V1_SCHEMA, None, None, None)


def test_accounting_market_with_its_model_still_admits(isolated):
    assert prove(V1_SCHEMA, MODEL, MODEL, MODEL_ROW)['finalization_id'] == FIN


def test_an_unknown_market_schema_is_refused_with_or_without_a_model(isolated):
    with pytest.raises(ValueError):
        prove('qt-equity-finalization-market/v2', None, None, None)
    with pytest.raises(ValueError):
        prove('qt-equity-accounting-market/v9', MODEL, MODEL, MODEL_ROW)


class Cursor:
    """SQL-prefix keyed fake; each handler returns a list of dict rows."""

    def __init__(self, handlers):
        self.handlers, self.rows = handlers, []

    def execute(self, sql, args=None):
        self.rows = next(h for prefix, h in self.handlers if sql.startswith(prefix))(args)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


def lineage(market):
    anchor = {'source_id': 'qt-finalization/' + FIN, 'payload': {'previous_positions': []}}
    receipt = {'attempt_id': 'r', 'publication_payload': {'observation_id': 'o'}}
    handlers = [
        ('SELECT * FROM trading.qt_desk_receipts', lambda a: [receipt]),
        ('SELECT * FROM trading.qt_execution_observations', lambda a: [{'observation_id': 'o'}]),
        ('SELECT * FROM trading.qt_previews', lambda a: [{'preview_id': 'p'}]),
        ('SELECT * FROM trading.qt_desk_results', lambda a: [{'decision_id': DECISION}]),
        ('SELECT * FROM trading.qt_desk_finalizations WHERE decision_id', lambda a: [{'finalization_id': FIN, 'market_source_id': MARKET}]),
        ('SELECT * FROM trading.qt_desk_market_sources', lambda a: [market]),
        ('SELECT * FROM trading.qt_equity_desk_evidence_sources WHERE source_id=%s', lambda a: [{'source_id': 'qt-actions/x'}]),
        ('SELECT * FROM trading.qt_desk_finalization_sources', lambda a: [anchor]),
        ('SELECT * FROM trading.qt_equity_desk_evidence_sources WHERE source_id=ANY', lambda a: []),
    ]
    local = lambda cursor, d, row, current=False: {
        'finalization_row': {'payload': {'schema_version': 'qt-equity-finalized-accounting/v1'}},
        'input_row': {'payload': {}}, 'payload': {}}
    decision = {'decision_id': DECISION, 'book_id': 'EQ', 'source_day': '2026-09-24', 'preview_id': 'p'}
    return evidence.load_equity_lineage_context(Cursor(handlers), decision, {}, load_local_context=local)


def test_lineage_loader_never_loads_a_model_for_a_finalization_only_market(monkeypatch):
    import algolens.infrastructure.portfolio.qt_empty_owner_sql as owner_sql
    monkeypatch.setattr(owner_sql, 'load_original_model_publication',
                        lambda cursor, identity: pytest.fail('model loaded for a finalization-only market'))
    market = {'source_id': MARKET, 'model_publication_id': None,
              'payload': {'schema_version': FIN_SCHEMA, 'actions_source_id': 'qt-actions/x'}}
    root = lineage(market)
    assert root['equity_lineage'][0]['accounting']['successor']['model_publication'] is None


def test_lineage_loader_still_loads_the_model_of_an_accounting_market(monkeypatch):
    import algolens.infrastructure.portfolio.qt_empty_owner_sql as owner_sql
    monkeypatch.setattr(owner_sql, 'load_original_model_publication', lambda cursor, identity: {'publication_id': identity})
    market = {'source_id': MARKET, 'model_publication_id': MODEL,
              'payload': {'schema_version': V1_SCHEMA, 'actions_source_id': 'qt-actions/x'}}
    root = lineage(market)
    assert root['equity_lineage'][0]['accounting']['successor']['model_publication'] == {'publication_id': MODEL}

"""Equity day 2, lane A1: the finalization recompute client's request validation and the finalization-only market.

Only the FINALIZATION path may carry ``qt-equity-finalization-market/v1`` (null model) to the native finalizer.
Every test stops at the transport: a stub process whose launch raises a fixed error, so a request that passes
validation surfaces ``equity_finalization_transport_unavailable`` (or, off Linux, the isolation error) and a request
that is refused surfaces ``equity_finalization_request_invalid``.  Nothing is launched and nothing touches a database.

The request body is the frozen synthetic wire fixture in ``tests/fixtures``.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
import json

import pytest

from algolens.infrastructure.portfolio import qt_equity_finalization_recompute_client as client_module
from algolens.infrastructure.portfolio.qt_equity_finalization_recompute_client import (
    QtEquityFinalizationRecomputeClient, QtEquityFinalizationUnavailable, _hash)
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess, QtEvaluatorUnavailable

FIN = 'qt-equity-finalization-market/v1'
V1 = 'qt-equity-accounting-market/v1'
EMPTY_OWNER_MARKET = 'qt-equity-accounting-market-empty-owner/v2'
MODEL = 'a0000000-0000-4000-8000-000000000001'
INVALID = 'equity_finalization_request_invalid'


def wire_path():
    return Path(__file__).with_name('fixtures') / 'qt-equity-finalization-wire.json'


@dataclass(frozen=True)
class StoppedProcess(QtEvaluatorProcess):
    @contextmanager
    def _launch(self):
        raise QtEvaluatorUnavailable('stub_never_launches')
        yield  # pragma: no cover


def load():
    return json.loads(wire_path().read_text(encoding='utf-8'))


def run(mutate=None):
    """Call the real client with the wire fixture (optionally changed) and return the fixed error text, or None."""
    wire = load()
    if mutate:
        mutate(wire)
    authority = wire['finalizer_authority']
    process = StoppedProcess(executable=Path('/opt/qt/evaluator'), expected_sha256=authority['evaluator_sha256'],
                             expected_build=authority['evaluator_build'], bundle_directory=Path('/opt/qt/bundle'),
                             expected_bundle_sha256=authority['evaluator_bundle_sha256'])
    try:
        QtEquityFinalizationRecomputeClient(process).recompute(
            wire['decision'], wire['original_input'], json.loads(wire['original_output_json']), wire['market_payload'],
            wire['actions_payload'], wire['before_financial'], wire['provenance'], authority,
            expected_authority_digest=_hash(authority))
    except QtEquityFinalizationUnavailable as error:
        return str(error)
    raise AssertionError('the stub process must stop the call')


def finalization_only(wire, model=None):
    market = wire['market_payload']
    market['schema_version'] = FIN
    market['model_publication_id'] = model
    wire['provenance']['market_source_digest'] = _hash(market)


def passed(error):
    return error != INVALID


def test_the_v1_market_still_passes_request_validation():
    assert passed(run())


def test_the_finalization_only_market_with_a_null_model_passes_request_validation():
    assert passed(run(finalization_only))


def test_the_finalization_only_market_may_not_name_a_model():
    assert run(lambda wire: finalization_only(wire, MODEL)) == INVALID


def test_the_finalization_only_market_may_not_drop_the_model_key_or_add_a_key():
    def drop(wire):
        finalization_only(wire)
        del wire['market_payload']['model_publication_id']
        wire['provenance']['market_source_digest'] = _hash(wire['market_payload'])

    def add(wire):
        finalization_only(wire)
        wire['market_payload']['model_seed_digest'] = 'a' * 64
        wire['provenance']['market_source_digest'] = _hash(wire['market_payload'])
    assert run(drop) == INVALID
    assert run(add) == INVALID


def test_a_v1_market_may_not_have_a_null_model():
    def null_model(wire):
        wire['market_payload']['model_publication_id'] = None
        wire['provenance']['market_source_digest'] = _hash(wire['market_payload'])
    assert run(null_model) == INVALID


def test_the_finalization_only_market_keeps_the_digest_binding_to_the_provenance():
    def stale(wire):
        finalization_only(wire)
        wire['provenance']['market_source_digest'] = '0' * 64
    assert run(stale) == INVALID


def test_the_finalization_only_market_keeps_the_other_market_rules():
    for change in (lambda m: m.update(currency='EUR'), lambda m: m.update(day_mode='close'),
                   lambda m: m.update(previous_day='2026-09-24'), lambda m: m.update(source_day='2026-09-25'),
                   lambda m: m.update(valuation_time='2026-09-26T01:00:00Z'), lambda m: m.update(calculation_version='x')):
        def mutate(wire, change=change):
            finalization_only(wire)
            change(wire['market_payload'])
            wire['provenance']['market_source_digest'] = _hash(wire['market_payload'])
        assert run(mutate) == INVALID


def test_the_finalization_only_market_is_not_accepted_for_an_empty_owner_input():
    def empty_owner(wire):
        finalization_only(wire)
        wire['original_input']['schema_version'] = 'qt-equity-accounting-input-empty-owner/v2'
    assert run(empty_owner) == INVALID


def test_the_empty_owner_market_schema_is_unchanged():
    def as_v2_market_on_v1_input(wire):
        wire['market_payload']['schema_version'] = EMPTY_OWNER_MARKET
        wire['provenance']['market_source_digest'] = _hash(wire['market_payload'])
    assert run(as_v2_market_on_v1_input) == INVALID


def test_the_client_imports_the_one_schema_constant_of_the_finalization_proof():
    from algolens.infrastructure.portfolio.qt_equity_finalization_proof import FINALIZATION_MARKET_SCHEMA
    assert FINALIZATION_MARKET_SCHEMA == FIN
    assert client_module.FINALIZATION_MARKET_SCHEMA is FINALIZATION_MARKET_SCHEMA

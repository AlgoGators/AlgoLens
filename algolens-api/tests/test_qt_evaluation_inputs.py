"""Governed input admission: no caller choices or financial defaults."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json

import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_evaluation_inputs import (
    canonical_qt_input_bytes, validate_qt_evaluation_snapshot,
    load_qt_evaluation_inputs,
)

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
MODEL = "10000000-0000-4000-8000-000000000001"
KEY = dict(portfolio_id="BOOK", strategy_id="alpha", strategy_name="Alpha",
           date="2026-09-25", symbol="SYN", portfolio_type="qt_proposal")


def sample():
    payload = dict(schema_version="qt-inputs/v1", book_id="BOOK",
        source_day="2026-09-25", model_publication_id=MODEL,
        instrument_catalog=[dict(key=KEY.copy(), instrument_type="EQUITY", editable=True)],
        engine_inputs=dict(risk_config_source_id="risk-v1",
            risk_inputs={"market_snapshot_id": "market-v1"},
            risk_config={"capital_exact": "1000000"},
            quantity_rules=[{"increment_exact": "0.00000001"}],
            component_cost_inputs=[{"source_id": "cost-v1"}],
            optimizer_policy={"enabled": False, "config_source_id": "optimizer-v1"},
            optimizer_inputs=None, optimizer_config=None))
    policy = dict(book_id="BOOK", purpose="evaluation", enabled=True, version=1,
        producer_id="synthetic", policy_version="policy-v1", evaluator_build="build-v1",
        evaluator_sha256="a" * 64, evaluator_bundle_sha256="b" * 64,
        allowed_override_codes=["gross_leverage"], updated_at=NOW)
    snapshot = dict(snapshot_id=7, book_id="BOOK", source_day=NOW.date(),
        model_publication_id=MODEL, producer_id="synthetic", policy_version="policy-v1",
        source_version="source-v1", as_of=NOW-timedelta(seconds=1),
        valid_until=NOW+timedelta(seconds=60), payload=payload,
        content_digest=sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest())
    return policy, snapshot


def admit(policy=None, snapshot=None):
    if policy is None:
        policy, snapshot = sample()
    return validate_qt_evaluation_snapshot(policy, snapshot, book_id="BOOK",
        source_day=NOW.date(), model_publication_id=MODEL, checked_at=NOW)


def rehash(snapshot):
    snapshot["content_digest"] = sha256(json.dumps(snapshot["payload"], sort_keys=True,
        separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def test_input_authority_supplies_immutable_bound_read_set_facts():
    policy, snapshot = sample()
    value = admit(policy, snapshot)
    assert value.evaluator_build == "build-v1"
    assert value.evaluator_sha256 == "a" * 64
    assert value.allowed_override_codes == ("gross_leverage",)
    facts = value.read_set_overrides
    assert facts["portfolio_inputs"]["capital_exact"] == "1000000"
    assert facts["risk_limits"]["id"] == 7
    assert len(facts["external_sources"]) == 8
    assert all(x["status"] == "available" and x["digest"] == value.source_identity_digest
               for x in facts["external_sources"])
    snapshot["payload"]["engine_inputs"]["risk_config"]["capital_exact"] = "2"
    facts["evaluator"]["build"] = "changed"
    assert value.engine_inputs["risk_config"]["capital_exact"] == "1000000"
    assert value.read_set_overrides["evaluator"]["build"] == "build-v1"


@pytest.mark.parametrize("change", ["disabled", "foreign_policy", "producer", "policy_version",
    "model", "day", "expired", "future", "hash", "float", "unknown_root", "injected_choice",
    "injected_context", "duplicate_catalog", "foreign_catalog", "bad_type", "missing_capital",
    "zero_capital", "missing_optimizer", "policy_pin", "bad_codes", "missing_engine_field"])
def test_invalid_or_untrusted_input_never_becomes_override(change):
    policy, snapshot = sample()
    payload = snapshot["payload"]
    if change == "disabled": policy["enabled"] = False
    elif change == "foreign_policy": policy["book_id"] = "OTHER"
    elif change == "producer": snapshot["producer_id"] = "other"
    elif change == "policy_version": snapshot["policy_version"] = "other"
    elif change == "model": snapshot["model_publication_id"] = "20000000-0000-4000-8000-000000000001"
    elif change == "day": snapshot["source_day"] = NOW.date()+timedelta(days=1)
    elif change == "expired": snapshot["valid_until"] = NOW-timedelta(seconds=1)
    elif change == "future": snapshot["as_of"] = NOW+timedelta(seconds=1)
    elif change == "hash": snapshot["content_digest"] = "b"*64
    elif change == "float": payload["engine_inputs"]["risk_config"]["var_limit"] = 0.15
    elif change == "unknown_root": payload["chosen"] = []
    elif change == "injected_choice": payload["engine_inputs"]["risk_inputs"]["quantity_exact"] = "7"
    elif change == "injected_context": payload["engine_inputs"]["risk_inputs"]["expected_revision"] = "caller"
    elif change == "duplicate_catalog": payload["instrument_catalog"] *= 2
    elif change == "foreign_catalog": payload["instrument_catalog"][0]["key"]["portfolio_id"] = "OTHER"
    elif change == "bad_type": payload["instrument_catalog"][0]["instrument_type"] = "UNKNOWN"
    elif change == "missing_capital": payload["engine_inputs"]["risk_config"].clear()
    elif change == "zero_capital": payload["engine_inputs"]["risk_config"]["capital_exact"] = "0"
    elif change == "missing_optimizer": payload["engine_inputs"]["optimizer_policy"]["enabled"] = True
    elif change == "policy_pin": policy["evaluator_sha256"] = None
    elif change == "bad_codes": policy["allowed_override_codes"] = ["gross_leverage", "gross_leverage"]
    elif change == "missing_engine_field": del payload["engine_inputs"]["quantity_rules"]
    if change != "hash": rehash(snapshot)
    with pytest.raises(QtWorkflowError) as caught:
        admit(policy, snapshot)
    assert caught.value.code == "preview_unavailable"


def test_policy_revision_and_pin_invalidate_equal_value_snapshot():
    policy, snapshot = sample()
    before = admit(policy, snapshot)
    policy["version"] += 1
    assert before.source_identity_digest != admit(policy, snapshot).source_identity_digest
    policy["evaluator_sha256"] = "c"*64
    assert before.source_identity_digest != admit(policy, snapshot).source_identity_digest


def test_json_bounds_and_no_float_are_enforced_before_hashing():
    for value in ({"x": 0.0}, {"x": "z"*4097}, {"x": 2**63}, {"x": float("nan")}):
        with pytest.raises(ValueError): canonical_qt_input_bytes(value)


class Cursor:
    def __init__(self, replies): self.replies = iter(replies); self.calls = []
    def execute(self, query, params=()): self.calls.append((query, params))
    def fetchone(self): return next(self.replies)
    def fetchall(self):
        row = next(self.replies)
        return [] if row is None else [row]


class Tx:
    book_id = "BOOK"
    def __init__(self, replies, stage=4): self.cursor = Cursor(replies); self.stage=stage
    def _require_mutable(self):
        if self.stage != 4: raise RuntimeError("not locked")


def test_loader_uses_current_sql_authorities_under_existing_lock():
    policy, snapshot = sample()
    tx = Tx([{"ready":True}, policy, {"owner_v2_table_present": False},
             {"publication_id": MODEL}, snapshot])
    result = load_qt_evaluation_inputs(tx, source_day=NOW.date(), model_publication_id=MODEL, checked_at=NOW)
    assert result.snapshot_id == 7
    assert len(tx.cursor.calls) == 5
    assert "to_regclass('trading.qt_empty_model_owner_publications')" in tx.cursor.calls[2][0]
    assert "qt_storage_capabilities" not in " ".join(q for q, _ in tx.cursor.calls)
    assert "ORDER BY snapshot_id DESC LIMIT 1" in tx.cursor.calls[-1][0]
    assert tx.cursor.calls[-1][1] == ("BOOK", NOW.date())
    assert all("INSERT" not in q and "UPDATE" not in q for q,_ in tx.cursor.calls)


def test_missing_tables_are_checked_without_aborting_borrowed_transaction():
    tx = Tx([{"ready":False}])
    with pytest.raises(QtWorkflowError):
        load_qt_evaluation_inputs(tx, source_day=NOW.date(), model_publication_id=MODEL, checked_at=NOW)
    assert len(tx.cursor.calls) == 1
    assert "to_regclass" in tx.cursor.calls[0][0]


def test_loader_refuses_use_before_ordered_locks():
    with pytest.raises(RuntimeError):
        load_qt_evaluation_inputs(Tx([],stage=0), source_day=NOW.date(), model_publication_id=MODEL, checked_at=NOW)


@pytest.mark.parametrize("pin", [None,"", "not-a-digest"])
def test_missing_or_invalid_native_bundle_pin_blocks_input_authority(pin):
    policy,snapshot=sample()
    policy["evaluator_bundle_sha256"]=pin
    with pytest.raises(QtWorkflowError) as caught: admit(policy,snapshot)
    assert caught.value.code=="preview_unavailable"


def test_native_bundle_pin_is_exposed_and_bound_independently_of_binary_hash():
    policy,snapshot=sample();policy["evaluator_bundle_sha256"]="b"*64
    first=admit(policy,snapshot)
    assert first.evaluator_bundle_sha256=="b"*64
    policy["evaluator_bundle_sha256"]="c"*64
    second=admit(policy,snapshot)
    assert first.evaluator_sha256==second.evaluator_sha256
    assert first.source_identity_digest!=second.source_identity_digest

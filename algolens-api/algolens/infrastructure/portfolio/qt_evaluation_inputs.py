"""Read explicit evaluator authority from an already locked QT transaction.

This module admits source identity, not a trade decision. The C++ evaluator
still must validate complete market/rule/cost coverage and compute evidence.
No environment, connection, source ingestion or position write occurs here.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import re
from uuid import UUID

from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtKey

_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ENGINE_FIELDS = frozenset({"risk_config_source_id", "risk_inputs", "risk_config",
    "quantity_rules", "component_cost_inputs", "optimizer_policy", "optimizer_inputs", "optimizer_config"})
_EXTERNAL = ("mark", "history", "cost", "multiplier", "universe", "instrument_type", "quantity_rule", "evaluator_policy")
_FORBIDDEN = frozenset({"context", "slots", "selection", "proposal", "quantities", "quantity_exact",
    "chosen_quantity_exact", "desired_quantity_exact", "decision_id", "context_fingerprint",
    "expected_portfolio_id", "expected_date", "expected_portfolio_type", "expected_revision"})


def canonical_qt_input_bytes(value: object) -> bytes:
    """Bounded UTF-8 sorted-object JSON; array order is source-authoritative."""
    nodes = 0
    def check(item, depth=0):
        nonlocal nodes
        nodes += 1
        if nodes > 200000 or depth > 32:
            raise ValueError("input_bound_exceeded")
        if item is None or type(item) is bool:
            return
        if type(item) is int:
            if not -(1 << 63) <= item < (1 << 63): raise ValueError("input_integer_bound")
        elif type(item) is str:
            if len(item) > 4096: raise ValueError("input_string_bound")
            item.encode("utf-8", "strict")
        elif type(item) is list:
            if len(item) > 4096: raise ValueError("input_array_bound")
            for child in item: check(child, depth+1)
        elif type(item) is dict:
            if len(item) > 256: raise ValueError("input_object_bound")
            for key, child in item.items():
                if type(key) is not str: raise ValueError("input_key_type")
                check(key, depth+1)
                check(child, depth+1)
        else:
            raise ValueError("input_value_type")
    check(value)
    wire = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8", "strict")
    if len(wire) > 8*1024*1024: raise ValueError("input_byte_bound")
    return wire


def _text(value):
    if type(value) is not str or not value.strip() or len(value) > 4096:
        raise ValueError("invalid_source_text")
    value.encode("utf-8", "strict")
    return value


def _hash(value):
    if type(value) is not str or not _HEX.fullmatch(value): raise ValueError("invalid_source_hash")
    return value


def _positive(value):
    if type(value) is not int or not 0 < value < (1 << 63): raise ValueError("invalid_source_version")
    return value


def _utc(value):
    if type(value) is str:
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("source_time_unavailable")
    return value.astimezone(timezone.utc)


def _time(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _day(value):
    if type(value) is date: return value.isoformat()
    if type(value) is not str or date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid_source_day")
    return value


def _uuid(value):
    result = str(value)
    if str(UUID(result)) != result: raise ValueError("invalid_source_uuid")
    return result


def _no_choice(value):
    if type(value) is dict:
        if _FORBIDDEN.intersection(value): raise ValueError("selection_in_source")
        for item in value.values(): _no_choice(item)
    elif type(value) is list:
        for item in value: _no_choice(item)


@dataclass(frozen=True)
class QtEvaluationInputs:
    snapshot_id: int
    content_digest: str
    source_identity_digest: str
    evaluator_build: str
    evaluator_sha256: str
    evaluator_bundle_sha256: str
    policy_version: str
    allowed_override_codes: tuple[str, ...]
    valid_until: str
    _payload_bytes: bytes
    _facts_bytes: bytes

    @property
    def input_schema(self): return json.loads(self._payload_bytes)["schema_version"]

    @property
    def engine_inputs(self): return json.loads(self._payload_bytes)["engine_inputs"]

    @property
    def instrument_catalog(self): return json.loads(self._payload_bytes)["instrument_catalog"]

    @property
    def read_set_overrides(self): return json.loads(self._facts_bytes)


def validate_qt_evaluation_snapshot(policy, snapshot, *, book_id, source_day,
                                    model_publication_id, checked_at, model_publication=None):
    """Validate a current SQL-selected record; malformed inputs are unavailable."""
    try:
        book, day, model = _text(book_id), _day(source_day), _uuid(model_publication_id)
        checked = _utc(checked_at)
        if checked.date().isoformat() != day: raise ValueError("source_day_changed")
        if not isinstance(policy, dict) or not isinstance(snapshot, dict): raise ValueError("missing_authority")
        if policy["book_id"] != book or policy["purpose"] != "evaluation" or policy["enabled"] is not True:
            raise ValueError("policy_unavailable")
        revision = _positive(policy["version"])
        producer, version = _text(policy["producer_id"]), _text(policy["policy_version"])
        build, pin = _text(policy["evaluator_build"]), _hash(policy["evaluator_sha256"])
        bundle_pin = _hash(policy["evaluator_bundle_sha256"])
        codes = policy["allowed_override_codes"]
        if type(codes) is not list or len(codes) > 128: raise ValueError("invalid_override_policy")
        codes = [_text(code) for code in codes]
        if len(set(codes)) != len(codes): raise ValueError("duplicate_override_code")
        snapshot_id = _positive(snapshot["snapshot_id"])
        if (snapshot["book_id"] != book or _day(snapshot["source_day"]) != day
            or _uuid(snapshot["model_publication_id"]) != model or snapshot["producer_id"] != producer
            or snapshot["policy_version"] != version): raise ValueError("source_scope_mismatch")
        source_version = _text(snapshot["source_version"])
        start, until = _utc(snapshot["as_of"]), _utc(snapshot["valid_until"])
        if not start <= checked <= until: raise ValueError("source_expired")
        payload = snapshot["payload"]
        wire = canonical_qt_input_bytes(payload)
        digest = _hash(snapshot["content_digest"])
        if sha256(wire).hexdigest() != digest: raise ValueError("source_digest_mismatch")
        if (type(payload) is not dict or set(payload) != {"schema_version", "book_id", "source_day",
            "model_publication_id", "instrument_catalog", "engine_inputs"}
            or payload["schema_version"] not in {"qt-inputs/v1", "qt-inputs-empty-owner/v2"} or payload["book_id"] != book
            or payload["source_day"] != day or payload["model_publication_id"] != model):
            raise ValueError("source_payload_scope")
        catalog = payload["instrument_catalog"]
        empty_owner = payload['schema_version'] == 'qt-inputs-empty-owner/v2'
        if empty_owner:
            from algolens.infrastructure.portfolio.qt_empty_owner_sql import require_empty_current_owner
            require_empty_current_owner(model_publication, book, day, model)
        if type(catalog) is not list or (bool(catalog) if empty_owner else not catalog):
            raise ValueError("catalog_missing")
        seen = set()
        for row in catalog:
            if type(row) is not dict or set(row) != {"key", "instrument_type", "editable"}:
                raise ValueError("catalog_shape")
            key = QtKey.from_wire(row["key"])
            if (key.portfolio_id != book or key.date != day or key.portfolio_type != "qt_proposal"
                or row["instrument_type"] not in {"EQUITY", "FUTURE"} or type(row["editable"]) is not bool
                or key in seen): raise ValueError("catalog_scope")
            seen.add(key)
        inputs = payload["engine_inputs"]
        fields = _ENGINE_FIELDS - {'optimizer_inputs','optimizer_config'} if empty_owner else _ENGINE_FIELDS
        if type(inputs) is not dict or set(inputs) != fields: raise ValueError("engine_inputs_missing")
        _no_choice(inputs)
        _text(inputs["risk_config_source_id"])
        for field in ("risk_inputs", "risk_config", "optimizer_policy"):
            if type(inputs[field]) is not dict or not inputs[field]: raise ValueError("engine_input_shape")
        for field in ("quantity_rules", "component_cost_inputs"):
            if type(inputs[field]) is not list: raise ValueError("engine_input_shape")
        if empty_owner and (inputs['quantity_rules'] != [] or inputs['component_cost_inputs'] != []
            or any(inputs['risk_inputs'].get(field) != [] for field in
                ('valuations','closes','expected_observation_times'))):
            raise ValueError('nonempty_owner_asset_inputs')
        capital = inputs["risk_config"]["capital_exact"]
        if (type(capital) is not str or canonical_position_decimal8(capital) != capital
            or Decimal(capital) <= 0): raise ValueError("capital_unavailable")
        optimizer = inputs["optimizer_policy"]
        if set(optimizer) != {"enabled", "config_source_id"} or type(optimizer["enabled"]) is not bool:
            raise ValueError("optimizer_policy_unavailable")
        _text(optimizer["config_source_id"])
        if empty_owner and optimizer['enabled']: raise ValueError('empty_owner_optimizer_unsupported')
        for field in (() if empty_owner else ("optimizer_inputs", "optimizer_config")):
            if optimizer["enabled"]:
                if type(inputs[field]) is not dict or not inputs[field]: raise ValueError("optimizer_input_missing")
            elif inputs[field] is not None: raise ValueError("disabled_optimizer_input")
        # Bind policy updates, even equal-value snapshots, to read-set freshness.
        identity = {"schema_version": "qt-input-authority/v1", "book_id": book, "source_day": day,
            "model_publication_id": model, "snapshot_id": snapshot_id, "source_version": source_version,
            "as_of": _time(start), "valid_until": _time(until), "content_digest": digest,
            "producer_id": producer, "policy_version": version, "policy_revision": revision,
            "policy_updated_at": _time(policy["updated_at"]), "evaluator_build": build,
            "evaluator_sha256": pin, "evaluator_bundle_sha256": bundle_pin, "allowed_override_codes": sorted(codes)}
        identity_digest = sha256(canonical_qt_input_bytes(identity)).hexdigest()
        source_id = f"qt_evaluation_snapshots:{snapshot_id}"
        facts = {"risk_limits": {"status": "present", "id": snapshot_id, "published_at": _time(start), "content_digest": digest},
            "portfolio_inputs": {"status": "present", "source_id": source_id, "source_day": day,
                "capital_exact": capital, "content_digest": digest},
            "external_sources": [{"name": name, "status": "available", "source_id": source_id,
                "version": source_version, "as_of": _time(start), "valid_until": _time(until),
                "digest": identity_digest, "reason": None} for name in _EXTERNAL],
            "evaluator": {"status": "available", "build": build, "policy_version": version}}
        return QtEvaluationInputs(snapshot_id, digest, identity_digest, build, pin, bundle_pin, version,
            tuple(sorted(codes)), _time(until), wire, canonical_qt_input_bytes(facts))
    except (ValueError, TypeError, KeyError, OverflowError, QtWorkflowError):
        raise QtWorkflowError("preview_unavailable", "Governed evaluator input is missing, stale or invalid") from None


def load_qt_evaluation_inputs(tx, *, source_day, model_publication_id, checked_at):
    """Borrow the caller's ordered, book-locked transaction; never open a DSN."""
    tx._require_mutable()
    cursor = tx.cursor
    cursor.execute("SELECT to_regclass('trading.qt_source_policies') IS NOT NULL "
        "AND to_regclass('trading.qt_evaluation_snapshots') IS NOT NULL "
        "AND to_regclass('trading.qt_model_seed_publications') IS NOT NULL AS ready")
    if not cursor.fetchone()["ready"]:
        raise QtWorkflowError("preview_unavailable", "Governed evaluator source storage is unavailable")
    cursor.execute("SELECT * FROM trading.qt_source_policies WHERE book_id=%s AND purpose='evaluation'", (tx.book_id,))
    policy = cursor.fetchone()
    from algolens.infrastructure.portfolio.qt_empty_owner_sql import load_evaluation_model_publication
    try:
        model = load_evaluation_model_publication(tx, source_day, str(model_publication_id))
    except ValueError:
        raise QtWorkflowError('preview_unavailable', 'Governed evaluator MODEL source is unavailable') from None
    cursor.execute("SELECT * FROM trading.qt_evaluation_snapshots WHERE book_id=%s AND source_day=%s "
        "ORDER BY snapshot_id DESC LIMIT 1", (tx.book_id, source_day))
    snapshot = cursor.fetchone()
    return validate_qt_evaluation_snapshot(dict(policy) if policy is not None else None,
        dict(snapshot) if snapshot is not None else None, book_id=tx.book_id,
        source_day=source_day, model_publication_id=model_publication_id, checked_at=checked_at,
        model_publication=model)

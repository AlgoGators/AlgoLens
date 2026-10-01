"""Strict qt-workflow/v1 canonical JSON; hash the bytes, never JSONB text.

Book parity digests use only complete target ``qt`` six-keys and exact
quantities. Display origin, basis, type, risk, and cost remain bound in the
immutable preview/read-set payload, not in the publication parity digest.
The preview payload digest hashes the entire typed preview without its own
``payload_digest`` field.
"""

from collections.abc import Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from math import isfinite
import re
from uuid import UUID

from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8
from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError


_MAX_BYTES = 1_048_576
_MAX_STRING = 4096
_MAX_ARRAY = 4096
_INT64_MIN = -(1 << 63)
_INT64_MAX = (1 << 63) - 1
_KEY_FIELDS = ("portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")
_KEY_SET = frozenset(_KEY_FIELDS)
_EXACT_FIELDS = frozenset({
    "quantity_exact", "average_price_exact", "previous_net_quantity_exact",
    "proposed_net_quantity_exact",
    "prior_quantity_exact", "selected_quantity_exact", "cash_cost_exact", "total_exact",
})
_DIAGNOSTIC_FIELDS = frozenset({
    "weight_diagnostic", "cost_penalty", "limit_diagnostic", "actual_diagnostic", "value_diagnostic",
})
_DIGEST_FIELDS = frozenset({
    "source_digest", "provenance_digest", "draft_digest", "payload_digest",
    "optimizer_book_digest", "selected_book_digest", "read_set_digest",
    "evaluated_book_digest", "published_book_digest", "row_manifest_digest",
    "expected_source_digest", "expected_provenance_digest", "expected_digest",
    "seed_digest", "request_digest",
})
_UUID_FIELDS = frozenset({
    "draft_id", "preview_id", "decision_id", "request_id", "idempotency_key",
    "seed_publication_id", "model_publication_id",
})
_INT_FIELDS = frozenset({"version", "draft_revision", "expected_draft_revision", "approvals_count", "required_approvals"})
_BOOL_FIELDS = frozenset({
    "required", "available", "can_save_draft", "can_confirm", "can_approve",
    "editable", "confirmable", "requires_override", "passed", "acknowledge_warnings",
    "retryable", "report_ready",
})
_ARRAY_FIELDS = frozenset({
    "selection_rows", "seed_rows", "saved_qt_rows", "aggregate_bindings",
    "component_keys", "current_weights", "target_weights", "solved_weights",
    "trace", "diagnostics", "breaches", "metrics", "by_component",
    "unavailable_reasons", "approvals", "report_blocked_reasons", "reason_codes",
})
_OBJECT_FIELDS = frozenset({"key", "capability", "action_grants", "evaluation", "optimizer", "selected_risk", "selected_costs", "receipt", "report_eligibility", "error"})
_STRING_FIELDS = frozenset({
    "schema_version", "book_id", "source_day", "workflow_state", "read_only_reason",
    "state", "portfolio_id", "strategy_id", "strategy_name", "date", "symbol",
    "portfolio_type", "basis_status", "asset_type", "origin", "status", "availability",
    "instrument_type", "config_source_id", "market_snapshot_id", "source_id", "code",
    "unit", "message", "action", "person_id", "display_label", "user_id",
    "approved_at", "created_at", "updated_at", "evaluator_build", "policy_version",
    "rationale",
})
_ALLOWED_FIELDS = _EXACT_FIELDS | _DIAGNOSTIC_FIELDS | _DIGEST_FIELDS | _UUID_FIELDS | _INT_FIELDS | _BOOL_FIELDS | _ARRAY_FIELDS | _OBJECT_FIELDS | _STRING_FIELDS
_SORTED_KEY_ARRAYS = frozenset({"selection_rows", "seed_rows", "saved_qt_rows", "component_keys", "by_component"})
_TEXT_ARRAYS = frozenset({"trace", "diagnostics", "unavailable_reasons", "report_blocked_reasons", "reason_codes"})
_NESTED_SHAPES = {
    "key": (_KEY_SET,),
    "component_keys": (_KEY_SET,),
    "selection_rows": (frozenset({"key", "quantity_exact"}), frozenset({"key", "quantity_exact", "basis_status", "average_price_exact", "asset_type", "editable", "origin"})),
    "seed_rows": (frozenset({"key", "quantity_exact", "average_price_exact"}), frozenset({"key", "quantity_exact", "basis_status", "average_price_exact", "asset_type", "editable", "origin"})),
    "saved_qt_rows": (frozenset({"key", "quantity_exact", "basis_status", "average_price_exact", "asset_type", "editable", "origin"}),),
    "by_component": (frozenset({"key", "prior_quantity_exact", "selected_quantity_exact", "cash_cost_exact", "source_id"}),),
    "aggregate_bindings": (frozenset({"instrument_type", "symbol", "component_keys", "previous_net_quantity_exact", "proposed_net_quantity_exact"}),),
    "current_weights": (frozenset({"instrument_type", "symbol", "weight_diagnostic"}),),
    "target_weights": (frozenset({"instrument_type", "symbol", "weight_diagnostic"}),),
    "solved_weights": (frozenset({"instrument_type", "symbol", "weight_diagnostic"}),),
    "breaches": (frozenset({"code", "limit_diagnostic", "actual_diagnostic"}),),
    "metrics": (frozenset({"code", "value_diagnostic", "unit", "source_id"}),),
    "approvals": (frozenset({"person_id", "display_label", "user_id", "approved_at"}),),
    "capability": (frozenset({"required", "available", "version"}),),
    "action_grants": (frozenset({"can_save_draft", "can_confirm", "can_approve"}),),
    "evaluation": (frozenset({"optimizer", "selected_risk", "selected_costs"}),),
    "optimizer": (frozenset({"status", "evaluated_book_digest", "aggregate_bindings", "current_weights", "target_weights", "solved_weights", "trace", "cost_penalty", "diagnostics", "config_source_id"}),),
    "selected_risk": (frozenset({"status", "evaluated_book_digest", "passed", "breaches", "metrics", "config_source_id", "market_snapshot_id", "diagnostics"}),),
    "selected_costs": (frozenset({"status", "evaluated_book_digest", "by_component", "total_exact", "diagnostics"}),),
    "receipt": (frozenset({"status", "published_book_digest", "report_eligibility"}),),
    "report_eligibility": (frozenset({"status", "reason_codes", "row_manifest_digest"}),),
    "error": (frozenset({"code", "message", "retryable"}),),
}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_DIAGNOSTIC_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_ACCOUNT_ID = re.compile(r"(?:0|[1-9][0-9]*)\Z")


def _reject(code: str = "invalid_qt_payload", message: str = "Invalid QT wire payload") -> None:
    raise QtWorkflowError(code, message)


def _checked_string(value: object) -> str:
    if type(value) is not str or len(value) > _MAX_STRING:
        _reject()
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        _reject()
    return value


def _key_tuple(value: Mapping[str, object]) -> tuple[str, ...]:
    key = value.get("key", value)
    if not isinstance(key, Mapping) or frozenset(key) != _KEY_SET:
        _reject("invalid_qt_key", "QT component key requires all six fields")
    return tuple(_checked_string(key[field]) for field in _KEY_FIELDS)


def _validate(value: object, field: str | None = None, *, depth: int = 0) -> object:
    if depth > 32:
        _reject()
    if field == "origin" and (type(value) is not str or value not in {
            "verified_model_seed", "reconciled_legacy_draft", "verified_qt_decision", "qt_draft", "immutable"}):
        _reject()
    if isinstance(value, Mapping):
        if len(value) > 128:
            _reject()
        if field in _NESTED_SHAPES and frozenset(value) not in _NESTED_SHAPES[field]:
            _reject("invalid_qt_key" if field in {"key", "component_keys"} else "invalid_qt_payload")
        result = {}
        for name, item in value.items():
            if type(name) is not str or not name.isascii() or name not in _ALLOWED_FIELDS:
                _reject()
            result[name] = _validate(item, name, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if field not in _ARRAY_FIELDS or len(value) > _MAX_ARRAY:
            _reject()
        result = [_validate(item, field, depth=depth + 1) for item in value]
        if field in _SORTED_KEY_ARRAYS:
            keys = [_key_tuple(item) for item in result]
            if len(set(keys)) != len(keys):
                _reject("invalid_qt_key", "Duplicate QT component key")
            result = [item for _, item in sorted(zip(keys, result), key=lambda pair: pair[0])]
        elif field == "aggregate_bindings":
            pairs = [(item["instrument_type"], item["symbol"]) for item in result]
            if len(set(pairs)) != len(pairs):
                _reject()
            result = [item for _, item in sorted(zip(pairs, result), key=lambda pair: pair[0])]
        return result
    if value is None:
        if field in (_EXACT_FIELDS - {"quantity_exact", "previous_net_quantity_exact", "proposed_net_quantity_exact", "prior_quantity_exact", "selected_quantity_exact", "cash_cost_exact"}) | _DIAGNOSTIC_FIELDS | _DIGEST_FIELDS | _UUID_FIELDS | _OBJECT_FIELDS | {"read_only_reason", "config_source_id", "market_snapshot_id", "source_id", "passed", "version", "user_id"}:
            return None
        _reject()
    if field in _TEXT_ARRAYS:
        return _checked_string(value)
    if field in _EXACT_FIELDS:
        if type(value) is not str:
            _reject("invalid_qt_exact", "QT exact value must be canonical Decimal8 text")
        try:
            parsed = parse_fixed_decimal8(value)
            if canonical_position_decimal8(parsed) != value:
                _reject("invalid_qt_exact", "QT exact value is not canonical")
        except (TypeError, ValueError):
            _reject("invalid_qt_exact", "QT exact value is not canonical")
        return value
    if field in _DIAGNOSTIC_FIELDS:
        text = _checked_string(value)
        if _DIAGNOSTIC_DECIMAL.fullmatch(text) is None:
            _reject()
        try:
            decimal_value = Decimal(text)
            double_value = float(text)
            if (not decimal_value.is_finite() or not isfinite(double_value)
                    or (decimal_value != 0 and double_value == 0.0)):
                _reject()
        except (InvalidOperation, OverflowError, ValueError):
            _reject()
        return text
    if field in _DIGEST_FIELDS:
        text = _checked_string(value)
        if _HEX64.fullmatch(text) is None:
            _reject()
        return text
    if field in _UUID_FIELDS:
        text = _checked_string(value)
        try:
            parsed = UUID(text)
        except (ValueError, AttributeError):
            _reject()
        if str(parsed) != text:
            _reject()
        return text
    if field in _INT_FIELDS:
        if type(value) is not int or not _INT64_MIN <= value <= _INT64_MAX:
            _reject()
        return value
    if field in _BOOL_FIELDS:
        if type(value) is not bool:
            _reject()
        return value
    if field in _OBJECT_FIELDS | _ARRAY_FIELDS:
        _reject()
    if field in _STRING_FIELDS:
        text = _checked_string(value)
        if field == "user_id" and (_ACCOUNT_ID.fullmatch(text) is None or int(text) > _INT64_MAX):
            _reject()
        if field in {"date", "source_day"}:
            try:
                if date.fromisoformat(text).isoformat() != text:
                    _reject()
            except ValueError:
                _reject()
        if field == "schema_version" and text != "qt-workflow/v1":
            _reject()
        return text
    _reject()


def canonical_qt_bytes(payload: Mapping[str, object]) -> bytes:
    """Validate and encode restricted QT JSON with lexical fields and key-sorted components."""
    if not isinstance(payload, Mapping):
        _reject()
    if payload.get("schema_version") == "qt-workflow/v2":
        proposal = frozenset("schema_version book_id source_day capability workflow_state read_only_reason action_grants source_digest provenance_digest seed_publication_id seed_rows saved_qt_rows empty_owner".split())
        draft = frozenset("schema_version book_id source_day state draft_id draft_revision draft_digest source_digest provenance_digest selection_rows empty_owner".split())
        consumed = draft | {"successor"}
        if frozenset(payload) not in {proposal, draft, consumed}: _reject()
        marker = payload["empty_owner"]
        names = frozenset("schema_version model_publication_id owner_document_digest configured_owner_names".split())
        if not isinstance(marker, Mapping) or frozenset(marker) != names: _reject()
        if marker["schema_version"] != "qt-empty-owner-choice/v2": _reject()
        model = _validate(marker["model_publication_id"], "model_publication_id")
        if model is None or UUID(model).int == 0: _reject()
        digest = _validate(marker["owner_document_digest"], "source_digest")
        if digest is None: _reject()
        owners = marker["configured_owner_names"]
        if type(owners) is not list or len(owners) != 1: _reject()
        owner = _checked_string(owners[0])
        if not owner.strip() or len(owner.encode("utf-8")) > 256: _reject()
        if any(payload[name] is None for name in ("source_digest", "provenance_digest")): _reject()
        if frozenset(payload) == proposal:
            if (payload["workflow_state"] != "ready" or payload["seed_publication_id"] != model
                    or payload["seed_rows"] != [] or payload["saved_qt_rows"] != []
                    or not isinstance(payload["capability"], Mapping) or payload["capability"].get("available") is not True): _reject()
        elif (payload["selection_rows"] != [] or
              (frozenset(payload) == draft and payload["state"] not in {"absent", "saved"}) or
              (frozenset(payload) == consumed and payload["state"] != "consumed")): _reject()
        successor = None
        if frozenset(payload) == consumed:
            source = payload["successor"]
            if not isinstance(source, Mapping) or frozenset(source) != frozenset("decision_id attempt_id preview_id publication_digest".split()): _reject()
            successor = {}
            for name in ("decision_id", "attempt_id", "preview_id"):
                ident = _validate(source[name], "model_publication_id")
                if ident is None or UUID(ident).int == 0: _reject()
                successor[name] = ident
            successor["publication_digest"] = _validate(source["publication_digest"], "source_digest")
            if successor["publication_digest"] is None: _reject()
        legacy = {name: item for name, item in payload.items() if name not in {"empty_owner", "successor"}}
        legacy["schema_version"] = "qt-workflow/v1"
        normalized = _validate(legacy)
        normalized.update(schema_version="qt-workflow/v2", empty_owner={
            "schema_version": "qt-empty-owner-choice/v2", "model_publication_id": model,
            "owner_document_digest": digest, "configured_owner_names": [owner]})
        if successor is not None: normalized["successor"] = successor
    else:
        normalized = _validate(payload)
    try:
        wire = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        _reject()
    if len(wire) > _MAX_BYTES:
        _reject()
    return wire


def qt_digest_v1(payload: Mapping[str, object]) -> str:
    return sha256(canonical_qt_bytes(payload)).hexdigest()


def qt_book_digest_v1(rows: Sequence[Mapping[str, object]], *, source_portfolio_type: str) -> str:
    """Hash the full target-qt quantity projection, retaining zero/short rows.

    A caller must assert the current source stream; only the stream field is
    transformed. Every other identity field is carried through unchanged.
    """
    if source_portfolio_type not in {"qt_proposal", "qt"} or not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        _reject("invalid_qt_key")
    projected = []
    for row in rows:
        if not isinstance(row, Mapping) or "key" not in row or "quantity_exact" not in row:
            _reject("invalid_qt_key")
        key = row["key"]
        _key_tuple(key)
        if key["portfolio_type"] != source_portfolio_type:
            _reject("invalid_qt_key", "QT source stream does not match expected stream")
        projected.append({"key": {**key, "portfolio_type": "qt"}, "quantity_exact": row["quantity_exact"]})
    return qt_digest_v1({"selection_rows": projected})


def parse_qt_json(raw: bytes) -> dict[str, object]:
    """Decode strict UTF-8 JSON, rejecting duplicate fields before dict construction."""
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
        _reject()
    try:
        decoded = raw.decode("utf-8", "strict")
    except UnicodeError:
        _reject()

    def no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result = {}
        for key, value in pairs:
            if key in result:
                _reject()
            result[key] = value
        return result

    def reject_numeric(_: str) -> None:
        _reject()

    try:
        payload = json.loads(decoded, object_pairs_hook=no_duplicates, parse_float=reject_numeric, parse_constant=reject_numeric)
    except (ValueError, TypeError, RecursionError):
        _reject()
    canonical_qt_bytes(payload)
    return payload

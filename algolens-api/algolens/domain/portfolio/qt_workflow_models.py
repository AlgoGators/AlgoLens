"""Immutable, typed QT workflow wire values and selection admission."""

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
import re
from types import MappingProxyType
from typing import ClassVar
from uuid import UUID

from algolens.domain.portfolio.qt_canonical import canonical_qt_bytes, qt_book_digest_v1, qt_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8


SCHEMA_VERSION = "qt-workflow/v1"
_KEY_NAMES = ("portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")
_APPROVER_IDS = frozenset({"xander_robbins", "hemdutt_rao", "dominick_dupuy"})
_UTC_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")


def _shape(value: object, names: frozenset[str], optional: frozenset[str] = frozenset()) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not names - optional <= value.keys() or not value.keys() <= names:
        raise QtWorkflowError("invalid_qt_payload", "QT wire fields do not match the v1 contract")
    canonical_qt_bytes(value)
    return value


def _literal(value: object, choices: frozenset[str]) -> str:
    if type(value) is not str or value not in choices:
        raise QtWorkflowError("invalid_qt_payload", "Invalid QT wire state")
    return value


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True, order=True)
class QtKey:
    portfolio_id: str
    strategy_id: str
    strategy_name: str
    date: str
    symbol: str
    portfolio_type: str

    @classmethod
    def from_wire(cls, value: object) -> "QtKey":
        obj = _shape(value, frozenset(_KEY_NAMES))
        if any(type(obj[name]) is not str or not obj[name] for name in _KEY_NAMES):
            raise QtWorkflowError("invalid_qt_key", "QT component identity is incomplete")
        try:
            if date.fromisoformat(obj["date"]).isoformat() != obj["date"]:
                raise ValueError()
        except ValueError:
            raise QtWorkflowError("invalid_qt_key", "QT component date is invalid") from None
        return cls(**obj)

    def to_wire(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class QtSelectionRow:
    key: QtKey
    quantity_exact: str
    basis_status: str
    average_price_exact: str | None
    asset_type: str
    editable: bool
    origin: str

    _NAMES: ClassVar[frozenset[str]] = frozenset({
        "key", "quantity_exact", "basis_status", "average_price_exact", "asset_type", "editable", "origin",
    })

    @classmethod
    def from_wire(cls, value: object) -> "QtSelectionRow":
        obj = _shape(value, cls._NAMES)
        key = QtKey.from_wire(obj["key"])
        _literal(obj["basis_status"], frozenset({"preserved_source", "unfilled"}))
        _literal(obj["asset_type"], frozenset({"EQUITY", "FUTURE"}))
        _literal(obj["origin"], frozenset({"verified_model_seed", "reconciled_legacy_draft", "verified_qt_decision", "qt_draft", "immutable"}))
        if type(obj["editable"]) is not bool:
            raise QtWorkflowError("invalid_qt_payload")
        if (obj["basis_status"] == "unfilled") != (obj["average_price_exact"] is None):
            raise QtWorkflowError("invalid_qt_payload", "QT basis status and value disagree")
        if obj["asset_type"] == "FUTURE" and Decimal(obj["quantity_exact"]) != Decimal(obj["quantity_exact"]).to_integral_value():
            raise QtWorkflowError("invalid_qt_exact", "Futures positions require whole contracts")
        return cls(key=key, **{name: obj[name] for name in cls._NAMES - {"key"}})

    def to_wire(self) -> dict[str, object]:
        return asdict(self)


def parse_qt_selection(
    rows: Sequence[Mapping[str, object]],
    editable_keys: frozenset[QtKey],
    instrument_types: Mapping[QtKey, str],
    *,
    source_rows: Mapping[QtKey, QtSelectionRow] | None = None,
    immutable_rows: Sequence[QtSelectionRow] = (),
) -> tuple[QtSelectionRow, ...]:
    """Admit one exact explicit choice per server-resolved editable component."""
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) > 4096:
        raise QtWorkflowError("invalid_qt_payload")
    parsed = []
    seen: set[QtKey] = set()
    for row in rows:
        obj = _shape(row, frozenset({"key", "quantity_exact"}))
        key = QtKey.from_wire(obj["key"])
        if key in seen or key not in editable_keys:
            raise QtWorkflowError("invalid_qt_key", "Duplicate or out-of-scope QT component")
        seen.add(key)
        kind = instrument_types.get(key)
        if kind not in {"EQUITY", "FUTURE"}:
            raise QtWorkflowError("draft_identity_unresolved", "QT instrument type is unavailable")
        try:
            quantity = parse_fixed_decimal8(obj["quantity_exact"])
        except (TypeError, ValueError):
            raise QtWorkflowError("invalid_qt_exact", "Invalid QT quantity") from None
        if kind == "FUTURE" and Decimal(quantity) != Decimal(quantity).to_integral_value():
            raise QtWorkflowError("invalid_qt_exact", "Futures positions require whole contracts")
        source = (source_rows or {}).get(key)
        if source is not None and (source.key != key or source.asset_type != kind or not source.editable):
            raise QtWorkflowError("draft_identity_unresolved")
        parsed.append(QtSelectionRow(
            key=key, quantity_exact=quantity,
            basis_status=source.basis_status if source else "unfilled",
            average_price_exact=source.average_price_exact if source else None,
            asset_type=kind, editable=True, origin="qt_draft",
        ))
    if seen != editable_keys:
        raise QtWorkflowError("invalid_qt_key", "Complete QT editable selection is required")
    if any(row.editable or row.key in seen for row in immutable_rows):
        raise QtWorkflowError("draft_identity_unresolved")
    return tuple(sorted((*parsed, *immutable_rows), key=lambda row: row.key))


def _display_rows(
    rows: Sequence[Mapping[str, object]], book_id: str, source_day: str,
    streams: frozenset[str],
) -> tuple[QtSelectionRow, ...]:
    """A response row is a full display value, never a digest projection."""
    parsed = tuple(QtSelectionRow.from_wire(row) for row in rows)
    if any(
        row.key.portfolio_id != book_id
        or row.key.date != source_day
        or row.key.portfolio_type not in streams
        for row in parsed
    ):
        raise QtWorkflowError("invalid_qt_key", "QT display row is outside the response scope")
    return parsed


@dataclass(frozen=True)
class QtDraftSaveRequest:
    expected_source_digest: str
    expected_provenance_digest: str
    expected_draft_revision: int
    idempotency_key: str
    rationale: str
    selection_rows: tuple[Mapping[str, object], ...]

    @classmethod
    def from_wire(cls, value: object) -> "QtDraftSaveRequest":
        obj = _shape(value, frozenset(cls.__dataclass_fields__))
        if obj["expected_draft_revision"] < 0 or not isinstance(obj["selection_rows"], list):
            raise QtWorkflowError("invalid_qt_payload")
        if type(obj["rationale"]) is not str:
            raise QtWorkflowError("invalid_qt_payload", "QT draft rationale is required")
        rationale = obj["rationale"].strip()
        if not rationale or len(rationale.encode("utf-8")) > 1000:
            raise QtWorkflowError("invalid_qt_payload", "QT draft rationale must be 1 to 1000 UTF-8 bytes")
        return cls(**{**obj, "rationale": rationale, "selection_rows": _freeze(obj["selection_rows"])})

    def to_wire(self) -> dict[str, object]:
        return {"expected_source_digest": self.expected_source_digest,
                "expected_provenance_digest": self.expected_provenance_digest,
                "expected_draft_revision": self.expected_draft_revision,
                "idempotency_key": self.idempotency_key,
                "rationale": self.rationale,
                "selection_rows": _thaw(self.selection_rows)}


@dataclass(frozen=True)
class QtCreatePreviewRequest:
    book_id: str
    draft_id: str
    draft_revision: int
    draft_digest: str
    expected_source_digest: str
    expected_provenance_digest: str
    idempotency_key: str

    @classmethod
    def from_wire(cls, value: object) -> "QtCreatePreviewRequest":
        obj = _shape(value, frozenset(cls.__dataclass_fields__))
        if obj["draft_revision"] < 1:
            raise QtWorkflowError("invalid_qt_payload")
        return cls(**obj)

    def to_wire(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class QtConfirmRequest:
    action: str
    expected_digest: str
    idempotency_key: str
    acknowledge_warnings: bool

    @classmethod
    def from_wire(cls, value: object) -> "QtConfirmRequest":
        obj = _shape(value, frozenset(cls.__dataclass_fields__))
        if obj["action"] != "confirm_selected_book":
            raise QtWorkflowError("invalid_qt_action", "Expected confirm_selected_book")
        return cls(**obj)

    def to_wire(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class QtApproveRequest:
    action: str
    idempotency_key: str

    @classmethod
    def from_wire(cls, value: object) -> "QtApproveRequest":
        obj = _shape(value, frozenset(cls.__dataclass_fields__))
        if obj["action"] != "approve":
            raise QtWorkflowError("invalid_qt_action", "Expected approve")
        return cls(**obj)

    def to_wire(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _WireResponse:
    payload: Mapping[str, object]
    _NAMES: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def from_wire(cls, value: object):
        obj = _shape(value, cls._NAMES)
        if obj["schema_version"] != SCHEMA_VERSION:
            raise QtWorkflowError("invalid_qt_payload")
        return cls(_freeze(obj))

    def to_wire(self) -> dict[str, object]:
        return _thaw(self.payload)


def _empty_owner_response(cls, value):
    """Only the two explicit response variants may carry empty-owner authority."""
    if not isinstance(value, Mapping) or value.get("schema_version") != "qt-workflow/v2":
        return _WireResponse.from_wire.__func__(cls, value)
    extra = {"empty_owner"}
    if value.get("state") == "consumed": extra.add("successor")
    obj = _shape(value, cls._NAMES | extra)
    marker = obj["empty_owner"]
    try:
        ident = marker["model_publication_id"]
        if type(ident) is not str or str(UUID(ident)) != ident or UUID(ident).int == 0:
            raise ValueError()
        names = marker["configured_owner_names"]
        if (marker["schema_version"] != "qt-empty-owner-choice/v2" or type(names) is not list
                or len(names) != 1 or type(names[0]) is not str or not names[0].strip()
                or len(names[0].encode("utf-8")) > 256): raise ValueError()
        for digest in (marker["owner_document_digest"], obj["source_digest"], obj["provenance_digest"]):
            if type(digest) is not str or not re.fullmatch(r"[0-9a-f]{64}", digest): raise ValueError()
        if "seed_rows" in obj:
            if (obj["workflow_state"] != "ready" or not obj["capability"]["available"]
                    or obj["seed_publication_id"] != ident or obj["seed_rows"] != []
                    or obj["saved_qt_rows"] != []): raise ValueError()
        elif obj["state"] not in {"absent", "saved", "consumed"} or obj["selection_rows"] != []:
            raise ValueError()
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
        raise QtWorkflowError("invalid_qt_payload", "Empty-owner choice needs complete current authority") from None
    return cls(_freeze(obj))


@dataclass(frozen=True)
class QtProposalResponse(_WireResponse):
    _NAMES: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "book_id", "source_day", "capability", "workflow_state",
        "read_only_reason", "action_grants", "source_digest", "provenance_digest",
        "seed_publication_id", "seed_rows", "saved_qt_rows",
    })

    @classmethod
    def from_wire(cls, value: object):
        result = _empty_owner_response(cls, value)
        data = result.payload
        seed_rows = _display_rows(data["seed_rows"], data["book_id"], data["source_day"], frozenset({"qt_proposal"}))
        _display_rows(data["saved_qt_rows"], data["book_id"], data["source_day"], frozenset({"qt"}))
        if any(row.origin != "verified_model_seed" for row in seed_rows):
            raise QtWorkflowError("invalid_qt_payload", "Proposal seed display needs verified MODEL origin")
        _literal(result.payload["workflow_state"], frozenset({"ready", "provenance_unresolved", "workflow_unavailable"}))
        if result.payload["workflow_state"] == "ready" and (
            result.payload["seed_publication_id"] is None
            or result.payload["source_digest"] is None
            or result.payload["provenance_digest"] is None
            or not result.payload["capability"]["available"]
        ):
            raise QtWorkflowError("invalid_qt_payload", "Ready QT proposal needs verified source and capability")
        return result


@dataclass(frozen=True)
class QtDraftResponse(_WireResponse):
    _NAMES: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "book_id", "source_day", "state", "draft_id", "draft_revision",
        "draft_digest", "source_digest", "provenance_digest", "rationale", "selection_rows",
    })

    @classmethod
    def from_wire(cls, value: object):
        result = _empty_owner_response(cls, value)
        rationale = result.payload["rationale"]
        if rationale is not None and (type(rationale) is not str or not rationale.strip()
                or rationale != rationale.strip() or len(rationale.encode("utf-8")) > 1000):
            raise QtWorkflowError("invalid_qt_payload", "Saved QT rationale is invalid")
        _display_rows(result.payload["selection_rows"], result.payload["book_id"], result.payload["source_day"], frozenset({"qt_proposal", "qt"}))
        states = {"absent", "saved", "stale", "provenance_unresolved"}
        if result.payload["schema_version"] == "qt-workflow/v2": states.add("consumed")
        _literal(result.payload["state"], frozenset(states))
        if result.payload["state"] == "absent" and (result.payload["draft_revision"] != 0 or result.payload["draft_id"] is not None):
            raise QtWorkflowError("invalid_qt_payload")
        if result.payload["state"] in {"saved", "consumed"} and (
            result.payload["draft_id"] is None
            or result.payload["draft_revision"] < 1
            or result.payload["draft_digest"] is None
        ):
            raise QtWorkflowError("invalid_qt_payload", "Saved QT draft needs its immutable identity")
        return result


@dataclass(frozen=True)
class QtPreviewResponse(_WireResponse):
    _NAMES: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "book_id", "source_day", "preview_id", "payload_digest",
        "optimizer_book_digest", "selected_book_digest", "draft_id", "draft_revision",
        "source_digest", "provenance_digest", "read_set_digest", "availability",
        "confirmable", "requires_override", "selection_rows", "unavailable_reasons", "evaluation",
    })

    @classmethod
    def from_wire(cls, value: object):
        result = super().from_wire(value)
        data = result.payload
        selected_rows = _display_rows(data["selection_rows"], data["book_id"], data["source_day"], frozenset({"qt_proposal", "qt"}))
        projected = [
            {"key": {**row.key.to_wire(), "portfolio_type": "qt"}, "quantity_exact": row.quantity_exact}
            for row in selected_rows
        ]
        if qt_book_digest_v1(projected, source_portfolio_type="qt") != data["selected_book_digest"]:
            raise QtWorkflowError("invalid_qt_payload", "QT selected-book digest does not match the complete selection")
        if qt_digest_v1({name: item for name, item in data.items() if name != "payload_digest"}) != data["payload_digest"]:
            raise QtWorkflowError("invalid_qt_payload", "QT preview payload digest mismatch")
        _literal(data["availability"], frozenset({"ready", "unavailable"}))
        if data["availability"] == "unavailable" and (data["confirmable"] or data["requires_override"]):
            raise QtWorkflowError("invalid_qt_payload")
        if data["requires_override"] and not data["confirmable"]:
            raise QtWorkflowError("invalid_qt_payload")
        evidence = data["evaluation"]
        risk = evidence["selected_risk"]
        costs = evidence["selected_costs"]
        if data["availability"] == "ready":
            if not data["confirmable"] or data["unavailable_reasons"]:
                raise QtWorkflowError("invalid_qt_payload")
            if risk["status"] != "evaluated" or costs["status"] != "evaluated" or risk["passed"] is None or costs["total_exact"] is None:
                raise QtWorkflowError("invalid_qt_payload", "Ready QT preview needs complete selected-book evidence")
            if not risk["config_source_id"] or not risk["market_snapshot_id"]:
                raise QtWorkflowError("invalid_qt_payload")
            if any(metric["value_diagnostic"] is None or not metric["source_id"] for metric in risk["metrics"]):
                raise QtWorkflowError("invalid_qt_payload")
            if any(breach["limit_diagnostic"] is None or breach["actual_diagnostic"] is None for breach in risk["breaches"]):
                raise QtWorkflowError("invalid_qt_payload")
            if any(not item["source_id"] for item in costs["by_component"]):
                raise QtWorkflowError("invalid_qt_payload")
            selected_editable = {QtKey.from_wire(row["key"]): row["quantity_exact"] for row in data["selection_rows"] if row["editable"]}
            costed = {QtKey.from_wire(item["key"]): item["selected_quantity_exact"] for item in costs["by_component"]}
            if costed != selected_editable or sum((Decimal(item["cash_cost_exact"]) for item in costs["by_component"]), Decimal(0)) != Decimal(costs["total_exact"]):
                raise QtWorkflowError("invalid_qt_payload", "Selected QT costs do not cover the chosen components")
            if risk["passed"] == data["requires_override"] or bool(risk["breaches"]) != data["requires_override"]:
                raise QtWorkflowError("invalid_qt_payload")
        if evidence["optimizer"]["evaluated_book_digest"] != data["optimizer_book_digest"] and evidence["optimizer"]["status"] == "evaluated":
            raise QtWorkflowError("invalid_qt_payload")
        for stage in ("selected_risk", "selected_costs"):
            if evidence[stage]["status"] == "evaluated" and evidence[stage]["evaluated_book_digest"] != data["selected_book_digest"]:
                raise QtWorkflowError("invalid_qt_payload")
        return result


@dataclass(frozen=True)
class QtDecisionResponse(_WireResponse):
    _NAMES: ClassVar[frozenset[str]] = frozenset({
        "schema_version", "book_id", "preview_id", "decision_id", "request_id", "status",
        "selected_book_digest", "read_set_digest", "approvals", "approvals_count",
        "required_approvals", "can_approve", "receipt", "report_ready", "report_blocked_reasons",
    })

    @classmethod
    def from_wire(cls, value: object):
        result = super().from_wire(value)
        data = result.payload
        _literal(data["status"], frozenset({"pending_override", "confirmed_decision"}))
        if data["required_approvals"] != 2 or data["approvals_count"] != len(data["approvals"]):
            raise QtWorkflowError("invalid_qt_payload")
        people: set[str] = set()
        users: set[str] = set()
        for approval in data["approvals"]:
            if approval["person_id"] not in _APPROVER_IDS or approval["person_id"] in people or approval["user_id"] in users:
                raise QtWorkflowError("invalid_qt_payload", "Duplicate or unknown QT approver")
            people.add(approval["person_id"])
            users.add(approval["user_id"])
            stamp = approval["approved_at"]
            if _UTC_TIMESTAMP.fullmatch(stamp) is None:
                raise QtWorkflowError("invalid_qt_payload", "QT approval timestamp must be UTC")
            try:
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                raise QtWorkflowError("invalid_qt_payload", "Invalid QT approval timestamp") from None
            if parsed.utcoffset() != timedelta(0):
                raise QtWorkflowError("invalid_qt_payload", "QT approval timestamp must be UTC")
        if data["status"] == "pending_override":
            if data["request_id"] is None or data["approvals_count"] >= 2 or data["receipt"] is not None or data["report_ready"]:
                raise QtWorkflowError("invalid_qt_payload")
        elif data["request_id"] is not None and data["approvals_count"] != 2:
            raise QtWorkflowError("invalid_qt_payload")
        if data["report_ready"]:
            receipt = data["receipt"]
            if receipt is None or receipt["status"] != "processed" or receipt["published_book_digest"] != data["selected_book_digest"] or receipt["report_eligibility"]["status"] != "eligible" or receipt["report_eligibility"]["row_manifest_digest"] is None or data["report_blocked_reasons"]:
                raise QtWorkflowError("invalid_qt_payload")
        return result

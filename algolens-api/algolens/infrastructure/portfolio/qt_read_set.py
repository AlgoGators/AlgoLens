"""Closed internal QT snapshot schemas and immutable current read-set values.

These are not public qt-workflow wire documents. In particular, arbitrary
JSONB from risk/config tables is never passed to the public canonicalizer.
An unavailable upstream market/cost contract is an explicit hashed fact.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import re
from types import MappingProxyType
from uuid import UUID

from algolens.domain.portfolio.position_decimal import canonical_position_decimal8


_MAX_BYTES = 1_048_576
_MAX_STRING = 4096
_MAX_ARRAY = 4096
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ACCOUNT = re.compile(r"[1-9][0-9]*\Z")
_EXTERNAL_NAMES = frozenset({
    "mark", "history", "cost", "multiplier", "universe", "instrument_type",
    "quantity_rule", "evaluator_policy",
})
_KEY = ("portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")


def _text(value: object) -> str:
    if type(value) is not str or len(value) > _MAX_STRING:
        raise ValueError("invalid_internal_text")
    value.encode("utf-8", "strict")
    return value


def _nonempty(value: object) -> str:
    value = _text(value)
    if not value.strip():
        raise ValueError("empty_internal_text")
    return value


def _day(value: object) -> str:
    value = _text(value)
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError("invalid_internal_day")
    return value


def _timestamp(value: object) -> str:
    value = _text(value)
    if not value.endswith("Z"):
        raise ValueError("invalid_internal_timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("invalid_internal_timestamp")
    return value


def _digest(value: object) -> str:
    value = _text(value)
    if _HEX64.fullmatch(value) is None:
        raise ValueError("invalid_internal_digest")
    return value


def _uuid(value: object) -> str:
    value = _text(value)
    if str(UUID(value)) != value:
        raise ValueError("invalid_internal_uuid")
    return value


def _int(value: object) -> int:
    if type(value) is not int or not -(1 << 63) <= value < (1 << 63):
        raise ValueError("invalid_internal_int")
    return value


def _positive(value: object) -> int:
    value = _int(value)
    if value <= 0:
        raise ValueError("invalid_internal_version")
    return value


def _bool(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("invalid_internal_bool")
    return value


def _exact(value: object) -> str:
    value = _text(value)
    if canonical_position_decimal8(value) != value:
        raise ValueError("noncanonical_internal_exact")
    return value


def _account(value: object) -> str:
    value = _text(value)
    if _ACCOUNT.fullmatch(value) is None or int(value) >= 1 << 63:
        raise ValueError("invalid_internal_account")
    return value


def _maybe(check):
    return lambda value: None if value is None else check(value)


def _literal(*choices):
    def check(value):
        if type(value) is not str or value not in choices:
            raise ValueError("invalid_internal_literal")
        return value
    return check


def _shape(value: object, fields: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != set(fields):
        raise ValueError("invalid_internal_shape")
    return {name: check(value[name]) for name, check in fields.items()}


def _array(value: object, check, *, identity=None) -> list[object]:
    if not isinstance(value, (list, tuple)) or len(value) > _MAX_ARRAY:
        raise ValueError("invalid_internal_array")
    result = [check(item) for item in value]
    if identity is not None:
        keys = [identity(item) for item in result]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_internal_identity")
        result = [item for _, item in sorted(zip(keys, result), key=lambda pair: pair[0])]
    return result


def _key(value: object) -> dict[str, str]:
    result = _shape(value, {
        "portfolio_id": _nonempty, "strategy_id": _nonempty,
        "strategy_name": _nonempty, "date": _day, "symbol": _nonempty,
        "portfolio_type": _literal("system", "qt_proposal", "qt"),
    })
    return result


def _key_id(value: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(value[field] for field in _KEY)


def _row(value: object) -> dict[str, object]:
    return _shape(value, {
        "key": _key, "quantity_exact": _exact, "average_price_exact": _exact,
    })


def _rows(value: object) -> list[object]:
    return _array(value, _row, identity=lambda item: _key_id(item["key"]))


def _accounting_row(value: object) -> dict[str, object]:
    return _shape(value, {
        "key": _key, "quantity_exact": _exact, "average_price_exact": _exact,
        "daily_unrealized_pnl_exact": _exact, "daily_realized_pnl_exact": _exact,
        "last_update": _timestamp,
    })


def _proposal_row(value: object) -> dict[str, object]:
    result = _shape(value, {
        "key": _key, "quantity_exact": _exact,
        "average_price_exact": _exact, "position_revision": _maybe(_uuid),
    })
    if result["key"]["portfolio_type"] != "qt_proposal":
        raise ValueError("invalid_proposal_stream")
    return result


def _proposal_rows(value: object) -> list[object]:
    return _array(value, _proposal_row, identity=lambda item: _key_id(item["key"]))


def _manifest_entry(value: object) -> dict[str, object]:
    result = _shape(value, {
        "key": _key, "quantity_exact": _exact,
        "average_price_exact": _exact,
        "action": _literal("inserted", "preserved"),
        "position_revision": _maybe(_uuid),
        "origin_publication_id": _maybe(_uuid),
    })
    if result["key"]["portfolio_type"] != "qt_proposal":
        raise ValueError("invalid_manifest_stream")
    if result["action"] == "inserted" and (result["position_revision"] is None or result["origin_publication_id"] is None):
        raise ValueError("unlinked_manifest_insert")
    return result


def _manifest_rows(value: object) -> list[object]:
    return _array(value, _manifest_entry, identity=lambda item: _key_id(item["key"]))


def _audit_event(value: object) -> dict[str, object]:
    return _shape(value, {"id": _positive, "user_id": _account,
                          "source_app": _literal("algolens", "manual_db_edit"),
                          "before": _row, "after": _row})


def _publication(value: object) -> dict[str, object]:
    if isinstance(value, Mapping) and 'schema_version' in value:
        def owner_id(item):
            wire = _uuid(item)
            if UUID(wire).int == 0: raise ValueError('invalid_empty_owner_id')
            return wire
        def revision(item):
            number = _int(item)
            if number < 0: raise ValueError('invalid_empty_owner_registry_revision')
            return number
        def owners(item):
            result = _array(item, _nonempty, identity=lambda name: name)
            if not result or list(item) != result: raise ValueError('invalid_empty_owner_names')
            return result
        return _shape(value, {
            'schema_version': _literal('qt-empty-model-owner-reference/v2'),
            'publication_id': owner_id, 'strategy_id': _literal('LIVE_EQUITY_MEAN_REVERSION'),
            'publication_version': _positive, 'seed_digest': _digest,
            'proposal_manifest_digest': _digest, 'producer_version': _nonempty,
            'owner_document_digest': _digest, 'configuration_digest': _digest, 'qt_digest': _digest,
            'registry_id': _nonempty, 'registry_revision': revision, 'configured_owner_names': owners,
        })
    return _shape(value, {
        "publication_id": _uuid, "strategy_id": _nonempty,
        "publication_version": _positive, "seed_digest": _digest,
        "proposal_manifest_digest": _maybe(_digest),
        "producer_version": _nonempty,
    })


def _audit_ref(value: object) -> dict[str, object]:
    return _shape(value, {
        "id": _positive, "user_id": _maybe(_account),
        "source_app": _nonempty, "strategy_id": _nonempty,
        "symbol": _nonempty, "before_digest": _digest, "after_digest": _digest,
    })


def _draft(value: object) -> dict[str, object]:
    result = _shape(value, {
        "status": _literal("absent", "present"), "draft_id": _maybe(_uuid),
        "revision": _int, "digest": _maybe(_digest),
    })
    if result["status"] == "absent" and (result["draft_id"] is not None or result["revision"] != 0 or result["digest"] is not None):
        raise ValueError("invalid_absent_draft")
    if result["status"] == "present" and (result["draft_id"] is None or result["revision"] <= 0 or result["digest"] is None):
        raise ValueError("invalid_present_draft")
    return result


def _registry(value: object) -> dict[str, object]:
    return _shape(value, {
        "id": _nonempty, "strategy_type": _nonempty, "portfolio_id": _nonempty,
        "is_active": _bool, "lifecycle": _nonempty, "updated_at": _timestamp,
    })


def _membership(value: object) -> dict[str, object]:
    return _shape(value, {"strategy_id": _nonempty, "portfolio_id": _nonempty})


def _risk_inventory_row(value: object) -> dict[str, object]:
    return _shape(value, {
        "id": _positive, "strategy_id": _nonempty,
        "published_at": _timestamp, "content_digest": _digest,
    })


def _capability(value: object) -> dict[str, object]:
    result = _shape(value, {
        "status": _literal("absent", "present"), "enabled": _maybe(_bool),
        "version": _maybe(_positive),
    })
    if (result["status"] == "absent") != (result["enabled"] is None and result["version"] is None):
        raise ValueError("invalid_capability_absence")
    return result


def _grant(value: object) -> dict[str, object]:
    return _shape(value, {
        "user_id": _account, "capability": _literal("qt_submit", "qt_approve"),
        "active": _bool, "version": _positive,
    })


def _risk(value: object) -> dict[str, object]:
    result = _shape(value, {
        "status": _literal("absent", "present"), "id": _maybe(_positive),
        "published_at": _maybe(_timestamp), "content_digest": _maybe(_digest),
    })
    if (result["status"] == "absent") != all(result[name] is None for name in ("id", "published_at", "content_digest")):
        raise ValueError("invalid_risk_absence")
    return result


def _portfolio(value: object) -> dict[str, object]:
    result = _shape(value, {
        "status": _literal("absent", "present"), "source_id": _maybe(_nonempty),
        "source_day": _maybe(_day), "capital_exact": _maybe(_exact),
        "content_digest": _maybe(_digest),
    })
    if (result["status"] == "absent") != all(result[name] is None for name in ("source_id", "source_day", "capital_exact", "content_digest")):
        raise ValueError("invalid_portfolio_absence")
    return result


def _external(value: object) -> dict[str, object]:
    result = _shape(value, {
        "name": _literal(*sorted(_EXTERNAL_NAMES)),
        "status": _literal("available", "unavailable"),
        "source_id": _maybe(_nonempty), "version": _maybe(_nonempty),
        "as_of": _maybe(_timestamp), "valid_until": _maybe(_timestamp),
        "digest": _maybe(_digest), "reason": _maybe(_nonempty),
    })
    fields = ("source_id", "version", "as_of", "valid_until", "digest")
    if result["status"] == "available":
        if any(result[name] is None for name in fields) or result["reason"] is not None:
            raise ValueError("unversioned_external_source")
    elif any(result[name] is not None for name in fields) or result["reason"] is None:
        raise ValueError("untyped_external_absence")
    return result


def _evaluator(value: object) -> dict[str, object]:
    result = _shape(value, {
        "status": _literal("available", "unavailable"),
        "build": _maybe(_nonempty), "policy_version": _maybe(_nonempty),
    })
    if (result["status"] == "unavailable") != (result["build"] is None and result["policy_version"] is None):
        raise ValueError("invalid_evaluator_absence")
    return result


def _provenance(value: object) -> dict[str, object]:
    return _shape(value, {
        "status": _literal("ready", "provenance_unresolved"),
        "source_digest": _maybe(_digest), "chain_digest": _maybe(_digest),
        "seed_digest": _maybe(_digest),
    })


def _read_set(value: object) -> dict[str, object]:
    result = _shape(value, {
        "schema_version": _literal("qt-read-set/v1"), "book_id": _nonempty,
        "source_day": _day,
        "source_rows": _proposal_rows, "saved_rows": _rows, "system_rows": _rows,
        "saved_accounting": lambda x: _array(x, _accounting_row, identity=lambda item: _key_id(item["key"])),
        "publication_refs": lambda x: _array(x, _publication, identity=lambda item: item["publication_id"]),
        "audit_refs": lambda x: _array(x, _audit_ref, identity=lambda item: item["id"]),
        "draft": _draft,
        "registry": lambda x: _array(x, _registry, identity=lambda item: item["id"]),
        "memberships": lambda x: _array(x, _membership, identity=lambda item: (item["strategy_id"], item["portfolio_id"])),
        "capability": _capability,
        "grants": lambda x: _array(x, _grant, identity=lambda item: (item["user_id"], item["capability"])),
        "risk_limits": _risk,
        "risk_inventory": lambda x: _array(x, _risk_inventory_row, identity=lambda item: item["id"]),
        "portfolio_inputs": _portfolio,
        "external_sources": lambda x: _array(x, _external, identity=lambda item: item["name"]),
        "evaluator": _evaluator, "provenance": _provenance,
    })
    if {source["name"] for source in result["external_sources"]} != _EXTERNAL_NAMES:
        raise ValueError("incomplete_external_source_set")
    for field, stream in (("source_rows", "qt_proposal"), ("saved_rows", "qt"), ("system_rows", "system"), ("saved_accounting", "qt")):
        for row in result[field]:
            if (row["key"]["portfolio_id"] != result["book_id"]
                    or row["key"]["date"] != result["source_day"]
                    or row["key"]["portfolio_type"] != stream):
                raise ValueError("foreign_read_set_row")
    return result


def canonical_internal_snapshot_bytes(kind: str, payload: Mapping[str, object]) -> bytes:
    """Encode only the three closed, versioned internal document shapes."""
    if kind == "qt-source/v1":
        normalized = _shape(payload, {
            "schema_version": _literal(kind), "book_id": _nonempty,
            "source_day": _day, "rows": _proposal_rows,
        })
    elif kind == "qt-provenance/v1":
        normalized = _shape(payload, {
            "schema_version": _literal(kind), "book_id": _nonempty,
            "source_day": _day, "publication_id": _uuid,
            "publication_version": _positive, "seed_digest": _digest,
            "proposal_manifest_digest": _digest,
            "audit_events": lambda x: _array(x, _audit_event, identity=lambda item: item["id"]),
        })
    elif kind == "qt-proposal-manifest/v1":
        normalized = _shape(payload, {"proposal_rows": _manifest_rows})
    elif kind == "qt-receipt-provenance/v1":
        def receipt_link(value):
            link = _shape(value, {"decision_id": _uuid, "attempt_id": _uuid, "preview_id": _uuid,
                "publication_digest": _digest,
                "audit_ids": lambda x: _array(x, _positive, identity=lambda item: item),
                "source_keys": lambda x: _array(x, _key, identity=_key_id)})
            if not link["audit_ids"] or any(key["portfolio_type"] != "qt" for key in link["source_keys"]):
                raise ValueError("invalid_receipt_link")
            return link
        normalized = _shape(payload, {"schema_version": _literal(kind), "book_id": _nonempty,
            "source_day": _day, "legacy_chain_digest": _digest,
            "receipt_links": lambda x: _array(x, receipt_link)})
        links = normalized["receipt_links"]
        triples = [(row["decision_id"], row["attempt_id"], row["preview_id"]) for row in links]
        ids = [identity for row in links for identity in row["audit_ids"]]
        if (not links or len(triples) != len(set(triples)) or len(ids) != len(set(ids))
                or any(key["portfolio_id"] != normalized["book_id"] or key["date"] != normalized["source_day"]
                       for row in links for key in row["source_keys"])):
            raise ValueError("ambiguous_receipt_links")
        normalized["receipt_links"] = sorted(links, key=lambda row: row["audit_ids"][0])
    elif kind == 'qt-empty-owner-receipt-provenance/v2':
        def nonnil(value):
            value=_uuid(value)
            if UUID(value).int==0:raise ValueError('nil_empty_receipt_identity')
            return value
        def empty_array(value):
            if not isinstance(value,(list,tuple)) or value:raise ValueError('nonempty_empty_receipt_scope')
            return []
        def owner_marker(value):
            marker=_shape(value,{'schema_version':_literal('qt-empty-owner-choice/v2'),
                'model_publication_id':nonnil,'owner_document_digest':_digest,
                'configured_owner_names':lambda item:_array(item,_nonempty)})
            names=marker['configured_owner_names']
            if len(names)!=1 or len(names[0].encode('utf-8'))>256:raise ValueError('empty_receipt_owner_scope')
            return marker
        def exact_stamp(value):
            value=_timestamp(value)
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.isoformat().replace('+00:00','Z')!=value:raise ValueError('noncanonical_empty_receipt_time')
            return value
        def empty_link(value):
            return _shape(value,{'decision_id':nonnil,'attempt_id':nonnil,'preview_id':nonnil,
                'publication_digest':_digest,'audit_ids':empty_array,'source_keys':empty_array,'processed_at':exact_stamp})
        normalized=_shape(payload,{'schema_version':_literal(kind),'book_id':_nonempty,'source_day':_day,
            'legacy_chain_digest':_digest,'empty_owner':owner_marker,'receipt_links':lambda item:_array(item,empty_link)})
        links=normalized['receipt_links']
        triples=[(row['decision_id'],row['attempt_id'],row['preview_id']) for row in links]
        times=[datetime.fromisoformat(row['processed_at'].replace('Z','+00:00')) for row in links]
        if (not links or len(triples)!=len(set(triples)) or len(times)!=len(set(times)) or times!=sorted(times)
            or any(row['processed_at'][:10]!=normalized['source_day'] for row in links)):
            raise ValueError('ambiguous_empty_receipt_links')
    elif kind == "qt-read-set/v1":
        normalized = _read_set(payload)
    else:
        raise ValueError("unsupported_internal_snapshot")
    wire = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8", "strict")
    if len(wire) > _MAX_BYTES:
        raise ValueError("oversize_internal_snapshot")
    return wire


def internal_snapshot_digest(kind: str, payload: Mapping[str, object]) -> str:
    return sha256(canonical_internal_snapshot_bytes(kind, payload)).hexdigest()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class QtReadSet:
    source_day: str
    digest: str
    available: bool
    payload: Mapping[str, object]
    checked_at: str


def capture_qt_read_set(facts: Mapping[str, object]) -> QtReadSet:
    """Admit a transaction-selected snapshot; unavailable facts stay explicit.

    ``QtTransaction.read_current_facts`` is the production source. Its caller
    must acquire the A2 lock stages first; it fixes source day after waiting.
    """
    if not isinstance(facts, Mapping) or "captured_at" not in facts:
        raise ValueError("missing_transaction_capture_time")
    checked_at = _timestamp(facts["captured_at"])
    wire = canonical_internal_snapshot_bytes(
        "qt-read-set/v1", {name: value for name, value in facts.items() if name != "captured_at"}
    )
    normalized = json.loads(wire)
    captured = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    for source in normalized["external_sources"]:
        if source["status"] == "available":
            as_of = datetime.fromisoformat(source["as_of"].replace("Z", "+00:00"))
            until = datetime.fromisoformat(source["valid_until"].replace("Z", "+00:00"))
            if not as_of <= captured <= until:
                raise ValueError("stale_external_source")
    available = (
        normalized["provenance"]["status"] == "ready"
        and normalized["capability"]["status"] == "present"
        and normalized["capability"]["enabled"]
        and normalized["risk_limits"]["status"] == "present"
        and normalized["portfolio_inputs"]["status"] == "present"
        and normalized["evaluator"]["status"] == "available"
        and all(source["status"] == "available" for source in normalized["external_sources"])
        and normalized["saved_rows"] == [
            {name: row[name] for name in ("key", "quantity_exact", "average_price_exact")}
            for row in normalized["saved_accounting"]
        ]
    )
    return QtReadSet(normalized["source_day"], sha256(wire).hexdigest(), available,
                     _freeze(normalized), checked_at)

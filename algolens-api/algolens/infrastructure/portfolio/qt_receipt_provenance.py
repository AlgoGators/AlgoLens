"""Historical human ownership from actual immutable publication chains."""
from datetime import datetime, timezone
from hashlib import sha256
from collections.abc import Mapping

from algolens.domain.portfolio.qt_workflow_models import QtKey
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_publication_proof import validate_qt_publication_chain
from algolens.infrastructure.portfolio.qt_accounting_proof import current_accounting_after


def _audit_state_key(state):
    if not isinstance(state, Mapping):
        return None
    try:
        return QtKey.from_wire({name: state[name] for name in (
            "portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")})
    except (KeyError, TypeError, ValueError, QtWorkflowError):
        return None


def audit_is_other_qt_day(audit, book_id, day):
    """Exclude history only from a canonical, unambiguous actual full-key scope."""
    after = _audit_state_key(audit.get("after_state"))
    if (after is None or after.portfolio_type != "qt" or after.portfolio_id != book_id
            or after.date == day.isoformat()
            or (audit.get("portfolio_id"), audit.get("strategy_id"), audit.get("symbol"))
                != (after.portfolio_id, after.strategy_id, after.symbol)):
        return False
    before = _audit_state_key(audit.get("before_state"))
    if before == after:
        return True
    reference = audit.get("risk_check_result")
    return (audit.get("before_state") is None and isinstance(reference, Mapping)
        and reference.get("schema_version") == "qt-desk-audit/v1")


def _audit_matches_current(audit, current_keys, book_id):
    identities = {(key.strategy_id, key.symbol) for key in current_keys}
    return ((audit.get("portfolio_id") == book_id
             and (audit.get("strategy_id"), audit.get("symbol")) in identities)
            or any(_audit_state_key(audit.get(name)) in current_keys
                   for name in ("before_state", "after_state")))


def verified_receipt_chain(book_id, day, publications, audits, saved_accounting, *, recompute_client_factory=None,
                           finalization_recompute_client_factory=None):
    """Return verified complete accounting and editable choices, without financial inference."""
    if not isinstance(publications, (list, tuple)) or len(publications) > 4096:
        raise ValueError("invalid_receipt_set")
    verified = []
    checkpoints = {}
    seen_ids, seen_triples, empty_times = set(), set(), set()
    for evidence in publications:
        decision, receipt = evidence["decision"], evidence["receipt"]
        if decision["book_id"] != book_id or str(decision["source_day"]) != day.isoformat():
            raise ValueError("foreign_receipt_scope")
        triple = (str(decision["decision_id"]), str(receipt["attempt_id"]), str(decision["preview_id"]))
        if triple in seen_triples:
            raise ValueError("duplicate_receipt_identity")
        seen_triples.add(triple)
        prior_ids = {row["id"] for row in evidence["preview"]["read_set_payload"]["audit_refs"]}
        scoped = [row for row in audits if row["id"] in prior_ids or (
            isinstance(row.get("risk_check_result"), dict)
            and row["risk_check_result"].get("decision_id") == triple[0]
            and row["risk_check_result"].get("attempt_id") == triple[1])]
        proof = validate_qt_publication_chain({**evidence, "audits": scoped},
            recompute_client_factory=recompute_client_factory,
            finalization_recompute_client_factory=finalization_recompute_client_factory)
        audit_ids = sorted(proof["audit_additions"])
        empty_owner = proof.get('empty_owner')
        if (not audit_ids and empty_owner is None) or seen_ids.intersection(audit_ids):
            raise ValueError("ambiguous_receipt_audits")
        if empty_owner is not None:
            if proof['before'] or proof['after'] or proof['payload']['selection_rows'] or audit_ids:
                raise ValueError('inconsistent_empty_receipt')
            text = receipt['processed_at']
            if type(text) is not str or not text.endswith('Z'):
                raise ValueError('invalid_receipt_timestamp')
            stamp = datetime.fromisoformat(text.replace('Z','+00:00'))
            if (stamp.utcoffset() != timezone.utc.utcoffset(stamp) or stamp in empty_times
                    or stamp.isoformat().replace('+00:00','Z')!=text or stamp.date()!=day):
                raise ValueError('ambiguous_empty_receipt_order')
            empty_times.add(stamp)
        seen_ids.update(audit_ids)
        editable = {}
        for row in proof["payload"]["selection_rows"]:
            if row["editable"]:
                key = QtKey.from_wire({**row["key"], "portfolio_type": "qt"})
                editable[key] = proof["after"][key]
        link = {"decision_id": triple[0], "attempt_id": triple[1], "preview_id": triple[2],
            "publication_digest": sha256(canonical_qt_input_bytes(receipt["publication_payload"])).hexdigest(),
            "audit_ids": audit_ids, "source_keys": [key.to_wire() for key in sorted(editable)]}
        if empty_owner is not None:
            link['processed_at'] = stamp.isoformat().replace('+00:00','Z')
        consumed = {**decision, "draft_digest": evidence["preview"]["draft_digest"],
            "source_digest": evidence["preview"]["source_digest"],
            "selection_digest": qt_digest_v1({"selection_rows": proof["payload"]["selection_rows"]})}
        refs = [row for row in proof["original"]["publication_refs"]
            if row.get("schema_version") == "qt-empty-model-owner-reference/v2"
            and row["publication_id"] == str(decision["model_publication_id"])]
        if len(refs) == 1:
            ref = refs[0]
            consumed["empty_owner_choice"] = dict(schema_version="qt-empty-owner-choice/v2",
                model_publication_id=ref["publication_id"], owner_document_digest=ref["owner_document_digest"],
                configured_owner_names=list(ref["configured_owner_names"]))
        order = (1, stamp) if empty_owner is not None else (0, audit_ids[0])
        verified.append((order, proof, editable, link, consumed,
                         current_accounting_after(evidence,proof['after'],
                            recompute_client_factory=recompute_client_factory,
                            finalization_recompute_client_factory=finalization_recompute_client_factory)))
        # Raw actual timestamp is consumed strictly only by an archival join.
        # Ordinary v1 receipts retain the shared validator's original admission.
        checkpoints[triple]={'processed_at':receipt.get('processed_at'),'after':verified[-1][5]}
    verified.sort(key=lambda item: item[0])
    if not verified:
        current_keys = {QtKey.from_wire(row["key"]) for row in saved_accounting}
        for audit in audits:
            if audit_is_other_qt_day(audit, book_id, day):
                continue
            reference = audit.get("risk_check_result")
            if (isinstance(reference, dict) and reference.get("schema_version") == "qt-desk-audit/v1"
                    and _audit_matches_current(audit, current_keys, book_id)):
                raise ValueError("receipt_proof_missing")
        return None
    previous = None
    latest_choices = {}
    for _, proof, editable, link, decision, current_after in verified:
        if previous is not None and proof["before"] != previous:
            raise ValueError("receipt_accounting_chain_break")
        previous = current_after
        # Only the latest complete immutable preview's editable subset is human-owned.
        latest_choices = editable
    actual = {}
    required = {"key", "quantity_exact", "average_price_exact", "daily_unrealized_pnl_exact", "daily_realized_pnl_exact", "last_update"}
    for row in saved_accounting:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("missing_actual_accounting")
        key = QtKey.from_wire(row["key"])
        if key in actual or key.portfolio_id != book_id or key.date != day.isoformat() or key.portfolio_type != "qt":
            raise ValueError("foreign_actual_accounting")
        if any(type(row[name]) is not str or canonical_position_decimal8(row[name]) != row[name]
               for name in required - {"key", "last_update"}):
            raise ValueError("inexact_actual_accounting")
        if not isinstance(row["last_update"], str) or not row["last_update"].endswith("Z"):
            raise ValueError("missing_actual_accounting_time")
        datetime.fromisoformat(row["last_update"].replace("Z", "+00:00"))
        actual[key] = row
    if previous != actual:
        raise ValueError("receipt_current_accounting_mismatch")
    if len({item[0][0] for item in verified}) != 1:
        raise ValueError('mixed_empty_receipt_chain')
    first_id = verified[0][0][1] if verified[0][0][0] == 0 else None
    for audit in audits:
        if (first_id is not None and audit["id"] <= first_id) or audit["id"] in seen_ids:
            continue
        if audit_is_other_qt_day(audit, book_id, day):
            continue
        # A malformed current-key event cannot disappear just because it lacks
        # the exact state needed to prove continuity.
        if _audit_matches_current(audit, set(actual), book_id):
            raise ValueError("unproved_post_receipt_edit")
    return {"before": verified[0][1]["before"], "after": previous, "choices": latest_choices,
            "audit_ids": seen_ids, "links": tuple(item[3] for item in verified),
            "decisions": tuple(item[4] for item in verified),
            "checkpoints":tuple(checkpoints[(item[3]['decision_id'],item[3]['attempt_id'],item[3]['preview_id'])] for item in verified)}

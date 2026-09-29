"""Real linked immutable receipt proof preserves a human choice, never MODEL."""
from copy import deepcopy
from datetime import date
from hashlib import sha256
from types import SimpleNamespace
from pathlib import Path
import json

import pytest

from algolens.domain.portfolio.qt_canonical import qt_digest_v1, canonical_qt_bytes, qt_book_digest_v1
from algolens.domain.portfolio.qt_workflow_models import QtSelectionRow
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_provenance import reconcile_qt_source
from algolens.infrastructure.portfolio.qt_read_set import internal_snapshot_digest
from algolens.infrastructure.portfolio.qt_read_set import canonical_internal_snapshot_bytes
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.application.portfolio.qt_workflow import QtWorkflowService
from tests.test_qt_decision_read import processed_fixture


def receipt_source(monkeypatch):
    evidence = processed_fixture(monkeypatch)
    original = evidence["preview"]["read_set_payload"]
    source, system = deepcopy(original["source_rows"]), deepcopy(original["system_rows"])
    pub_id = evidence["decision"]["model_publication_id"]
    components = [{"key": row["key"], "quantity_exact": row["quantity_exact"],
        "average_price_exact": row["average_price_exact"], "action": "inserted",
        "position_revision": row["position_revision"], "origin_publication_id": pub_id} for row in source]
    publication = {"publication_id": pub_id, "attempt_id": None, "portfolio_id": "BOOK",
        "strategy_id": system[0]["key"]["strategy_id"], "source_day": date(2026, 9, 25),
        "publication_version": 1, "system_components": system,
        "seed_digest": qt_digest_v1({"seed_rows": system}), "producer_version": "synthetic-proof",
        "proposal_components": components,
        "proposal_manifest_digest": internal_snapshot_digest("qt-proposal-manifest/v1", {"proposal_rows": components})}
    return evidence, source, system, publication


def reconcile(evidence, source, system, publication):
    return reconcile_qt_source("BOOK", date(2026, 9, 25), [publication], source, evidence["audits"],
        observed_system_rows=system, observed_saved_rows=evidence["current_facts"]["saved_rows"],
        observed_saved_accounting=evidence["current_facts"]["saved_accounting"],
        processed_publications=[evidence])


def test_processed_human_choice_has_independent_receipt_origin(monkeypatch):
    evidence, source, system, publication = receipt_source(monkeypatch)
    result = reconcile(evidence, source, system, publication)
    assert result.status == "ready"
    assert result.draft_overlay[0].quantity_exact == "2"
    assert result.draft_overlay[0].average_price_exact == "101"
    assert result.seed_rows[0].quantity_exact != "2"
    assert result.verified_qt_edits[0].origin == "verified_qt_decision"
    assert result.receipt_links[0]["decision_id"] == evidence["decision"]["decision_id"]
    assert result.receipt_links[0]["source_keys"] == [evidence["receipt"]["publication_payload"]["after_accounting"][0]["key"]]


@pytest.mark.parametrize("part", ["missing_receipt", "audit_reference", "audit_actor", "before", "result", "physical_pnl", "physical_time", "extra_current"])
def test_unproved_receipt_or_current_accounting_cannot_become_human_origin(monkeypatch, part):
    evidence, source, system, publication = receipt_source(monkeypatch)
    if part == "missing_receipt": evidence["receipt"] = None
    elif part == "audit_reference": evidence["audits"][0]["risk_check_result"]["attempt_id"] = "00000000-0000-4000-8000-000000000099"
    elif part == "audit_actor": evidence["audits"][0]["user_id"] = 999
    elif part == "before": evidence["audits"][0]["before_state"] = None
    elif part == "result": evidence["result"]["content_digest"] = "0" * 64
    elif part == "physical_pnl": evidence["current_facts"]["saved_accounting"][0]["daily_unrealized_pnl_exact"] = "999"
    elif part == "physical_time": evidence["current_facts"]["saved_accounting"][0]["last_update"] = "2026-09-25T12:01:00Z"
    else:
        extra = deepcopy(evidence["current_facts"]["saved_accounting"][0])
        extra["key"]["symbol"] = "EXTRA"
        evidence["current_facts"]["saved_accounting"].append(extra)
        evidence["current_facts"]["saved_rows"].append({name: extra[name] for name in ("key", "quantity_exact", "average_price_exact")})
    assert reconcile(evidence, source, system, publication).status == "provenance_unresolved"


def test_new_public_human_origin_is_closed_and_does_not_claim_seed(monkeypatch):
    evidence = processed_fixture(monkeypatch)
    row = {**evidence["preview"]["payload"]["selection_rows"][0], "origin": "verified_qt_decision"}
    assert QtSelectionRow.from_wire(row).origin == "verified_qt_decision"
    with pytest.raises(QtWorkflowError): canonical_qt_bytes({"selection_rows": [{**row, "origin": "invented_model_claim"}]})


def add_new_choice(evidence, *, immutable=False):
    preview, decision = evidence["preview"], evidence["decision"]
    original = preview["read_set_payload"]
    after = deepcopy(evidence["receipt"]["publication_payload"]["after_accounting"][0])
    after.update(quantity_exact="3", average_price_exact="102", daily_unrealized_pnl_exact="2",
                 daily_realized_pnl_exact="-0.5")
    after["key"]["symbol"] = "IMM" if immutable else "NEW"
    row = {**deepcopy(preview["payload"]["selection_rows"][0]), "key": {**after["key"], "portfolio_type": "qt_proposal"},
           "quantity_exact": "3", "basis_status": "preserved_source" if immutable else "unfilled",
           "average_price_exact": "102" if immutable else None, "editable": not immutable,
           "origin": "immutable" if immutable else "qt_draft"}
    if immutable: row["key"]["portfolio_type"] = "qt"
    preview["payload"]["selection_rows"].append(row)
    preview["draft_digest"] = original["draft"]["digest"] = qt_digest_v1({"selection_rows": preview["payload"]["selection_rows"]})
    if immutable:
        original["saved_accounting"].append(deepcopy(after))
        original["saved_rows"].append({name: deepcopy(after[name]) for name in ("key", "quantity_exact", "average_price_exact")})
        evidence["receipt"]["publication_payload"]["before_accounting"].append(deepcopy(after))
    evidence["receipt"]["publication_payload"]["after_accounting"].append(after)
    evidence["current_facts"]["saved_accounting"].append(deepcopy(after))
    evidence["current_facts"]["saved_rows"].append({name: deepcopy(after[name]) for name in ("key", "quantity_exact", "average_price_exact")})
    digest = qt_book_digest_v1([{"key": {**item["key"], "portfolio_type": "qt"}, "quantity_exact": item["quantity_exact"]}
                              for item in preview["payload"]["selection_rows"]], source_portfolio_type="qt")
    preview["selected_book_digest"] = preview["payload"]["selected_book_digest"] = decision["selected_book_digest"] = digest
    risk, cost = (preview["payload"]["evaluation"][name] for name in ("selected_risk", "selected_costs"))
    risk["evaluated_book_digest"] = cost["evaluated_book_digest"] = digest
    if not immutable:
        cost["total_exact"] = "0.05"
        cost["by_component"].append({"key": row["key"], "prior_quantity_exact": "0", "selected_quantity_exact": "3",
                                     "cash_cost_exact": "0.03", "source_id": "unit-cost"})
    observation = evidence["observation"]
    fill = {name: deepcopy(value) for name, value in after.items() if name != "quantity_exact"}
    fill.update(selected_quantity_exact="3", observation_kind="carried" if immutable else "executed",
                actual_cash_cost_exact="0" if immutable else "0.03", currency="USD",
                execution_id=None if immutable else "execution-new", accounting_source_id="accounting-new")
    observation["payload"]["fills"].append(fill)
    observation["payload"]["results"] = {"position_count": 2, "currency_totals": [{"currency": "USD",
        "actual_cash_cost_exact": "0.02" if immutable else "0.05", "daily_unrealized_pnl_exact": "5", "daily_realized_pnl_exact": "-1.5"}]}
    observation["content_digest"] = sha256(canonical_qt_input_bytes(observation["payload"])).hexdigest()
    result = evidence["result"]
    result["payload"].update(selected_book_digest=digest, results=deepcopy(observation["payload"]["results"]))
    result["content_digest"] = sha256(canonical_qt_input_bytes(result["payload"])).hexdigest()
    read_digest = sha256(canonical_internal_snapshot_bytes("qt-read-set/v1", original)).hexdigest()
    preview["read_set_digest"] = preview["payload"]["read_set_digest"] = decision["read_set_digest"] = read_digest
    preview["payload"]["payload_digest"] = qt_digest_v1({name: value for name, value in preview["payload"].items() if name != "payload_digest"})
    preview["payload_digest"] = preview["payload"]["payload_digest"]
    decision["payload"].update(preview_payload_digest=preview["payload_digest"], selected_book_digest=digest, read_set_digest=read_digest)
    receipt = evidence["receipt"]
    receipt["published_book_digest"] = digest
    receipt["publication_payload"].update(selected_book_digest=digest, published_book_digest=digest,
        read_set_digest=read_digest, preview_payload_digest=preview["payload_digest"],
        observation_digest=observation["content_digest"], results_digest=result["content_digest"], report_scope=None)
    reference = evidence["audits"][0]["risk_check_result"]
    reference.update(preview_payload_digest=preview["payload_digest"], read_set_digest=read_digest,
                     selected_book_digest=digest, published_book_digest=digest, observation_digest=observation["content_digest"])
    flat = {**after["key"], "quantity_exact": "3", "average_price_exact": "102"}
    evidence["audits"].append({**deepcopy(evidence["audits"][0]), "id": 101, "symbol": after["key"]["symbol"],
                              "before_state": deepcopy(flat) if immutable else None, "after_state": flat})
    return evidence


def test_genuinely_new_key_keeps_absent_before_and_becomes_editable_human_choice(monkeypatch):
    evidence, source, system, publication = receipt_source(monkeypatch)
    add_new_choice(evidence)
    result = reconcile(evidence, source, system, publication)
    assert result.status == "ready" and len(result.draft_overlay) == 2
    tx = SimpleNamespace(resolve_instrument_types=lambda keys, registry_asset_class=None: {key: "EQUITY" for key in keys})
    base, immutable = QtWorkflowService._base_rows(tx, {"saved_rows": evidence["current_facts"]["saved_rows"]}, result)
    new = next(row for key, row in base.items() if key.symbol == "NEW")
    assert new.editable and new.quantity_exact == "3" and new.average_price_exact == "102"
    assert new.origin == "verified_qt_decision" and not immutable
    evidence["audits"][1]["before_state"] = {**evidence["audits"][1]["after_state"], "quantity_exact": "0", "average_price_exact": "0"}
    assert reconcile(evidence, source, system, publication).status == "provenance_unresolved"


def test_complete_book_audit_does_not_relabel_immutable_carried_holding(monkeypatch):
    evidence, source, system, publication = receipt_source(monkeypatch)
    add_new_choice(evidence, immutable=True)
    result = reconcile(evidence, source, system, publication)
    assert result.status == "ready" and len(result.draft_overlay) == 1
    tx = SimpleNamespace(resolve_instrument_types=lambda keys, registry_asset_class=None: {key: "EQUITY" for key in keys})
    base, immutable = QtWorkflowService._base_rows(tx, {"saved_rows": evidence["current_facts"]["saved_rows"]}, result)
    assert len(base) == 1 and len(immutable) == 1
    assert immutable[0].key.symbol == "IMM" and immutable[0].origin == "immutable" and not immutable[0].editable


def test_authoritative_literal_vector_binds_verified_new_human_choice():
    fixture = json.loads((Path(__file__).resolve().parents[2] / "contracts/qt-workflow-v1.json").read_text())
    vector = fixture["canonical_vectors"][-1]
    row = vector["input"]["selection_rows"][0]
    assert row["origin"] == "verified_qt_decision" and row["key"]["symbol"] == "NEW"
    assert QtSelectionRow.from_wire(row).editable
    wire = canonical_qt_bytes(vector["input"])
    assert wire.decode() == vector["canonical_json"] and sha256(wire).hexdigest() == vector["sha256"]


@pytest.mark.parametrize("malformed", [False, True])
def test_new_key_receipt_claim_without_linked_sql_receipt_is_unavailable(monkeypatch, malformed):
    evidence, source, system, publication = receipt_source(monkeypatch)
    add_new_choice(evidence)
    # The existing MODEL key has no edit; only the new key claims desk origin.
    evidence["audits"] = evidence["audits"][1:]
    if malformed: evidence["audits"][0]["after_state"] = {"quantity": 3.0}
    result = reconcile_qt_source("BOOK", date(2026, 9, 25), [publication], source, evidence["audits"],
        observed_system_rows=system, observed_saved_rows=evidence["current_facts"]["saved_rows"],
        observed_saved_accounting=evidence["current_facts"]["saved_accounting"], processed_publications=[])
    assert result.status == "provenance_unresolved"


def test_malformed_later_edit_of_receipt_owned_new_key_is_not_invisible(monkeypatch):
    evidence, source, system, publication = receipt_source(monkeypatch)
    add_new_choice(evidence)
    evidence["audits"].append({**deepcopy(evidence["audits"][1]), "id": 102,
        "risk_check_result": None, "after_state": {"quantity": 3.0}, "before_state": None})
    assert reconcile(evidence, source, system, publication).status == "provenance_unresolved"


def test_explicit_other_day_history_does_not_poison_current_receipt(monkeypatch):
    evidence, source, system, publication = receipt_source(monkeypatch)
    unrelated = deepcopy(evidence["audits"][0])
    unrelated.update(id=102, risk_check_result=None)
    for state in ("before_state", "after_state"):
        unrelated[state]["date"] = "2026-09-24"
    evidence["audits"].append(unrelated)
    assert reconcile(evidence, source, system, publication).status == "ready"


@pytest.mark.parametrize("null_before", [False, True])
@pytest.mark.parametrize("current_receipt", [False, True])
def test_canonical_prior_day_desk_audit_does_not_claim_current_receipt(monkeypatch, null_before, current_receipt):
    evidence, source, system, publication = receipt_source(monkeypatch)
    prior = deepcopy(evidence["audits"][0])
    prior["id"] = 99
    prior["risk_check_result"].update(decision_id="00000000-0000-4000-8000-000000000091",
        attempt_id="00000000-0000-4000-8000-000000000092", preview_id="00000000-0000-4000-8000-000000000093")
    for state in ("before_state", "after_state"):
        prior[state]["date"] = "2026-09-24"
    if null_before: prior["before_state"] = None
    evidence["audits"] = ([*evidence["audits"], prior] if current_receipt else [prior])
    result = reconcile_qt_source("BOOK", date(2026, 9, 25), [publication], source, evidence["audits"],
        observed_system_rows=system, observed_saved_rows=evidence["current_facts"]["saved_rows"],
        observed_saved_accounting=evidence["current_facts"]["saved_accounting"],
        processed_publications=[evidence] if current_receipt else [])
    assert result.status == "ready"
    if not current_receipt: assert not result.verified_qt_edits


@pytest.mark.parametrize("dates", [("not-a-date", "not-a-date"), ("2026-09-23", "2026-09-24"),
    ("2026-09-24", "2026-09-25"), ("20260924", "20260924")])
def test_later_current_new_key_audit_requires_canonical_unambiguous_day_scope(monkeypatch, dates):
    evidence, source, system, publication = receipt_source(monkeypatch)
    add_new_choice(evidence)
    later = deepcopy(evidence["audits"][1])
    later.update(id=102, risk_check_result=None)
    later["before_state"] = deepcopy(later["after_state"])
    for state, day in zip(("before_state", "after_state"), dates): later[state]["date"] = day
    evidence["audits"].append(later)
    assert reconcile(evidence, source, system, publication).status == "provenance_unresolved"


@pytest.mark.parametrize("tamper", ["unknown", "duplicate", "foreign"])
def test_receipt_provenance_envelope_is_closed_scoped_and_unique(monkeypatch, tamper):
    evidence, source, system, publication = receipt_source(monkeypatch)
    result = reconcile(evidence, source, system, publication)
    envelope = {"schema_version": "qt-receipt-provenance/v1", "book_id": "BOOK", "source_day": "2026-09-25",
        "legacy_chain_digest": "a" * 64, "receipt_links": deepcopy(list(result.receipt_links))}
    valid = canonical_internal_snapshot_bytes("qt-receipt-provenance/v1", envelope)
    assert sha256(valid).hexdigest() == internal_snapshot_digest("qt-receipt-provenance/v1", envelope)
    if tamper == "unknown": envelope["receipt_links"][0]["claimed_actor"] = 101
    elif tamper == "duplicate": envelope["receipt_links"].append(deepcopy(envelope["receipt_links"][0]))
    else: envelope["receipt_links"][0]["source_keys"][0]["portfolio_id"] = "OTHER"
    with pytest.raises(ValueError): canonical_internal_snapshot_bytes("qt-receipt-provenance/v1", envelope)

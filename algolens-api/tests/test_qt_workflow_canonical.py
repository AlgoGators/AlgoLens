"""Contract tests for the versioned QT wire boundary."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from algolens.domain.portfolio.qt_canonical import canonical_qt_bytes, qt_digest_v1, qt_book_digest_v1
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import (
    QtKey, QtProposalResponse, QtDraftResponse, QtPreviewResponse,
    QtDecisionResponse, QtDraftSaveRequest, parse_qt_selection,
)


KEY_A = {
    "portfolio_id": "book-A", "strategy_id": "17", "strategy_name": "alpha",
    "date": "2026-09-25", "symbol": "ES", "portfolio_type": "qt_proposal",
}
KEY_B = {
    "portfolio_id": "book-A", "strategy_id": "18", "strategy_name": "beta",
    "date": "2026-09-25", "symbol": "ES", "portfolio_type": "qt_proposal",
}


def test_digest_independent_of_mapping_insertion_order():
    left = {"quantity_exact": "1.25", "symbol": "ES"}
    right = {"symbol": "ES", "quantity_exact": "1.25"}
    assert canonical_qt_bytes(left) == b'{"quantity_exact":"1.25","symbol":"ES"}'
    assert canonical_qt_bytes(left) == canonical_qt_bytes(right)
    assert qt_digest_v1(left) == qt_digest_v1(right)


@pytest.mark.parametrize("value", [1.25, "1.25000000", "01", "-0", "0.000000001"])
def test_float_and_noncanonical_decimal_rejected(value):
    with pytest.raises(QtWorkflowError):
        canonical_qt_bytes({"quantity_exact": value})


def test_adjacent_decimal8_values_have_different_digests():
    assert qt_digest_v1({"quantity_exact": "1.00000001"}) != qt_digest_v1({"quantity_exact": "1.00000002"})


def test_component_rows_sort_by_complete_key_and_preserve_zero_short_offset():
    rows = [
        {"key": KEY_B, "quantity_exact": "-3"},
        {"key": KEY_A, "quantity_exact": "3"},
    ]
    forward = canonical_qt_bytes({"selection_rows": rows})
    assert forward == canonical_qt_bytes({"selection_rows": list(reversed(rows))})
    assert forward.index(b'"strategy_id":"17"') < forward.index(b'"strategy_id":"18"')
    assert b'"quantity_exact":"-3"' in forward
    assert b'"quantity_exact":"3"' in forward
    assert b'"quantity_exact":"0"' in canonical_qt_bytes({"selection_rows": [{"key": KEY_A, "quantity_exact": "0"}]})


def test_unknown_and_duplicate_fields_rejected():
    with pytest.raises(QtWorkflowError):
        canonical_qt_bytes({"quantity_exact": "1", "surprise": "x"})
    with pytest.raises(QtWorkflowError):
        canonical_qt_bytes({"key": {**KEY_A, "extra": "x"}})
    with pytest.raises(QtWorkflowError):
        canonical_qt_bytes({"selection_rows": [{"key": KEY_A, "key_duplicate": KEY_A, "quantity_exact": "1"}]})
    with pytest.raises(QtWorkflowError):
        canonical_qt_bytes({"selection_rows": [{"key": KEY_A, "quantity_exact": "1", "status": "ready"}]})


def test_duplicate_json_field_rejected_before_mapping_construction():
    from algolens.domain.portfolio.qt_canonical import parse_qt_json

    with pytest.raises(QtWorkflowError):
        parse_qt_json(b'{"quantity_exact":"1","quantity_exact":"2"}')


def test_unicode_and_integer_boundaries():
    assert canonical_qt_bytes({"symbol": "Café"}) == b'{"symbol":"Caf\xc3\xa9"}'
    for payload in ({"symbol": "\ud800"}, {"draft_revision": 2**63}, {"draft_revision": True}):
        with pytest.raises(QtWorkflowError):
            canonical_qt_bytes(payload)


def test_key_full_identity_and_future_whole_rule():
    a, b = QtKey.from_wire(KEY_A), QtKey.from_wire(KEY_B)
    assert a != b
    assert len({a, b}) == 2
    rows = parse_qt_selection(
        [{"key": KEY_A, "quantity_exact": "2.5"}, {"key": KEY_B, "quantity_exact": "-3"}],
        frozenset({a, b}), {a: "EQUITY", b: "FUTURE"},
    )
    assert [row.quantity_exact for row in rows] == ["2.5", "-3"]
    with pytest.raises(QtWorkflowError):
        parse_qt_selection([{"key": KEY_B, "quantity_exact": "-3.1"}], frozenset({b}), {b: "FUTURE"})
    with pytest.raises(QtWorkflowError):
        parse_qt_selection([{"key": KEY_A, "quantity_exact": "1"}, {"key": KEY_A, "quantity_exact": "2"}], frozenset({a}), {a: "EQUITY"})


def test_fixture_vectors_are_literal_wire_oracles():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    assert set(fixture) == {
        "schema_version", "proposal_ready", "draft_saved", "preview_clean", "preview_breach",
        "confirm_pending", "decision_processed", "decision_pending", "stale_error", "canonical_vectors",
    }
    assert fixture["schema_version"] == "qt-workflow/v1"
    for vector in fixture["canonical_vectors"]:
        wire = vector["canonical_json"].encode("utf-8")
        assert canonical_qt_bytes(vector["input"]) == wire
        assert qt_digest_v1(vector["input"]) == vector["sha256"]
        assert hashlib.sha256(wire).hexdigest() == vector["sha256"]


def test_narrow_model_seed_record_is_canonical_and_keyed_as_system():
    seed = {"seed_rows": [{"key": {**KEY_A, "portfolio_type": "system"}, "quantity_exact": "4", "average_price_exact": "100"}]}
    wire = canonical_qt_bytes(seed)
    assert b'"portfolio_type":"system"' in wire
    assert b'"quantity_exact":"4"' in wire


def test_selected_book_digest_uses_target_qt_keys_and_quantity_only():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    selected = fixture["draft_saved"]["selection_rows"]
    assert qt_book_digest_v1(selected, source_portfolio_type="qt_proposal") == fixture["preview_clean"]["selected_book_digest"]
    published = [{"key": {**row["key"], "portfolio_type": "qt"}, "quantity_exact": row["quantity_exact"], "average_price_exact": "101"} for row in selected]
    assert qt_book_digest_v1(published, source_portfolio_type="qt") == fixture["decision_processed"]["receipt"]["published_book_digest"]
    with pytest.raises(QtWorkflowError):
        qt_book_digest_v1(selected, source_portfolio_type="qt")


def test_all_fixture_examples_pass_typed_contract_and_share_selection():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    QtProposalResponse.from_wire(fixture["proposal_ready"])
    QtDraftResponse.from_wire(fixture["draft_saved"])
    clean = QtPreviewResponse.from_wire(fixture["preview_clean"])
    breach = QtPreviewResponse.from_wire(fixture["preview_breach"])
    for name in ("confirm_pending", "decision_processed", "decision_pending"):
        QtDecisionResponse.from_wire(fixture[name])
    assert [row["quantity_exact"] for row in fixture["proposal_ready"]["seed_rows"]] == ["4", "2"]
    assert [row["quantity_exact"] for row in fixture["draft_saved"]["selection_rows"]] == ["5", "1"]
    assert clean.to_wire()["selection_rows"] == breach.to_wire()["selection_rows"] == fixture["draft_saved"]["selection_rows"]
    assert clean.to_wire()["evaluation"]["selected_costs"]["by_component"] == breach.to_wire()["evaluation"]["selected_costs"]["by_component"]
    assert fixture["decision_processed"]["selected_book_digest"] == clean.payload["selected_book_digest"]
    selected_vector = fixture["canonical_vectors"][2]
    optimizer_vector = fixture["canonical_vectors"][3]
    assert clean.payload["selected_book_digest"] == breach.payload["selected_book_digest"] == selected_vector["sha256"]
    assert clean.payload["optimizer_book_digest"] == optimizer_vector["sha256"]
    for name in ("preview_clean", "preview_breach"):
        preview = fixture[name]
        assert preview["payload_digest"] == qt_digest_v1({k: v for k, v in preview.items() if k != "payload_digest"})


def test_typed_preview_cannot_claim_clean_on_missing_stage():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    broken = json.loads(json.dumps(fixture["preview_clean"]))
    broken["evaluation"]["selected_risk"]["status"] = "unavailable"
    broken["payload_digest"] = qt_digest_v1({name: value for name, value in broken.items() if name != "payload_digest"})
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(broken)


def test_ready_preview_requires_component_costs_for_each_selected_edit():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    broken = json.loads(json.dumps(fixture["preview_clean"]))
    broken["evaluation"]["selected_costs"]["by_component"] = []
    broken["payload_digest"] = qt_digest_v1({name: value for name, value in broken.items() if name != "payload_digest"})
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(broken)


def test_decision_rejects_duplicate_approver_and_bad_utc_timestamp():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    broken = json.loads(json.dumps(fixture["confirm_pending"]))
    broken["approvals"] = [
        {"person_id": "john_riley", "display_label": "John Riley", "user_id": "101", "approved_at": "2026-09-25T12:00:00Z"},
        {"person_id": "john_riley", "display_label": "John Riley", "user_id": "102", "approved_at": "2026-09-25T12:01:00Z"},
    ]
    broken["approvals_count"] = 2
    with pytest.raises(QtWorkflowError):
        QtDecisionResponse.from_wire(broken)
    broken["approvals"] = [{**broken["approvals"][0], "approved_at": "yesterday"}]
    broken["approvals_count"] = 1
    with pytest.raises(QtWorkflowError):
        QtDecisionResponse.from_wire(broken)


def test_confirmed_override_keeps_request_id_and_two_distinct_approvals():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    approved = json.loads(json.dumps(fixture["confirm_pending"]))
    approved["status"] = "confirmed_decision"
    approved["approvals"] = [
        {"person_id": "xander_robbins", "display_label": "Xander Robbins", "user_id": "101", "approved_at": "2026-09-25T12:00:00Z"},
        {"person_id": "hemdutt_rao", "display_label": "Hemdutt Rao", "user_id": "102", "approved_at": "2026-09-25T12:01:00Z"},
    ]
    approved["approvals_count"] = 2
    approved["report_blocked_reasons"] = ["receipt_pending"]
    assert QtDecisionResponse.from_wire(approved).payload["request_id"] == fixture["confirm_pending"]["request_id"]


def test_saved_draft_and_ready_proposal_need_authoritative_identities():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    draft = json.loads(json.dumps(fixture["draft_saved"]))
    draft["draft_id"] = None
    with pytest.raises(QtWorkflowError):
        QtDraftResponse.from_wire(draft)
    proposal = json.loads(json.dumps(fixture["proposal_ready"]))
    proposal["seed_publication_id"] = None
    with pytest.raises(QtWorkflowError):
        QtProposalResponse.from_wire(proposal)


def test_validated_preview_is_immutable_and_detached_from_caller():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    incoming = fixture["preview_clean"]
    response = QtPreviewResponse.from_wire(incoming)
    incoming["selection_rows"][0]["quantity_exact"] = "999"
    assert response.to_wire()["selection_rows"][0]["quantity_exact"] == "5"
    with pytest.raises(TypeError):
        response.payload["selection_rows"][0]["quantity_exact"] = "999"
    exported = response.to_wire()
    exported["selection_rows"][0]["quantity_exact"] = "777"
    assert response.to_wire()["selection_rows"][0]["quantity_exact"] == "5"
    assert response.to_wire()["payload_digest"] == fixture["preview_clean"]["payload_digest"]


def test_preview_rejects_quantity_tamper_with_original_digest_labels():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    preview = deepcopy(fixture["preview_clean"])
    preview["selection_rows"][0]["quantity_exact"] = "6"
    preview["evaluation"]["selected_costs"]["by_component"][0]["selected_quantity_exact"] = "6"
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(preview)


def test_preview_rejects_evidence_tamper_without_payload_digest_update():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    preview = deepcopy(fixture["preview_clean"])
    preview["evaluation"]["selected_risk"]["metrics"][0]["value_exact"] = "601"
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(preview)


def test_preview_rejects_synchronized_fake_book_digest_even_with_new_payload_digest():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    preview = deepcopy(fixture["preview_clean"])
    preview["selection_rows"][0]["quantity_exact"] = "6"
    preview["evaluation"]["selected_costs"]["by_component"][0]["selected_quantity_exact"] = "6"
    fake = "0" * 64
    preview["selected_book_digest"] = fake
    preview["evaluation"]["selected_risk"]["evaluated_book_digest"] = fake
    preview["evaluation"]["selected_costs"]["evaluated_book_digest"] = fake
    preview["payload_digest"] = qt_digest_v1({name: value for name, value in preview.items() if name != "payload_digest"})
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(preview)


@pytest.mark.parametrize("response_name,row_name,model", [
    ("proposal_ready", "seed_rows", QtProposalResponse),
    ("proposal_ready", "saved_qt_rows", QtProposalResponse),
    ("draft_saved", "selection_rows", QtDraftResponse),
])
def test_display_rows_reject_narrow_digest_projection(response_name, row_name, model):
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    response = deepcopy(fixture[response_name])
    row = deepcopy(fixture["proposal_ready"]["seed_rows"][0])
    if row_name == "saved_qt_rows":
        row["key"]["portfolio_type"] = "qt"
    response[row_name] = [{"key": row["key"], "quantity_exact": row["quantity_exact"]}]
    with pytest.raises(QtWorkflowError):
        model.from_wire(response)


def test_proposal_seed_display_rejects_narrow_model_seed_digest_record():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    proposal = deepcopy(fixture["proposal_ready"])
    seed = proposal["seed_rows"][0]
    proposal["seed_rows"] = [{"key": seed["key"], "quantity_exact": seed["quantity_exact"], "average_price_exact": seed["average_price_exact"]}]
    with pytest.raises(QtWorkflowError):
        QtProposalResponse.from_wire(proposal)


@pytest.mark.parametrize("field", ["basis_status", "average_price_exact", "asset_type", "editable", "origin"])
@pytest.mark.parametrize("response_name,row_name,model", [
    ("proposal_ready", "seed_rows", QtProposalResponse),
    ("proposal_ready", "saved_qt_rows", QtProposalResponse),
    ("draft_saved", "selection_rows", QtDraftResponse),
])
def test_display_rows_require_every_metadata_field(response_name, row_name, model, field):
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    response = deepcopy(fixture[response_name])
    row = deepcopy(fixture["proposal_ready"]["seed_rows"][0])
    if row_name == "saved_qt_rows":
        row["key"]["portfolio_type"] = "qt"
    row.pop(field)
    response[row_name] = [row]
    with pytest.raises(QtWorkflowError):
        model.from_wire(response)


@pytest.mark.parametrize("identity,value", [("portfolio_id", "foreign-book"), ("date", "2026-09-26")])
@pytest.mark.parametrize("response_name,row_name,model", [
    ("proposal_ready", "seed_rows", QtProposalResponse),
    ("proposal_ready", "saved_qt_rows", QtProposalResponse),
    ("draft_saved", "selection_rows", QtDraftResponse),
])
def test_display_rows_reject_foreign_scope(response_name, row_name, model, identity, value):
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    response = deepcopy(fixture[response_name])
    row = deepcopy(fixture["proposal_ready"]["seed_rows"][0])
    if row_name == "saved_qt_rows":
        row["key"]["portfolio_type"] = "qt"
    row["key"][identity] = value
    response[row_name] = [row]
    with pytest.raises(QtWorkflowError):
        model.from_wire(response)


def test_draft_save_request_still_accepts_narrow_key_quantity_rows():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    draft = fixture["draft_saved"]
    request = {
        "expected_source_digest": draft["source_digest"],
        "expected_provenance_digest": draft["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "60000000-0000-4000-8000-000000000001",
        "rationale": "Reduce concentration before the event window.",
        "selection_rows": [{"key": row["key"], "quantity_exact": row["quantity_exact"]} for row in draft["selection_rows"]],
    }
    decoded = QtDraftSaveRequest.from_wire(request).to_wire()
    assert decoded["rationale"] == "Reduce concentration before the event window."
    assert len(decoded["selection_rows"]) == 2


@pytest.mark.parametrize("rationale", [None, "", "   ", "x" * 1001, "é" * 501])
def test_draft_save_request_requires_bounded_utf8_rationale(rationale):
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    draft = fixture["draft_saved"]
    request = {
        "expected_source_digest": draft["source_digest"],
        "expected_provenance_digest": draft["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "60000000-0000-4000-8000-000000000001",
        "rationale": rationale,
        "selection_rows": [{"key": row["key"], "quantity_exact": row["quantity_exact"]} for row in draft["selection_rows"]],
    }
    with pytest.raises(QtWorkflowError):
        QtDraftSaveRequest.from_wire(request)


def test_draft_save_request_trims_rationale():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    draft = fixture["draft_saved"]
    request = {
        "expected_source_digest": draft["source_digest"],
        "expected_provenance_digest": draft["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "60000000-0000-4000-8000-000000000001",
        "rationale": "  Reduce concentration.  ",
        "selection_rows": [{"key": row["key"], "quantity_exact": row["quantity_exact"]} for row in draft["selection_rows"]],
    }
    assert QtDraftSaveRequest.from_wire(request).to_wire()["rationale"] == "Reduce concentration."


def test_draft_rationale_changes_the_immutable_draft_digest():
    rows = [{"key": KEY_A, "quantity_exact": "1"}]
    assert qt_digest_v1({"rationale": "Reduce concentration.", "selection_rows": rows}) != qt_digest_v1(
        {"rationale": "Increase liquidity.", "selection_rows": rows}
    )


def test_proposal_accepts_complete_saved_qt_display_row():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    proposal = deepcopy(fixture["proposal_ready"])
    saved = deepcopy(proposal["seed_rows"][0])
    saved["key"]["portfolio_type"] = "qt"
    saved["origin"] = "qt_draft"
    proposal["saved_qt_rows"] = [saved]
    assert QtProposalResponse.from_wire(proposal).to_wire()["saved_qt_rows"] == [saved]


def test_preview_rejects_implicit_system_to_qt_stream_mapping():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    preview = deepcopy(fixture["preview_clean"])
    preview["selection_rows"][0]["key"]["portfolio_type"] = "system"
    preview["evaluation"]["selected_costs"]["by_component"][0]["key"]["portfolio_type"] = "system"
    preview["payload_digest"] = qt_digest_v1({name: value for name, value in preview.items() if name != "payload_digest"})
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(preview)


def test_finite_risk_diagnostic_can_exceed_decimal8_precision():
    expected = b'{"value_diagnostic":"0.12345678901234566"}'
    assert canonical_qt_bytes({"value_diagnostic": "0.12345678901234566"}) == expected
    assert canonical_qt_bytes({"value_diagnostic": "5e-324"}) == b'{"value_diagnostic":"5e-324"}'


@pytest.mark.parametrize("value", [1.25, "NaN", "Infinity", "1e309", "1e-999", "-1e-999"])
def test_risk_diagnostic_rejects_float_nonfinite_or_out_of_double_range(value):
    with pytest.raises(QtWorkflowError):
        canonical_qt_bytes({"value_diagnostic": value})


def test_fixture_uses_new_risk_diagnostic_fields_and_non_decimal8_value():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    for name in ("preview_clean", "preview_breach"):
        risk = fixture[name]["evaluation"]["selected_risk"]
        assert risk["metrics"][0]["value_diagnostic"] == "0.12345678901234566"
        assert "value_exact" not in risk["metrics"][0]
        for breach in risk["breaches"]:
            assert set(breach) == {"code", "limit_diagnostic", "actual_diagnostic"}
        assert QtPreviewResponse.from_wire(fixture[name]).payload["payload_digest"] == fixture[name]["payload_digest"]


def test_legacy_risk_exact_field_names_rejected_in_preview():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    preview = deepcopy(fixture["preview_breach"])
    metric = preview["evaluation"]["selected_risk"]["metrics"][0]
    metric.pop("value_diagnostic", None)
    metric["value_exact"] = "0.12345678"
    breach = preview["evaluation"]["selected_risk"]["breaches"][0]
    breach.pop("limit_diagnostic", None)
    breach.pop("actual_diagnostic", None)
    breach["limit_exact"] = "0.1"
    breach["actual_exact"] = "0.12345678"
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(preview)


@pytest.mark.parametrize("field", ["limit_exact", "actual_exact", "value_exact"])
def test_legacy_risk_exact_field_names_are_not_canonical_v1_fields(field):
    with pytest.raises(QtWorkflowError):
        canonical_qt_bytes({field: "0.1"})


def test_mixed_old_and_new_risk_fields_rejected():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    preview = deepcopy(fixture["preview_breach"])
    preview["evaluation"]["selected_risk"]["metrics"][0]["value_exact"] = "0.12"
    preview["evaluation"]["selected_risk"]["metrics"][0]["value_diagnostic"] = "0.12345678901234566"
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(preview)


def test_tampered_risk_diagnostic_rejected_by_preview_payload_digest():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    preview = deepcopy(fixture["preview_clean"])
    preview["evaluation"]["selected_risk"]["metrics"][0]["value_diagnostic"] = "0.22222222"
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(preview)


def test_required_missing_risk_diagnostic_stays_unavailable():
    fixture = json.loads((Path(__file__).parents[2] / "contracts" / "qt-workflow-v1.json").read_text(encoding="utf-8"))
    preview = deepcopy(fixture["preview_clean"])
    metric = preview["evaluation"]["selected_risk"]["metrics"][0]
    metric["value_diagnostic"] = None
    preview["payload_digest"] = qt_digest_v1({name: value for name, value in preview.items() if name != "payload_digest"})
    with pytest.raises(QtWorkflowError):
        QtPreviewResponse.from_wire(preview)


def test_position_and_cash_exact_values_still_refuse_nine_places():
    for field in ("quantity_exact", "average_price_exact", "cash_cost_exact", "total_exact"):
        with pytest.raises(QtWorkflowError):
            canonical_qt_bytes({field: "0.123456789"})

"""Actual native receipts and locked SQL support explicit subsequent QT choices."""
from copy import deepcopy
from datetime import date, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
from uuid import uuid4
import os
import subprocess

from psycopg2.extras import Json
from psycopg2 import sql
import psycopg2
import pytest

from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.domain.portfolio.qt_canonical import qt_digest_v1, qt_book_digest_v1
from algolens.infrastructure.portfolio.qt_provenance import reconcile_qt_source
from algolens.infrastructure.portfolio.qt_read_set import internal_snapshot_digest
from algolens.infrastructure.portfolio.qt_publication_proof import validate_qt_publication_chain, report_row_manifest
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from tests.integration.test_qt_a3_read_set_postgres import a3_db
from tests.integration.test_qt_preview_evaluator import preview_db, saved_draft, authority, query
from tests.integration.test_qt_connected_workflow import connected_db, prepare, observe, desk, OBSERVATION, DESK


def save_request(view, quantities):
    return {"expected_source_digest": view["source_digest"],
        "expected_provenance_digest": view["provenance_digest"],
        "expected_draft_revision": view["draft_revision"], "idempotency_key": str(uuid4()),
        "rationale": "Exercise receipt provenance for reviewed quantities.",
        "selection_rows": [{"key": row["key"], "quantity_exact": quantities[row["key"]["symbol"]]}
            for row in view["selection_rows"] if row["editable"]]}


def test_actual_receipt_consumed_head_requires_explicit_successor_cas(connected_db, monkeypatch):
    http, preview, decision = prepare(connected_db, "7", monkeypatch)
    observe(connected_db, preview, decision, "7")
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    browser, headers = http["browser"], http["headers"]
    response = browser.get('/portfolio/qt-books/BOOK/draft')
    assert response.status_code == 200, response.json
    view = response.json
    assert view["state"] == "stale" and view["draft_revision"] == 1
    assert view["selection_rows"][0]["origin"] == "verified_qt_decision"
    assert view["selection_rows"][0]["quantity_exact"] == "7"
    before = query(connected_db, 'SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type')
    audits = query(connected_db, 'SELECT count(*) FROM trading.position_overrides')
    request = save_request(view, {"SYN": "3"})
    saved = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json=request)
    assert saved.status_code == 200, saved.json
    assert saved.json["draft_revision"] == 2 and saved.json["selection_rows"][0]["quantity_exact"] == "3"
    assert saved.json["selection_rows"][0]["origin"] == "qt_draft"
    assert saved.json["selection_rows"][0]["average_price_exact"] == "101"
    assert browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json=request).json == saved.json
    stale = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers,
        json={**request, "idempotency_key": str(uuid4())})
    assert stale.status_code == 409, stale.json
    assert query(connected_db, 'SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type') == before
    assert query(connected_db, 'SELECT count(*) FROM trading.position_overrides') == audits
    next_preview = browser.post('/portfolio/qt-previews', headers=headers, json={"book_id": "BOOK",
        "draft_id": saved.json["draft_id"], "draft_revision": saved.json["draft_revision"],
        "draft_digest": saved.json["draft_digest"], "expected_source_digest": saved.json["source_digest"],
        "expected_provenance_digest": saved.json["provenance_digest"], "idempotency_key": str(uuid4())})
    assert next_preview.status_code == 200 and next_preview.json["confirmable"], next_preview.json
    next_decision = browser.post('/portfolio/qt-previews/' + next_preview.json["preview_id"] + '/confirm', headers=headers,
        json={"action": "confirm_selected_book", "expected_digest": next_preview.json["payload_digest"],
              "acknowledge_warnings": False, "idempotency_key": str(uuid4())})
    assert next_decision.status_code == 200, next_decision.json
    first_observation = deepcopy(query(connected_db, "SELECT payload FROM trading.qt_execution_observations")[0][0])
    now = query(connected_db, "SELECT clock_timestamp()")[0][0]
    first_observation["decision_id"] = next_decision.json["decision_id"]
    first_observation["fills"][0].update(selected_quantity_exact="3", execution_id="synthetic-second-choice",
        last_update=now.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'))
    next_observation, next_attempt = str(uuid4()), str(uuid4())
    query(connected_db, """INSERT INTO trading.qt_execution_observations
        (observation_id,decision_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        VALUES(%s,%s,'synthetic-connected-execution','connected-execution-v1','second-choice-v2',%s,%s,%s,%s)""",
        (next_observation, next_decision.json["decision_id"], now, now+timedelta(minutes=5),
         sha256(canonical_qt_input_bytes(first_observation)).hexdigest(), Json(first_observation)))
    second = subprocess.run([str(DESK), next_decision.json["decision_id"], next_attempt, next_observation],
        capture_output=True, text=True, timeout=30, env=os.environ.copy())
    assert second.returncode == 0, second.stdout + second.stderr
    assert query(connected_db, "SELECT quantity FROM trading.positions WHERE portfolio_type='qt'") == [(Decimal(3),)]
    latest = browser.get('/portfolio/qt-books/BOOK/draft')
    assert latest.status_code == 200 and latest.json["state"] == "stale", latest.json
    assert latest.json["selection_rows"][0]["quantity_exact"] == "3"
    assert latest.json["selection_rows"][0]["origin"] == "verified_qt_decision"
    assert query(connected_db, 'SELECT count(*) FROM trading.qt_desk_receipts') == [(2,)]


@pytest.mark.parametrize("change", ["pnl", "time", "audit"])
def test_actual_receipt_current_accounting_and_audit_inventory_are_mandatory(connected_db, monkeypatch, change):
    http, preview, decision = prepare(connected_db, "7", monkeypatch)
    observe(connected_db, preview, decision, "7")
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    if change == "pnl":
        query(connected_db, "UPDATE trading.positions SET daily_realized_pnl=9 WHERE portfolio_type='qt'")
    elif change == "time":
        query(connected_db, "UPDATE trading.positions SET last_update=last_update+interval '1 second' WHERE portfolio_type='qt'")
    else:
        query(connected_db, "UPDATE trading.position_overrides SET risk_check_result=risk_check_result || '{\"preview_payload_digest\":\"bad\"}'::jsonb")
    response = http["browser"].get('/portfolio/qt-books/BOOK/draft')
    assert response.status_code == 200, response.json
    assert response.json["state"] == "provenance_unresolved"
    refused = http["browser"].put('/portfolio/qt-books/BOOK/draft', headers=http["headers"],
        json=save_request(response.json, {"SYN": "3"}))
    assert refused.status_code == 409, refused.json
    assert query(connected_db, 'SELECT count(*) FROM trading.qt_drafts') == [(1,)]


def new_key_decision(dsn):
    service, _ = saved_draft(dsn)
    current = service.get_draft("BOOK", 101).to_wire()
    query(dsn, "INSERT INTO metadata.contract_metadata VALUES('NEW','NEW','EQUITY')")
    request = save_request(current, {"SYN": "2"})
    request["selection_rows"].append({"key": {**current["selection_rows"][0]["key"], "symbol": "NEW"}, "quantity_exact": "3"})
    selected = service.save_draft("BOOK", 101, request).to_wire()
    authority(dsn, selection=selected["selection_rows"])
    preview = service.create_preview(101, {"book_id": "BOOK", "draft_id": selected["draft_id"],
        "draft_revision": selected["draft_revision"], "draft_digest": selected["draft_digest"],
        "expected_source_digest": selected["source_digest"], "expected_provenance_digest": selected["provenance_digest"],
        "idempotency_key": str(uuid4())}).to_wire()
    assert preview["confirmable"], preview
    decision = service.confirm_preview(preview["preview_id"], 101, {"action": "confirm_selected_book",
        "expected_digest": preview["payload_digest"], "acknowledge_warnings": False, "idempotency_key": str(uuid4())}).to_wire()
    now = query(dsn, "SELECT clock_timestamp()")[0][0]
    fills = [{"key": {**row["key"], "portfolio_type": "qt"}, "observation_kind": "executed",
        "selected_quantity_exact": row["quantity_exact"], "average_price_exact": "101", "actual_cash_cost_exact": "0.02",
        "currency": "USD", "execution_id": "synthetic-receipt-" + row["key"]["symbol"],
        "accounting_source_id": "synthetic-receipt-accounting", "daily_unrealized_pnl_exact": "3",
        "daily_realized_pnl_exact": "-1", "last_update": now.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')}
        for row in preview["selection_rows"]]
    payload = {"schema_version": "qt-execution/v1", "decision_id": decision["decision_id"], "book_id": "BOOK",
        "source_day": preview["source_day"], "fills": fills, "results": {"position_count": 2, "currency_totals": [{
            "currency": "USD", "actual_cash_cost_exact": "0.04", "daily_unrealized_pnl_exact": "6", "daily_realized_pnl_exact": "-2"}]}}
    query(dsn, """INSERT INTO trading.qt_source_policies(book_id,purpose,enabled,version,producer_id,policy_version,allowed_override_codes)
        VALUES('BOOK','execution',true,1,'synthetic-connected-execution','connected-execution-v1','[]')""")
    query(dsn, """INSERT INTO trading.qt_execution_observations
        (observation_id,decision_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        VALUES(%s,%s,'synthetic-connected-execution','connected-execution-v1','receipt-observation-v1',%s,%s,%s,%s)""",
        (OBSERVATION, decision["decision_id"], now, now+timedelta(minutes=5), sha256(canonical_qt_input_bytes(payload)).hexdigest(), Json(payload)))
    return service, preview, decision


def test_actual_new_key_null_before_receipt_and_complete_second_choice(connected_db):
    service, preview, decision = new_key_decision(connected_db)
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    assert query(connected_db, "SELECT before_state FROM trading.position_overrides WHERE symbol='NEW'") == [(None,)]
    view = service.get_draft("BOOK", 101).to_wire()
    assert view["state"] == "stale" and view["draft_revision"] == 2
    assert {row["key"]["symbol"] for row in view["selection_rows"] if row["editable"]} == {"NEW", "SYN"}
    assert all(row["origin"] == "verified_qt_decision" for row in view["selection_rows"])
    saved = service.save_draft("BOOK", 101, save_request(view, {"SYN": "4", "NEW": "2"})).to_wire()
    assert saved["draft_revision"] == 3
    assert query(connected_db, "SELECT symbol,quantity FROM trading.positions WHERE portfolio_type='qt' ORDER BY symbol") == [("NEW", Decimal(3)), ("SYN", Decimal(2))]
    assert query(connected_db, 'SELECT count(*) FROM trading.position_overrides') == [(2,)]


def insert_historical_publication(dsn, source):
    """Store a fully linked, hashed prior-day synthetic history, never a bare audit claim.

    Financial/accounting evidence is copied from the actual native publication;
    only explicit historical identities/scope/timestamps and their hashes change.
    The old observation is expired now, as durable historical proof permits.
    """
    current_day = source["source_day"]
    prior_day = current_day - timedelta(days=1)
    current = source["processed_publications"][0]
    current["audits"] = source["audits"]
    original_draft = query(dsn, "SELECT to_jsonb(d) FROM trading.qt_drafts d WHERE draft_id=%s",
                           (current["decision"]["draft_id"],))[0][0]
    original_seed = query(dsn, "SELECT to_jsonb(s) FROM trading.qt_model_seed_publications s WHERE publication_id=%s",
                          (current["decision"]["model_publication_id"],))[0][0]
    identities = {current["decision"][name]: str(uuid4())
                  for name in ("decision_id", "preview_id", "draft_id", "model_publication_id")}
    identities.update({current["receipt"]["attempt_id"]: str(uuid4()),
                       current["observation"]["observation_id"]: str(uuid4())})
    def historical(value):
        if isinstance(value, dict): return {name: historical(item) for name, item in value.items()}
        if isinstance(value, list): return [historical(item) for item in value]
        if isinstance(value, str):
            if value in identities: return identities[value]
            if value[:10] == current_day.isoformat(): return prior_day.isoformat() + value[10:]
        return value
    old, draft, seed = (historical(item) for item in (current, original_draft, original_seed))
    seed["source_day"] = prior_day  # SQL date type expected by the source reader.
    original, preview, decision = old["preview"]["read_set_payload"], old["preview"], old["decision"]
    seed["seed_digest"] = qt_digest_v1({"seed_rows": seed["system_components"]})
    seed["proposal_manifest_digest"] = internal_snapshot_digest("qt-proposal-manifest/v1", {"proposal_rows": seed["proposal_components"]})
    provenance = reconcile_qt_source("BOOK", prior_day, [seed], original["source_rows"], [],
        observed_system_rows=original["system_rows"], observed_saved_rows=original["saved_rows"],
        observed_saved_accounting=original["saved_accounting"])
    assert provenance.status == "ready", provenance.reason
    original["provenance"] = {"status": "ready", "source_digest": provenance.observed_source_digest,
        "chain_digest": provenance.legacy_audit_chain_digest, "seed_digest": provenance.seed_digest}
    original["publication_refs"][0].update(seed_digest=seed["seed_digest"], proposal_manifest_digest=seed["proposal_manifest_digest"])
    draft.update(source_digest=provenance.observed_source_digest, provenance_digest=provenance.legacy_audit_chain_digest,
        seed_digest=provenance.seed_digest, draft_digest=qt_digest_v1(draft["selection_payload"]))
    original["draft"]["digest"] = draft["draft_digest"]
    selected = qt_book_digest_v1([{ "key": {**row["key"], "portfolio_type": "qt"}, "quantity_exact": row["quantity_exact"]}
        for row in preview["payload"]["selection_rows"]], source_portfolio_type="qt")
    diagnostic = qt_book_digest_v1([{ "key": {**row["key"], "portfolio_type": "qt"}, "quantity_exact": row["quantity_exact"]}
        for row in original["source_rows"]], source_portfolio_type="qt")
    read_digest = internal_snapshot_digest("qt-read-set/v1", original)
    preview.update(draft_digest=draft["draft_digest"], source_digest=draft["source_digest"], provenance_digest=draft["provenance_digest"],
        read_set_digest=read_digest, selected_book_digest=selected, optimizer_book_digest=diagnostic)
    preview["payload"].update(source_digest=draft["source_digest"], provenance_digest=draft["provenance_digest"],
        read_set_digest=read_digest, selected_book_digest=selected, optimizer_book_digest=diagnostic)
    for name in ("selected_risk", "selected_costs"): preview["payload"]["evaluation"][name]["evaluated_book_digest"] = selected
    preview["payload"]["payload_digest"] = qt_digest_v1({name: value for name, value in preview["payload"].items() if name != "payload_digest"})
    preview["payload_digest"] = preview["payload"]["payload_digest"]
    decision.update(provenance_digest=draft["provenance_digest"], selected_book_digest=selected, read_set_digest=read_digest)
    decision["payload"].update(preview_payload_digest=preview["payload_digest"], selected_book_digest=selected, read_set_digest=read_digest)
    observation, result, receipt = (old[name] for name in ("observation", "result", "receipt"))
    observation["content_digest"] = sha256(canonical_qt_input_bytes(observation["payload"])).hexdigest()
    result["payload"]["selected_book_digest"] = selected
    result["content_digest"] = sha256(canonical_qt_input_bytes(result["payload"])).hexdigest()
    publication = receipt["publication_payload"]
    publication.update(preview_payload_digest=preview["payload_digest"], read_set_digest=read_digest,
        selected_book_digest=selected, published_book_digest=selected,
        observation_digest=observation["content_digest"], results_digest=result["content_digest"])
    receipt.update(published_book_digest=selected, row_manifest_digest=report_row_manifest(
        publication["before_accounting"], publication["after_accounting"], preview["payload"]["selection_rows"]))
    for audit in old["audits"]:
        audit["id"] += 10000
        audit["risk_check_result"].update(preview_payload_digest=preview["payload_digest"], read_set_digest=read_digest,
            selected_book_digest=selected, published_book_digest=selected, observation_digest=observation["content_digest"])
    validate_qt_publication_chain(old)
    def insert(cursor, table, record):
        # Actual storage rows with fixed table names; values remain SQL parameters.
        cursor.execute(sql.SQL("INSERT INTO trading.{} ({}) VALUES ({})").format(sql.Identifier(table),
            sql.SQL(',').join(sql.Identifier(name) for name in record),
            sql.SQL(',').join(sql.Placeholder() for _ in record)),
            tuple(Json(value) if isinstance(value, (dict, list)) else value for value in record.values()))
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended('algolens:qt-book:BOOK',0))")
            for table, record in [("qt_model_seed_publications", seed), ("qt_drafts", draft), ("qt_previews", preview),
                ("qt_decisions", decision), ("qt_execution_observations", observation), ("qt_desk_results", result),
                ("qt_desk_receipts", receipt)]: insert(cursor, table, record)
            for audit in old["audits"]:
                insert(cursor, "position_overrides", {name: value for name, value in audit.items() if name != "legacy_scope_book"})
    return prior_day


def test_actual_linked_prior_day_desk_history_does_not_block_current_successor(connected_db, monkeypatch):
    http, preview, decision = prepare(connected_db, "7", monkeypatch)
    observe(connected_db, preview, decision, "7")
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    repository = QtWorkflowRepository(lambda: psycopg2.connect(connected_db))
    def source():
        with repository.transaction("BOOK", 101) as tx:
            tx.lock_authorities([101]); tx.lock_registries(["ui-one"]); tx.lock_books(["BOOK"])
            tx.lock_mutable(source_day=date.fromisoformat(preview["source_day"]))
            return tx.read_source_evidence()
    prior_day = insert_historical_publication(connected_db, source())
    # Prove the historical SQL chain itself rather than trusting a desk marker.
    with repository.transaction("BOOK", 101) as tx:
        tx.lock_authorities([101]); tx.lock_registries(["ui-one"]); tx.lock_books(["BOOK"]); tx.lock_mutable()
        old = tx.read_processed_publications(prior_day)[0]
    old["audits"] = [audit for audit in source()["audits"] if audit["risk_check_result"]["decision_id"] == old["decision"]["decision_id"]]
    validate_qt_publication_chain(old)
    # The old implementation was an external, unversioned repair archive that
    # is unavailable in a clean checkout; no historical RED is claimed here.
    # Exercise current prior-day isolation and successor CAS on the proven SQL
    # chain, without inventing archived source or skipping the live regression.
    view = http["browser"].get('/portfolio/qt-books/BOOK/draft')
    assert view.status_code == 200 and view.json["state"] == "stale", view.json
    assert view.json["selection_rows"][0]["origin"] == "verified_qt_decision"
    saved = http["browser"].put('/portfolio/qt-books/BOOK/draft', headers=http["headers"],
        json=save_request(view.json, {"SYN": "3"}))
    assert saved.status_code == 200 and saved.json["draft_revision"] == 2, saved.json
    assert query(connected_db, "SELECT quantity FROM trading.positions WHERE portfolio_type='qt'") == [(Decimal(7),)]

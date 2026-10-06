"""F3 connected proof (PLAN14 report rows from saved positions): a position the
desk OPENS -- a key with no earlier position row at all -- must not hold the
report back. Each test drives the real chain: HTTP draft -> preview -> confirm
-> native desk processing -> API readiness (`report_ready`) -> native report
probe, then checks the saved row, the receipt's eligibility, the row manifest
digest against an independently built expectation, and the rendered rows
(PLAN13's assert_positions_rows_match_saved: HTML uses the saved average
price, CSV the market price 102).

Three shapes:
- a brand-new SYMBOL under the existing strategy name (IMM, next to SYN);
- a brand-new STRATEGY NAME (TWO/SYN, next to ONE/SYN) with no 'qt' row -- the
  shape of vectors v2's open_from_absent_new_strategy_name, and of independent
  review finding 1 (report_scope from before UNION after);
- a book with NO 'qt' rows at all -- vectors v2's open_into_empty_before_book.

PLAN15 rewrite (build14 failures, all in the fixtures):
- The native report probe (qt_processed_report_probe.cpp) registers ONLY the
  instruments SYN, IMM and FUT and prices only those; any other symbol cannot
  be rendered. The new symbol is therefore IMM (an equity the probe knows),
  and the new strategy name TWO trades SYN, as test_qt_connected_multiowner
  does.
- The preview needs a governed catalog that covers the whole selection:
  `authority(dsn, selection=draft["selection_rows"])`. Without `selection` it
  writes a catalog with only ONE/SYN and `_validate_catalog` raises
  preview_unavailable (the build14 failure for the new-symbol test).
- A second strategy_name needs a v2 model-seed publication that carries EVERY
  current system row (qt_provenance: `current_system != seed` ->
  current_system_mismatch), i.e. ONE/SYN and TWO/SYN, plus a governed
  evaluation snapshot bound to that publication, exactly like
  test_qt_connected_multiowner's multiowner_db / prepare_multiowner.

Imports come only from the installed `tests` package and `algolens`.

Written per this task's PostgreSQL-integration-lane convention; the
integration lane runs it against an owned database with the native probes.
"""
from copy import deepcopy
from decimal import Decimal
from hashlib import sha256
import json
import os
import subprocess
from datetime import timedelta, timezone

from psycopg2.extras import Json
import pytest

from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.domain.portfolio.qt_workflow_models import QtKey
from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_read_set import internal_snapshot_digest
from tests.integration.test_qt_preview_evaluator import preview_db, authority, query
from tests.integration.test_qt_a3_read_set_postgres import a3_db, PUBLICATION, REVISION
from tests.qt_native_evaluator import native_evaluator_configuration
from tests.integration.test_qt_a8_http_postgres import http_harness
from tests.integration.test_qt_connected_workflow import (
    connected_db, desk, report, assert_positions_rows_match_saved, OBSERVATION, REPORT, DELIVERY_GUARD,
)
import psycopg2
from tests.qt_report_probe import report_probe_environment


NEW_NAME_PUBLICATION = "10000000-0000-4000-8000-000000000091"
NEW_NAME_REVISION = "30000000-0000-4000-8000-000000000091"
KEY_FIELDS = ("portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")


def report_with_names(preview, directory, *strategy_names):
    """Like test_qt_connected_workflow.report(), but names every strategy
    the probe must report on -- report() itself hardcodes only 'ONE', which
    is wrong once a second strategy_name ('TWO') is in scope (mirrors
    test_qt_connected_multiowner.py's report_multiowner())."""
    directory.mkdir()
    assert DELIVERY_GUARD.is_file(), 'Build the test-only delivery guard first'
    report_environment = report_probe_environment(DELIVERY_GUARD)
    return subprocess.run([str(REPORT), "BOOK", preview["source_day"], "engine-one", str(directory), *strategy_names],
        capture_output=True, text=True, timeout=30, env=report_environment)


def governed_inputs_for(dsn, draft, *, publication_id=None):
    """The governed evaluation authority for exactly this draft's selection
    (catalog, valuations, closes, quantity rules and cost inputs for every
    row). When a later model-seed publication is the current one, also bind
    a copy of the newest snapshot to it, as prepare_multiowner does."""
    authority(dsn, case='clean', selection=draft["selection_rows"])
    if publication_id is None:
        return
    payload = deepcopy(query(dsn, "SELECT payload FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1")[0][0])
    payload["model_publication_id"] = publication_id
    query(dsn, """INSERT INTO trading.qt_evaluation_snapshots
        (book_id,source_day,model_publication_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        SELECT book_id,source_day,%s,producer_id,policy_version,'connected-new-strategy-name-v2',
          as_of,valid_until,%s,%s FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1""",
        (publication_id, sha256(canonical_qt_input_bytes(payload)).hexdigest(), Json(payload)))


def confirmed_decision(browser, headers, dsn, draft, *, publication_id=None, key_seed):
    """Preview and confirm a saved draft over HTTP; returns (preview, decision)."""
    governed_inputs_for(dsn, draft, publication_id=publication_id)
    preview_response = browser.post('/portfolio/qt-previews', headers=headers, json={"book_id": "BOOK",
        "draft_id": draft["draft_id"], "draft_revision": draft["draft_revision"], "draft_digest": draft["draft_digest"],
        "expected_source_digest": draft["source_digest"], "expected_provenance_digest": draft["provenance_digest"],
        "idempotency_key": "00000000-0000-4000-8000-0000000000%02d" % key_seed})
    assert preview_response.status_code == 200, preview_response.json
    preview = preview_response.json
    assert preview["confirmable"], (preview["unavailable_reasons"], preview["evaluation"]["selected_risk"])
    decision_response = browser.post('/portfolio/qt-previews/' + preview['preview_id'] + '/confirm', headers=headers, json={
        "action": "confirm_selected_book", "expected_digest": preview["payload_digest"],
        "idempotency_key": "00000000-0000-4000-8000-0000000000%02d" % (key_seed + 1), "acknowledge_warnings": False})
    assert decision_response.status_code == 200, decision_response.json
    decision = decision_response.json
    assert not decision["report_ready"] and decision["receipt"] is None
    return preview, decision


def observe_editable_rows(dsn, preview, decision):
    """One executed fill for every editable selection row (the desk needs a
    fill per selected key, including a key that had no earlier row)."""
    now = query(dsn, "SELECT clock_timestamp()")[0][0]
    fills = []
    totals = [Decimal(0), Decimal(0), Decimal(0)]
    for row in preview["selection_rows"]:
        if not row["editable"]:
            continue
        tag = row["key"]["strategy_name"] + "-" + row["key"]["symbol"]
        fills.append({"key": {**row["key"], "portfolio_type": "qt"}, "observation_kind": "executed",
            "selected_quantity_exact": row["quantity_exact"], "average_price_exact": "101",
            "actual_cash_cost_exact": "0.02", "currency": "USD",
            "execution_id": "synthetic-connected-fill-" + tag,
            "accounting_source_id": "synthetic-connected-accounting-" + tag,
            "daily_unrealized_pnl_exact": "3", "daily_realized_pnl_exact": "-1",
            "last_update": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")})
        totals[0] += Decimal("0.02"); totals[1] += Decimal("3"); totals[2] += Decimal("-1")
    payload = {"schema_version": "qt-execution/v1", "decision_id": decision["decision_id"], "book_id": "BOOK",
        "source_day": preview["source_day"], "fills": fills, "results": {"position_count": len(fills),
        "currency_totals": [{"currency": "USD", "actual_cash_cost_exact": str(totals[0]),
            "daily_unrealized_pnl_exact": str(totals[1]), "daily_realized_pnl_exact": str(totals[2])}]}}
    query(dsn, """INSERT INTO trading.qt_source_policies(book_id,purpose,enabled,version,producer_id,policy_version,allowed_override_codes)
        VALUES('BOOK','execution',true,1,'synthetic-connected-execution','connected-execution-v1','[]')""")
    query(dsn, """INSERT INTO trading.qt_execution_observations
        (observation_id,decision_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        VALUES(%s,%s,'synthetic-connected-execution','connected-execution-v1','connected-observation-v1',%s,%s,%s,%s)""",
        (OBSERVATION, decision["decision_id"], now, now + timedelta(minutes=5),
         sha256(canonical_qt_input_bytes(payload)).hexdigest(), Json(payload)))


def assert_receipt_matches_plan14(dsn, browser, decision, day, *, shown, before_keys, names):
    """The processed receipt is eligible, its row manifest is the digest of
    exactly the shown keys (built independently here from QtKey, sorted as the
    manifest sorts them), its scope is before UNION after, and the API's own
    readiness gate agrees (report_ready)."""
    keys = sorted(QtKey("BOOK", "engine-one", name, day, symbol, "qt") for name, symbol in shown)
    expected = qt_digest_v1({"component_keys": [key.to_wire() for key in keys]})
    payload, status, digest = query(dsn,
        "SELECT publication_payload, report_eligibility_status, row_manifest_digest "
        "FROM trading.qt_desk_receipts WHERE decision_id = %s", (decision["decision_id"],))[0]
    assert status == "eligible" and digest == expected
    assert payload["report_scope"] == {"portfolio_id": "BOOK", "strategy_id": "engine-one",
        "strategy_names": sorted(names), "portfolio_type": "qt", "date": day}
    assert sorted((row["key"]["strategy_name"], row["key"]["symbol"]) for row in payload["before_accounting"]) == sorted(before_keys)
    assert sorted((row["key"]["strategy_name"], row["key"]["symbol"]) for row in payload["after_accounting"]) == sorted(shown)
    ready = browser.get('/portfolio/qt-decisions/' + decision['decision_id'])
    assert ready.status_code == 200 and ready.json['report_ready'] is True, ready.json
    assert ready.json['receipt']['report_eligibility']['status'] == 'eligible'
    assert ready.json['receipt']['report_eligibility']['row_manifest_digest'] == expected


# --- a brand-new symbol under the existing strategy name --------------------

def prepare_with_a_genuinely_new_symbol(dsn, monkeypatch):
    """Like test_qt_connected_workflow.prepare(), but the submitted draft
    adds a second, brand-new (strategy_name, symbol) key -- ONE/IMM -- that
    has never had a 'system', 'qt_proposal' or 'qt' row on ANY day, next to
    the existing editable ONE/SYN row. IMM is registered in the catalog as an
    equity (as test_qt_connected_multiowner does) and is one of the three
    instruments the native report probe can render."""
    query(dsn, "INSERT INTO metadata.contract_metadata VALUES ('IMM', 'IMM', 'EQUITY')")
    config = native_evaluator_configuration()
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(dsn)),
        evaluator_bundle_directory=config["bundle_directory"])
    _, clients, _ = http_harness(dsn, service, monkeypatch)
    browser, headers = clients(101)
    initial_response = browser.get('/portfolio/qt-books/BOOK/draft')
    assert initial_response.status_code == 200, initial_response.json
    initial = initial_response.json
    row = next(row for row in initial["selection_rows"] if row["editable"])
    assert row["quantity_exact"] == "4" and row["origin"] == "verified_model_seed"
    new_key = {**row["key"], "symbol": "IMM"}
    draft_response = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json={
        "expected_source_digest": initial["source_digest"], "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0, "idempotency_key": "00000000-0000-4000-8000-000000000061",
        "rationale": "Exercise a new symbol with immutable holdings.",
        "selection_rows": [{"key": row["key"], "quantity_exact": "7"},
                            {"key": new_key, "quantity_exact": "3"}]})
    assert draft_response.status_code == 200, draft_response.json
    draft = draft_response.json
    assert {item["key"]["symbol"]: item["quantity_exact"] for item in draft["selection_rows"]
            if item["editable"]} == {"SYN": "7", "IMM": "3"}
    preview, decision = confirmed_decision(browser, headers, dsn, draft, key_seed=62)
    assert query(dsn, "SELECT count(*) FROM trading.positions WHERE symbol = 'IMM'") == [(0,)]
    return {'browser': browser, 'headers': headers, 'clients': clients}, preview, decision


def test_actual_brand_new_symbol_with_no_prior_row_does_not_hold_the_report_back(connected_db, tmp_path, monkeypatch):
    http, preview, decision = prepare_with_a_genuinely_new_symbol(connected_db, monkeypatch)
    observe_editable_rows(connected_db, preview, decision)
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    # The saved row now exists -- this is the F3 regression itself: before
    # PLAN14, this key having no 'before' row at all refused the report even
    # though it processed and saved correctly.
    saved = query(connected_db, "SELECT quantity FROM trading.positions WHERE symbol = 'IMM' AND portfolio_type = 'qt'")
    assert saved == [(Decimal("3"),)]
    assert_receipt_matches_plan14(connected_db, http['browser'], decision, preview["source_day"],
        shown=[("ONE", "SYN"), ("ONE", "IMM")], before_keys=[("ONE", "SYN")], names=["ONE"])
    rendered = report(preview, tmp_path / "qt-report-new-symbol")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    output = json.loads(rendered.stdout)
    assert output['delivery_guard_loaded'] is True and output['delivery_calls'] == 0
    assert output["quantities"] == {"ONE": {"SYN": "7", "IMM": "3"}}
    assert_positions_rows_match_saved(output["report_html"], output["report_csv"],
        output["baseline_html"], output["baseline_csv"],
        [("One", "SYN", "7", "101", "1", "102"), ("One", "IMM", "3", "101", "1", "102")])


# --- a brand-new strategy name with no 'qt' row -----------------------------

@pytest.fixture
def connected_db_with_a_second_known_but_never_qt_strategy_name(connected_db):
    """Like test_qt_connected_multiowner.py's multiowner_db, but the second
    strategy_name ('TWO', trading SYN) has NEVER had a 'qt' (before) row --
    only 'system' and 'qt_proposal' seed rows. A later (v2) model-seed
    publication carries EVERY current system row (ONE/SYN preserved, TWO/SYN
    inserted): qt_provenance requires the latest publication's seed to equal
    the current physical system rows, so a v2 that named only TWO would be a
    current_system_mismatch and empty the draft. This is the realistic
    production shape behind vectors v2's open_from_absent_new_strategy_name: a
    strategy the book already knows (seeded, previewable, confirmable) opening
    its first-ever QT position.
    """
    dsn = connected_db
    day = query(dsn, "SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")[0][0].isoformat()
    query(dsn, """
        INSERT INTO trading.positions
          (portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type,quantity,average_price,
           qt_proposal_revision,daily_unrealized_pnl,daily_realized_pnl,last_update)
        VALUES ('BOOK','engine-one','TWO',%s,'SYN','system',3,100,NULL,NULL,NULL,NULL),
               ('BOOK','engine-one','TWO',%s,'SYN','qt_proposal',3,100,%s,NULL,NULL,NULL);
    """, (day, day, NEW_NAME_REVISION))
    seed, manifest = [], []
    for owner, quantity, revision, origin, action in (
        ("ONE", "4", REVISION, PUBLICATION, "preserved"),
        ("TWO", "3", NEW_NAME_REVISION, NEW_NAME_PUBLICATION, "inserted"),
    ):
        key = dict(zip(KEY_FIELDS, ("BOOK", "engine-one", owner, day, "SYN", "system")))
        seed.append({"key": key, "quantity_exact": quantity, "average_price_exact": "100"})
        manifest.append({"key": {**key, "portfolio_type": "qt_proposal"}, "quantity_exact": quantity,
                         "average_price_exact": "100", "action": action, "position_revision": revision,
                         "origin_publication_id": origin})
    query(dsn, """INSERT INTO trading.qt_model_seed_publications
        (publication_id,portfolio_id,strategy_id,source_day,publication_version,system_components,
         seed_digest,producer_version,proposal_components,proposal_manifest_digest)
        VALUES(%s,'BOOK','engine-one',%s,2,%s,%s,'synthetic-new-strategy-name',%s,%s)""",
        (NEW_NAME_PUBLICATION, day, Json(seed), qt_digest_v1({"seed_rows": seed}), Json(manifest),
         internal_snapshot_digest("qt-proposal-manifest/v1", {"proposal_rows": manifest})))
    return dsn


def prepare_with_a_new_strategy_name(dsn, monkeypatch):
    config = native_evaluator_configuration()
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(dsn)),
        evaluator_bundle_directory=config["bundle_directory"])
    _, clients, _ = http_harness(dsn, service, monkeypatch)
    browser, headers = clients(101)
    initial_response = browser.get('/portfolio/qt-books/BOOK/draft')
    assert initial_response.status_code == 200, initial_response.json
    initial = initial_response.json
    editable = {row["key"]["strategy_name"]: row["quantity_exact"] for row in initial["selection_rows"] if row["editable"]}
    assert editable == {"ONE": "4", "TWO": "3"}, initial
    draft_response = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json={
        "expected_source_digest": initial["source_digest"], "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0, "idempotency_key": "00000000-0000-4000-8000-000000000071",
        "rationale": "Exercise independent multi-owner symbols.",
        "selection_rows": [{"key": row["key"], "quantity_exact": row["quantity_exact"]}
                            for row in initial["selection_rows"] if row["editable"]]})
    assert draft_response.status_code == 200, draft_response.json
    draft = draft_response.json
    preview, decision = confirmed_decision(browser, headers, dsn, draft,
        publication_id=NEW_NAME_PUBLICATION, key_seed=72)
    assert query(dsn, "SELECT count(*) FROM trading.positions WHERE strategy_name = 'TWO' AND portfolio_type = 'qt'") == [(0,)]
    return {'browser': browser, 'headers': headers, 'clients': clients}, preview, decision


def test_actual_new_strategy_name_with_no_prior_qt_row_does_not_hold_the_report_back(
        connected_db_with_a_second_known_but_never_qt_strategy_name, tmp_path, monkeypatch):
    dsn = connected_db_with_a_second_known_but_never_qt_strategy_name
    http, preview, decision = prepare_with_a_new_strategy_name(dsn, monkeypatch)
    observe_editable_rows(dsn, preview, decision)
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    saved = query(dsn, "SELECT quantity FROM trading.positions WHERE strategy_name = 'TWO' AND symbol = 'SYN' AND portfolio_type = 'qt'")
    assert saved == [(Decimal("3"),)]
    # Independent review finding 1: report_scope must include the NEW
    # strategy_name 'TWO', not only 'ONE' (all that `before` had).
    assert_receipt_matches_plan14(dsn, http['browser'], decision, preview["source_day"],
        shown=[("ONE", "SYN"), ("TWO", "SYN")], before_keys=[("ONE", "SYN")], names=["ONE", "TWO"])
    rendered = report_with_names(preview, tmp_path / "qt-report-new-strategy-name", "ONE", "TWO")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    output = json.loads(rendered.stdout)
    assert output['delivery_guard_loaded'] is True and output['delivery_calls'] == 0
    assert output["quantities"] == {"ONE": {"SYN": "4"}, "TWO": {"SYN": "3"}}
    assert_positions_rows_match_saved(output["report_html"], output["report_csv"],
        output["baseline_html"], output["baseline_csv"],
        [("One", "SYN", "4", "101", "1", "102"), ("Two", "SYN", "3", "101", "1", "102")])


# --- a book with no 'qt' rows at all ----------------------------------------

@pytest.fixture
def connected_db_with_no_qt_rows_at_all(connected_db):
    """Deletes the book's only 'qt' (before) row entirely, matching vectors
    v2's open_into_empty_before_book: a book that has never saved a QT
    position at all opens its first one. Distinct from the explicit-zero
    'qt' row a3_db normally seeds -- this is genuine absence."""
    query(connected_db, "DELETE FROM trading.positions WHERE portfolio_type = 'qt'")
    return connected_db


def prepare_into_an_empty_before_book(dsn, monkeypatch):
    config = native_evaluator_configuration()
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(dsn)),
        evaluator_bundle_directory=config["bundle_directory"])
    _, clients, _ = http_harness(dsn, service, monkeypatch)
    browser, headers = clients(101)
    initial_response = browser.get('/portfolio/qt-books/BOOK/draft')
    assert initial_response.status_code == 200, initial_response.json
    initial = initial_response.json
    row = next(row for row in initial["selection_rows"] if row["editable"])
    assert query(dsn, "SELECT count(*) FROM trading.positions WHERE portfolio_type = 'qt'") == [(0,)]
    draft_response = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json={
        "expected_source_digest": initial["source_digest"], "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0, "idempotency_key": "00000000-0000-4000-8000-000000000081",
        "rationale": "Exercise a selected symbol without prior QT rows.",
        "selection_rows": [{"key": row["key"], "quantity_exact": "6"}]})
    assert draft_response.status_code == 200, draft_response.json
    draft = draft_response.json
    # Unchanged from the build14-green version of this test: a single
    # ONE/SYN row, so the default governed authority (catalog with only
    # ONE/SYN) already covers the whole selection.
    authority(dsn, case='clean')
    preview_response = browser.post('/portfolio/qt-previews', headers=headers, json={"book_id": "BOOK",
        "draft_id": draft["draft_id"], "draft_revision": draft["draft_revision"], "draft_digest": draft["draft_digest"],
        "expected_source_digest": draft["source_digest"], "expected_provenance_digest": draft["provenance_digest"],
        "idempotency_key": "00000000-0000-4000-8000-000000000082"})
    assert preview_response.status_code == 200, preview_response.json
    preview = preview_response.json
    assert preview["confirmable"] and preview["selection_rows"][0]["quantity_exact"] == "6"
    decision_response = browser.post('/portfolio/qt-previews/' + preview['preview_id'] + '/confirm', headers=headers, json={
        "action": "confirm_selected_book", "expected_digest": preview["payload_digest"],
        "idempotency_key": "00000000-0000-4000-8000-000000000083", "acknowledge_warnings": False})
    assert decision_response.status_code == 200, decision_response.json
    decision = decision_response.json
    assert not decision["report_ready"] and decision["receipt"] is None
    assert query(dsn, "SELECT count(*) FROM trading.positions WHERE portfolio_type='qt'") == [(0,)]
    return {'browser': browser, 'headers': headers, 'clients': clients}, preview, decision


def test_actual_open_into_a_book_with_no_qt_rows_at_all_does_not_hold_the_report_back(
        connected_db_with_no_qt_rows_at_all, tmp_path, monkeypatch):
    dsn = connected_db_with_no_qt_rows_at_all
    http, preview, decision = prepare_into_an_empty_before_book(dsn, monkeypatch)
    observe_editable_rows(dsn, preview, decision)
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    saved = query(dsn, "SELECT quantity FROM trading.positions WHERE portfolio_type = 'qt'")
    assert saved == [(Decimal("6"),)]
    assert_receipt_matches_plan14(dsn, http['browser'], decision, preview["source_day"],
        shown=[("ONE", "SYN")], before_keys=[], names=["ONE"])
    rendered = report(preview, tmp_path / "qt-report-empty-before-book")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    output = json.loads(rendered.stdout)
    assert output['delivery_guard_loaded'] is True and output['delivery_calls'] == 0
    assert output["quantities"] == {"ONE": {"SYN": "6"}}

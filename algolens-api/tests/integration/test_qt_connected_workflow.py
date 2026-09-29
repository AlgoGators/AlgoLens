"""Actual cookie/CSRF HTTP -> owned SQL -> bundled evaluator -> desk -> report."""
from copy import deepcopy
import csv
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import subprocess

from psycopg2.extras import Json
import pytest

from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from tests.integration.test_qt_preview_evaluator import preview_db, authority, query
from tests.integration.test_qt_a3_read_set_postgres import a3_db
from tests.qt_native_evaluator import native_evaluator_configuration
from tests.integration.test_qt_a8_http_postgres import http_harness, seed_http_approvers
from uuid import uuid4
import psycopg2

NATIVE_BUILD = Path('/home/devcontainers/qt-validation-20260921/bin/Debug')
DESK = NATIVE_BUILD / 'qt_desk_storage_probe'
REPORT = NATIVE_BUILD / 'qt_processed_report_probe'
DELIVERY_GUARD = NATIVE_BUILD / 'libqt_no_delivery_guard.so'
OBSERVATION = "60000000-0000-4000-8000-000000000051"
ATTEMPT = "50000000-0000-4000-8000-000000000051"


@pytest.fixture
def connected_db(preview_db):
    # These are extensions to the owned minimal A3 schema, never a deployment.
    query(preview_db,"""ALTER TABLE trading.positions ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
        UPDATE trading.positions SET quantity=5 WHERE portfolio_type='qt';
        CREATE SEQUENCE trading.synthetic_override_ids;
        ALTER TABLE trading.position_overrides ALTER COLUMN id SET DEFAULT nextval('trading.synthetic_override_ids');
        ALTER TABLE trading.position_overrides ADD COLUMN reason text,
          ADD COLUMN risk_check_result jsonb, ADD COLUMN overrode_risk boolean,
          ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();""")
    return preview_db


def prepare(dsn, quantity, monkeypatch, *, override=False):
    if override: seed_http_approvers(dsn)
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
    draft_response = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json={
        "expected_source_digest":initial["source_digest"],"expected_provenance_digest":initial["provenance_digest"],
        "expected_draft_revision":0,"idempotency_key":"00000000-0000-4000-8000-000000000051",
        "selection_rows":[{"key":row["key"],"quantity_exact":quantity}]})
    assert draft_response.status_code == 200, draft_response.json
    draft = draft_response.json
    authority(dsn, case='allowed_breach' if override else 'clean')
    # Explicit newer authoritative synthetic cost version admits quarter shares.
    payload = deepcopy(query(dsn,"SELECT payload FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1")[0][0])
    payload["engine_inputs"]["component_cost_inputs"][0]["calculation_increment_exact"] = "0.25"
    query(dsn,"""INSERT INTO trading.qt_evaluation_snapshots
        (book_id,source_day,model_publication_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        SELECT book_id,source_day,model_publication_id,producer_id,policy_version,'connected-cost-quarter-v2',
          as_of,valid_until,%s,%s FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1""",
        (sha256(canonical_qt_input_bytes(payload)).hexdigest(),Json(payload)))
    preview_response = browser.post('/portfolio/qt-previews', headers=headers, json={"book_id":"BOOK","draft_id":draft["draft_id"],
        "draft_revision":draft["draft_revision"],"draft_digest":draft["draft_digest"],
        "expected_source_digest":draft["source_digest"],"expected_provenance_digest":draft["provenance_digest"],
        "idempotency_key":"00000000-0000-4000-8000-000000000052"})
    assert preview_response.status_code == 200, preview_response.json
    preview = preview_response.json
    assert preview["confirmable"] and preview["selection_rows"][0]["quantity_exact"] == quantity
    decision_response = browser.post('/portfolio/qt-previews/' + preview['preview_id'] + '/confirm', headers=headers, json={"action":"confirm_selected_book",
        "expected_digest":preview["payload_digest"],"idempotency_key":"00000000-0000-4000-8000-000000000053",
        "acknowledge_warnings":override})
    assert decision_response.status_code == 200, decision_response.json
    decision = decision_response.json
    assert not decision["report_ready"] and decision["receipt"] is None
    assert query(dsn,"SELECT quantity FROM trading.positions WHERE portfolio_type='qt'") == [(Decimal(5),)]
    assert query(dsn,"SELECT count(*) FROM trading.position_overrides") == [(0,)]
    return {'browser': browser, 'headers': headers, 'clients': clients}, preview, decision


def observe(dsn, preview, decision, quantity):
    now = query(dsn,"SELECT clock_timestamp()")[0][0]
    fill = {"key":{**preview["selection_rows"][0]["key"],"portfolio_type":"qt"},
        "observation_kind":"executed","selected_quantity_exact":quantity,"average_price_exact":"101",
        "actual_cash_cost_exact":"0.02","currency":"USD","execution_id":"synthetic-connected-fill",
        "accounting_source_id":"synthetic-connected-accounting","daily_unrealized_pnl_exact":"3",
        "daily_realized_pnl_exact":"-1","last_update":now.isoformat().replace("+00:00","Z")}
    payload = {"schema_version":"qt-execution/v1","decision_id":decision["decision_id"],"book_id":"BOOK",
        "source_day":preview["source_day"],"fills":[fill],"results":{"position_count":1,"currency_totals":[
            {"currency":"USD","actual_cash_cost_exact":"0.02","daily_unrealized_pnl_exact":"3","daily_realized_pnl_exact":"-1"}]}}
    query(dsn,"""INSERT INTO trading.qt_source_policies(book_id,purpose,enabled,version,producer_id,policy_version,allowed_override_codes)
        VALUES('BOOK','execution',true,1,'synthetic-connected-execution','connected-execution-v1','[]')""")
    query(dsn,"""INSERT INTO trading.qt_execution_observations
        (observation_id,decision_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        VALUES(%s,%s,'synthetic-connected-execution','connected-execution-v1','connected-observation-v1',%s,%s,%s,%s)""",
        (OBSERVATION,decision["decision_id"],now,now+timedelta(minutes=5),sha256(canonical_qt_input_bytes(payload)).hexdigest(),Json(payload)))


def desk(decision):
    return subprocess.run([str(DESK),decision["decision_id"],ATTEMPT,OBSERVATION],
        capture_output=True,text=True,timeout=30,env=os.environ.copy())


def assert_positions_rows_match_saved(report_html, report_csv, baseline_html, baseline_csv, rows):
    """Prove report_html/report_csv render exactly the saved positions -- not
    a stale pre-decision baseline plus a substituted cell (spec: 'Row values
    come from the saved position through the renderers' existing formulas').

    rows: iterable of (strategy_display_name, symbol, quantity_exact,
    average_price_exact, multiplier_exact, market_price_exact) -- e.g.
    ('One', 'SYN', '7', '101', '1', '102').

    Quantity is checked as the renderer's exact string: email_sender.cpp's
    format_single_strategy_table streams `qty` (quantity_exact or
    position.quantity.to_string(), a std::string) with `std::setprecision(0)`
    applied -- a no-op on a string, so the cell is the exact decimal, not a
    rounded double (email_sender.cpp:3153,3165).

    HTML and CSV render notional from two different price bases -- neither is
    tautological against the other, so both are independently recomputed from
    caller-supplied, fixture-specific values (PLAN13; PLAN12 conflated them
    into one `signed_notional` and both callers and this helper were wrong
    about which basis feeds which cell):

    - HTML: quantity * average_price_exact * multiplier, formatted
      $<abs(...) with commas, 2 decimals> (email_sender.cpp:3143-3146 computes
      `position.quantity.as_double() * position.average_price.as_double() *
      contract_multiplier`; line 3167 does `std::abs(notional)` before
      formatting). `position.average_price` is the position's *saved* average
      price -- the fill/accounting basis actually written to
      trading.positions for this row, which callers must supply as the true
      basis for their fixture (see each call site's comment).

    - CSV: quantity * market_price_exact * multiplier, signed, no abs().
      qt_processed_report_probe.cpp:81,84 calls export_current_positions with
      an explicit (empty) StrategyInstancesMap, which selects the overload at
      csv_exporter.cpp:477-489 and fixes model_columns_absent=false -- the
      other, desk/QT `model_columns_absent=true` overload is never reached by
      this probe. That overload's row loop (csv_exporter.cpp:631-639) starts
      `market_price` as a fallback to the position's own saved average price
      (`market_price = pos_it->second.average_price.as_double(); // Default
      fallback`) and only overwrites it from `market_prices[symbol]` when the
      symbol is present there -- a symbol missing from market_prices silently
      renders at the average-price basis instead of failing. The probe always
      supplies all three symbols (market_prices = {'SYN':102,'IMM':102,
      'FUT':102}, qt_processed_report_probe.cpp:79,81,84, to both the HTML and
      CSV/baseline builders), so market_price_exact is '102' for every symbol
      in every test that uses this probe, and that fallback never triggers
      here. `calculate_notional(symbol, quantity, market_price)`
      (csv_exporter.cpp:63-88) then computes
      `quantity * price * contract_multiplier`, signed.

    Avoiding an exact-string dependency on C++'s std::defaultfloat double
    formatting, the CSV check compares Decimal(row[notional]) numerically
    rather than a formatted string.

    Margin (a strategy/portfolio summary line, not a per-row cell) and % of
    total are not independently re-derived here -- % of total needs every
    other row's notional in the same strategy table to reproduce, and margin
    needs the native instrument registry's per-symbol margin requirement,
    neither available to this Python-side test. Both, and every other byte
    outside the rows above, are proven correct by whole-document identity
    against baseline_html/baseline_csv instead: qt_processed_report_probe.cpp
    builds both from the identical saved snapshot (build_qt_saved_report_
    snapshot), baseline_* with no projection pointer and report_* with one,
    and email_sender.cpp:3094's row-drawing condition
    (`quantity != 0 || listed`) only differs between the two for a row the
    projection lists at zero quantity (closed today) -- the one case none of
    this helper's callers exercise. That makes the identity a proof for
    these specific tests, not an assumption.
    """
    assert report_html == baseline_html
    assert report_csv == baseline_csv
    csv_rows = list(csv.reader(io.StringIO(report_csv)))
    header = next(row for row in csv_rows if row and row[0] == "strategy")
    column = {name: header.index(name) for name in ("strategy", "symbol", "quantity", "notional")}
    for owner, symbol, quantity_exact, average_price_exact, multiplier_exact, market_price_exact in rows:
        html_notional = Decimal(quantity_exact) * Decimal(average_price_exact) * Decimal(multiplier_exact)
        csv_notional = Decimal(quantity_exact) * Decimal(market_price_exact) * Decimal(multiplier_exact)
        assert ("<td>" + symbol + "</td>\n<td>" + quantity_exact + "</td>") in report_html
        assert ("$" + format(abs(html_notional), ",.2f")) in report_html
        matches = [row for row in csv_rows if len(row) > max(column.values())
                   and row[column["strategy"]] == owner and row[column["symbol"]] == symbol]
        assert len(matches) == 1, (owner, symbol, matches)
        row = matches[0]
        assert row[column["quantity"]] == quantity_exact
        assert Decimal(row[column["notional"]]) == csv_notional


def report(preview, directory):
    directory.mkdir()
    assert DELIVERY_GUARD.is_file(), 'Build the test-only delivery guard first'
    report_environment = {**os.environ, 'LD_PRELOAD': str(DELIVERY_GUARD)}
    return subprocess.run([str(REPORT),"BOOK",preview["source_day"],"engine-one",str(directory),"ONE"],
        capture_output=True,text=True,timeout=30,env=report_environment)


@pytest.mark.parametrize("quantity",["7","2.5","-1.25"])
def test_actual_decision_saved_quantity_is_the_only_report_change(connected_db,tmp_path,monkeypatch,quantity):
    http,preview,decision = prepare(connected_db,quantity,monkeypatch)
    pending = report(preview,tmp_path/"qt-report-pending")
    assert pending.returncode != 0 and list((tmp_path/"qt-report-pending").iterdir()) == []
    observe(connected_db,preview,decision,quantity)
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    assert query(connected_db,"SELECT quantity FROM trading.positions WHERE portfolio_type='qt'") == [(Decimal(quantity),)]
    ready = http['browser'].get('/portfolio/qt-decisions/' + decision['decision_id'])
    assert ready.status_code == 200 and ready.json['report_ready'] is True, ready.json
    rendered = report(preview,tmp_path/"qt-report-processed")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    output = json.loads(rendered.stdout)
    assert output['delivery_guard_loaded'] is True and output['delivery_calls'] == 0
    assert output["quantities"] == {"ONE":{"SYN":quantity}}
    # SYN's saved average_price is 101 (observe()'s fill, average_price_exact
    # field, test_qt_connected_workflow.py:95) and its multiplier is 1 (an
    # equity), matching FULL-API-BUILD11-FAILURE-TRIAGE-1.md. Market price is
    # the probe's fixed 102 (qt_processed_report_probe.cpp:79,81,84).
    assert_positions_rows_match_saved(output["report_html"], output["report_csv"],
        output["baseline_html"], output["baseline_csv"], [("One", "SYN", quantity, "101", "1", "102")])
    print('QT_REPORT_EVIDENCE=' + json.dumps({'selected_quantity_exact':quantity,
        'source_day':preview['source_day'], **output}, sort_keys=True, separators=(',', ':')), flush=True)
    query(connected_db,"UPDATE trading.positions SET daily_realized_pnl=9 WHERE portfolio_type='qt'")
    assert report(preview,tmp_path/"qt-report-stale").returncode != 0
    stale = http['browser'].get('/portfolio/qt-decisions/' + decision['decision_id'])
    assert stale.status_code == 200 and stale.json['report_ready'] is False, stale.json


def test_failed_execution_evidence_keeps_positions_and_report_unpublished(connected_db,tmp_path,monkeypatch):
    http,preview,decision = prepare(connected_db,"7",monkeypatch)
    observe(connected_db,preview,decision,"6")
    refused = desk(decision)
    assert refused.returncode != 0
    assert query(connected_db,"SELECT quantity FROM trading.positions WHERE portfolio_type='qt'") == [(Decimal(5),)]
    assert query(connected_db,"SELECT count(*) FROM trading.qt_desk_receipts") == [(0,)]
    assert query(connected_db,"SELECT count(*) FROM trading.qt_desk_results") == [(0,)]
    assert query(connected_db,"SELECT count(*) FROM trading.position_overrides") == [(0,)]
    assert report(preview,tmp_path/"qt-report-failed").returncode != 0
    unavailable = http['browser'].get('/portfolio/qt-decisions/' + decision['decision_id'])
    assert unavailable.status_code == 200 and unavailable.json['report_ready'] is False, unavailable.json


def test_two_people_http_approval_then_native_desk_and_report(connected_db,tmp_path,monkeypatch):
    http,preview,decision = prepare(connected_db,'7',monkeypatch,override=True)
    assert decision['status'] == 'pending_override'
    observe(connected_db,preview,decision,'7')
    assert desk(decision).returncode != 0
    second, second_headers = http['clients'](202)
    discovery = second.get('/portfolio/qt-books/BOOK/decision?source_day=' + preview['source_day'])
    assert discovery.status_code == 200 and discovery.json['preview'] == preview, discovery.json
    assert discovery.json['decision']['can_approve'] is True
    path = '/portfolio/qt-override-requests/' + decision['request_id'] + '/approvals'
    first = http['browser'].post(path, headers=http['headers'],
        json={'action':'approve','idempotency_key':str(uuid4())})
    assert first.status_code == 200 and first.json['approvals_count'] == 1, first.json
    assert desk(decision).returncode != 0
    approved = second.post(path, headers=second_headers,
        json={'action':'approve','idempotency_key':str(uuid4())})
    assert approved.status_code == 200 and approved.json['status'] == 'confirmed_decision', approved.json
    processed = desk(approved.json)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    ready = second.get('/portfolio/qt-books/BOOK/decision?source_day=' + preview['source_day'])
    assert ready.status_code == 200 and ready.json['decision']['report_ready'] is True, ready.json
    rendered = report(preview,tmp_path/'qt-report-approved')
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    output = json.loads(rendered.stdout)
    assert output['delivery_guard_loaded'] is True and output['delivery_calls'] == 0
    assert output['quantities'] == {'ONE': {'SYN': '7'}}
    assert output['report_html'] == output['baseline_html'].replace('<td>SYN</td>\n<td>5</td>', '<td>SYN</td>\n<td>7</td>', 1)


def test_http_confirmation_retry_after_actual_publication_is_authorized_and_exact(connected_db,monkeypatch):
    http, preview, decision = prepare(connected_db, '7', monkeypatch)
    observe(connected_db, preview, decision, '7')
    published = desk(decision)
    assert published.returncode == 0, published.stdout + published.stderr
    assert query(connected_db, "SELECT quantity FROM trading.positions WHERE portfolio_type='qt'") == [(Decimal(7),)]
    assert http['browser'].get('/portfolio/qt-decisions/' + decision['decision_id']).json['report_ready'] is True

    def snapshot():
        # Complete owned fixture rows, including accounting, immutable evidence
        # and idempotency records. The only intentional change below is access.
        tables = ('positions', 'position_overrides', 'qt_drafts', 'qt_draft_heads',
            'qt_previews', 'qt_decisions', 'qt_override_requests', 'qt_override_approvals',
            'qt_idempotency', 'qt_desk_receipts', 'qt_desk_results', 'qt_execution_observations')
        return {name: query(connected_db, 'SELECT to_jsonb(t) FROM trading.' + name +
            ' t ORDER BY to_jsonb(t)::text') for name in tables}

    saved = snapshot()
    path = '/portfolio/qt-previews/' + preview['preview_id'] + '/confirm'
    body = {'action': 'confirm_selected_book', 'expected_digest': preview['payload_digest'],
        'idempotency_key': '00000000-0000-4000-8000-000000000053', 'acknowledge_warnings': False}
    recovered = http['browser'].post(path, headers=http['headers'], json=body)
    assert recovered.status_code == 200 and recovered.json == decision, recovered.json
    assert snapshot() == saved

    conflict = http['browser'].post(path, headers=http['headers'],
        json={**body, 'acknowledge_warnings': True})
    assert conflict.status_code == 409 and conflict.json['error']['code'] == 'idempotency_conflict', conflict.json
    assert snapshot() == saved

    query(connected_db, "UPDATE trading.qt_action_grants SET active=false,version=version+1 "
        "WHERE user_id=101 AND capability='qt_submit'")
    refused = http['browser'].post(path, headers=http['headers'], json=body)
    assert refused.status_code == 403 and refused.json['error']['code'] == 'authorization_changed', refused.json
    assert 'decision_id' not in refused.json and snapshot() == saved

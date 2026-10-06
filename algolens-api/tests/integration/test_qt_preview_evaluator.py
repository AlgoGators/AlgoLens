"""Actual compiled evaluator plus immutable governed SQL preview authority."""

from copy import deepcopy
from datetime import date, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import psycopg2
from psycopg2.extras import Json
import pytest

from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_evaluator_client import QtEvaluatorClient
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from tests.integration.test_qt_a3_read_set_postgres import a3_db, PUBLICATION
from tests.qt_native_evaluator import native_evaluator_configuration, native_evaluator_requests


MIGRATION = Path(__file__).resolve().parents[2] / "migrations/004_qt_governed_sources.sql"
BUNDLE_MIGRATION = Path(__file__).resolve().parents[2] / "migrations/005_qt_evaluator_bundle.sql"


def query(dsn, sql, values=()):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, values)
            return cursor.fetchall() if cursor.description else None


def test_actual_client_admits_selected_split_and_richer_optimizer_evidence():
    process = QtEvaluatorProcess(**native_evaluator_configuration())
    requests = native_evaluator_requests()
    selected = QtEvaluatorClient(process).evaluate(requests["selected_book"])
    assert selected.available and selected.evidence["selected_costs"]["total_exact"] == "0.02"
    diagnostic = requests["draft_diagnostic"]
    stamps = [(date(2026, 9, 5) + timedelta(days=index)).isoformat() + "T12:00:00Z" for index in range(21)]
    closes = [{"instrument": {"instrument_type": "EQUITY", "symbol": "SYN"}, "timestamp": stamp,
               "close": "100" if index % 2 == 0 else "110"} for index, stamp in enumerate(stamps)]
    for inputs in (diagnostic["risk_inputs"], diagnostic["optimizer_inputs"]):
        inputs.update(expected_observation_times=stamps, closes=deepcopy(closes))
    admitted = QtEvaluatorClient(process).evaluate(diagnostic)
    optimizer = admitted.evidence["optimizer"]
    assert optimizer["status"] == "evaluated"
    assert optimizer["evaluated_book_digest"] == admitted.book_digest
    assert json.loads(optimizer["trace"][0])["buffer_branch"] in {"disabled", "returned_prior", "applied"}
    assert optimizer["trace"][1].startswith("tracking_error=")


@pytest.fixture
def preview_db(a3_db):
    native_evaluator_configuration()
    query(a3_db, MIGRATION.read_text())
    query(a3_db, BUNDLE_MIGRATION.read_text())
    query(a3_db, '''CREATE SCHEMA IF NOT EXISTS metadata;
        CREATE TABLE IF NOT EXISTS metadata.contract_metadata (
            "Databento Symbol" text, "IB Symbol" text, "Asset Type" text);
        TRUNCATE metadata.contract_metadata;
        INSERT INTO metadata.contract_metadata VALUES ('SYN', 'SYN', 'EQUITY');
        ALTER TABLE trading.positions ADD COLUMN daily_unrealized_pnl numeric(20,8),
          ADD COLUMN daily_realized_pnl numeric(20,8), ADD COLUMN last_update timestamptz;
        UPDATE trading.positions SET daily_unrealized_pnl=1.25, daily_realized_pnl=-0.5,
          last_update=clock_timestamp() WHERE portfolio_type='qt';''')
    return a3_db


def authority(dsn, *, case="clean", selection=None):
    day, now = query(dsn, "SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date, clock_timestamp()")[0]
    stamp = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    key = {"portfolio_id": "BOOK", "strategy_id": "engine-one", "strategy_name": "ONE",
           "date": day.isoformat(), "symbol": "SYN", "portfolio_type": "qt_proposal"}
    fixture = native_evaluator_requests()["selected_book"]
    risk = {name: value for name, value in fixture["risk_inputs"].items() if not name.startswith("expected_")}
    times = [(day - timedelta(days=21-index)).isoformat() + "T12:00:00Z" for index in range(21)]
    risk.update(valuation_time=stamp, expected_observation_times=times,
        valuations=[{"instrument": {"instrument_type": "EQUITY", "symbol": "SYN"}, "mark_as_of": stamp,
                     "mark": "100", "price_multiplier": "1", "quote_currency": "USD"}],
        closes=[{"instrument": {"instrument_type": "EQUITY", "symbol": "SYN"}, "timestamp": timestamp,
                 "close": canonical_position_decimal8(Decimal("98") + Decimal(index) / 10)}
                for index, timestamp in enumerate(times)])
    config = fixture["risk_config"]
    config.update(lookback_period=21, var_limit="10", jump_risk_limit="10", max_correlation="0.99")
    if case in {"allowed_breach", "unknown_breach"}: config["capital_exact"] = "100"
    cost = {**fixture["component_cost_inputs"][0], "key": key}
    payload = {"schema_version": "qt-inputs/v1", "book_id": "BOOK", "source_day": day.isoformat(),
        "model_publication_id": PUBLICATION,
        "instrument_catalog": [{"key": key, "instrument_type": "EQUITY", "editable": True}],
        "engine_inputs": {"risk_config_source_id": fixture["risk_config_source_id"], "risk_inputs": risk,
            "risk_config": config, "quantity_rules": fixture["quantity_rules"], "component_cost_inputs": [cost],
            "optimizer_policy": {"enabled": False, "config_source_id": "synthetic-optimizer-disabled"},
            "optimizer_inputs": None, "optimizer_config": None}}
    if selection is not None:
        payload["instrument_catalog"] = [{"key": {**row["key"], "portfolio_type": "qt_proposal"},
            "instrument_type": row["asset_type"], "editable": row["editable"]} for row in selection]
        instruments = sorted({row["key"]["symbol"] for row in selection})
        risk["valuations"] = [{**deepcopy(risk["valuations"][0]),
            "instrument": {"instrument_type": "EQUITY", "symbol": symbol}} for symbol in instruments]
        risk["closes"] = [{**deepcopy(row), "instrument": {"instrument_type": "EQUITY", "symbol": symbol}}
            for symbol in instruments for row in risk["closes"]]
        payload["engine_inputs"]["quantity_rules"] = [{**deepcopy(fixture["quantity_rules"][0]),
            "instrument": {"instrument_type": "EQUITY", "symbol": symbol}} for symbol in instruments]
        payload["engine_inputs"]["component_cost_inputs"] = [{**deepcopy(cost),
            "key": {**row["key"], "portfolio_type": "qt_proposal"},
            "instrument": {"instrument_type": "EQUITY", "symbol": row["key"]["symbol"]}}
            for row in selection if row["editable"]]
        config["max_correlation"] = "1"
        if case in {"bad_new_optimizer", "duplicate_new_optimizer_history"}:
            template = native_evaluator_requests()["draft_diagnostic"]
            opt = {name: deepcopy(value) for name, value in template["optimizer_inputs"].items()
                   if not name.startswith("expected_")}
            editable_symbols = {row["key"]["symbol"] for row in selection if row["editable"]}
            opt.update(valuation_time=stamp, expected_observation_times=times,
                instruments=[{**deepcopy(opt["instruments"][0]), "mark_as_of": stamp,
                    "instrument": {"instrument_type": "EQUITY", "symbol": symbol}}
                    for symbol in sorted(editable_symbols)],
                closes=[deepcopy(row) for row in risk["closes"] if row["instrument"]["symbol"] in editable_symbols])
            if case == "bad_new_optimizer":
                next(row for row in opt["instruments"] if row["instrument"]["symbol"] == "NEW")["unknown_field"] = "100"
            else:
                opt["closes"].append(deepcopy(next(row for row in opt["closes"] if row["instrument"]["symbol"] == "NEW")))
            payload["engine_inputs"].update(optimizer_policy=template["optimizer_policy"],
                optimizer_inputs=opt, optimizer_config=template["optimizer_config"])
    if case == "missing_mark": payload["engine_inputs"]["risk_inputs"]["valuations"] = []
    if case == "catalog_extra":
        payload["instrument_catalog"].append({"key": {**key, "symbol": "EXTRA"}, "instrument_type": "EQUITY", "editable": True})
    codes = ["gross_leverage", "net_leverage"] if case == "allowed_breach" else []
    configuration = native_evaluator_configuration()
    query(dsn, """INSERT INTO trading.qt_source_policies
        (book_id,purpose,enabled,version,producer_id,policy_version,evaluator_build,evaluator_sha256,evaluator_bundle_sha256,allowed_override_codes)
        VALUES ('BOOK','evaluation',true,1,'synthetic-reviewed-producer','synthetic-policy-v1',%s,%s,%s,%s)""",
        (configuration["expected_build"], configuration["expected_sha256"], configuration["expected_bundle_sha256"], Json(codes)))
    query(dsn, """INSERT INTO trading.qt_evaluation_snapshots
        (book_id,source_day,model_publication_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        VALUES ('BOOK',%s,%s,'synthetic-reviewed-producer','synthetic-policy-v1','synthetic-source-v1',%s,%s,%s,%s)""",
        (day, PUBLICATION, now, now + timedelta(minutes=5), sha256(canonical_qt_input_bytes(payload)).hexdigest(), Json(payload)))


def saved_draft(dsn):
    configuration = native_evaluator_configuration()
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(dsn)), evaluator_executable=configuration["executable"],
                                evaluator_bundle_directory=configuration["bundle_directory"])
    initial = service.get_draft("BOOK", 101).to_wire()
    selected = {"key": next(row for row in initial["selection_rows"] if row["editable"])["key"], "quantity_exact": "5"}
    draft = service.save_draft("BOOK", 101, {"expected_source_digest": initial["source_digest"],
        "expected_provenance_digest": initial["provenance_digest"], "expected_draft_revision": 0,
        "idempotency_key": "00000000-0000-4000-8000-000000000041", "rationale": "Evaluate the reviewed target.",
        "selection_rows": [selected]}).to_wire()
    request = {"book_id": "BOOK", "draft_id": draft["draft_id"], "draft_revision": draft["draft_revision"],
        "draft_digest": draft["draft_digest"], "expected_source_digest": draft["source_digest"],
        "expected_provenance_digest": draft["provenance_digest"],
        "idempotency_key": "00000000-0000-4000-8000-000000000042"}
    return service, request


@pytest.mark.parametrize("case", ["clean", "missing_mark", "catalog_extra", "missing_accounting", "allowed_breach", "unknown_breach"])
def test_actual_sql_preview_evaluates_or_blocks_explicit_source(case, preview_db):
    service, request = saved_draft(preview_db)
    authority(preview_db, case=case)
    if case == "missing_accounting": query(preview_db, "UPDATE trading.positions SET last_update=NULL WHERE portfolio_type='qt'")
    before = query(preview_db, "SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type")
    preview = service.create_preview(101, request).to_wire()
    ready = case in {"clean", "allowed_breach"}
    assert preview["confirmable"] is ready, (preview["unavailable_reasons"], preview["evaluation"]["selected_risk"])
    assert preview["availability"] == ("ready" if ready else "unavailable")
    assert preview["requires_override"] is (case == "allowed_breach")
    if ready:
        assert preview["evaluation"]["selected_costs"]["total_exact"] == "0.05"
        assert preview["evaluation"]["selected_costs"]["by_component"][0]["prior_quantity_exact"] == "0"
        assert preview["evaluation"]["optimizer"]["status"] == "disabled"
    assert service.create_preview(101, request).to_wire() == preview
    assert query(preview_db, "SELECT count(*) FROM trading.qt_previews") == [(1,)]
    assert query(preview_db, "SELECT count(*) FROM trading.qt_decisions") == [(0,)]
    assert query(preview_db, "SELECT count(*) FROM trading.position_overrides") == [(0,)]
    assert query(preview_db, "SELECT row_to_json(p)::text FROM trading.positions p ORDER BY symbol,portfolio_type") == before


def test_actual_preview_from_non_utc_source_session_is_admitted(preview_db):
    source_dsn = psycopg2.extensions.make_dsn(preview_db, options='-c timezone=America/New_York')
    service, request = saved_draft(source_dsn)
    authority(source_dsn)
    preview = service.create_preview(101, request).to_wire()
    assert preview["confirmable"], preview["unavailable_reasons"]
    assert preview["evaluation"]["selected_costs"]["total_exact"] == "0.05"


def test_actual_saved_pnl_and_time_changes_preview_read_set(preview_db):
    service, request = saved_draft(preview_db)
    authority(preview_db)
    first = service.create_preview(101, request).to_wire()
    assert first["confirmable"]
    query(preview_db, "UPDATE trading.positions SET daily_unrealized_pnl=2.5,last_update=clock_timestamp() WHERE portfolio_type='qt'")
    second = service.create_preview(101, {**request, "idempotency_key": "00000000-0000-4000-8000-000000000043"}).to_wire()
    assert second["confirmable"]
    assert second["read_set_digest"] != first["read_set_digest"]
    assert query(preview_db, "SELECT count(*) FROM trading.qt_previews") == [(2,)]


@pytest.mark.parametrize("case", ["clean", "bad_new_optimizer", "duplicate_new_optimizer_history"])
def test_actual_preview_preserves_immutable_and_new_unfilled_component(preview_db, case, monkeypatch):
    calls = []
    original_run = QtEvaluatorProcess.run
    def record_run(process, request):
        calls.append(request["operation"])
        return original_run(process, request)
    monkeypatch.setattr(QtEvaluatorProcess, "run", record_run)
    day = query(preview_db, "SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")[0][0]
    query(preview_db, """INSERT INTO metadata.contract_metadata VALUES ('IMM','IMM','EQUITY'),('NEW','NEW','EQUITY');
        INSERT INTO trading.strategy_registry (id,strategy_type,portfolio_id,is_active,lifecycle,updated_at)
          VALUES ('engine-immutable','IMMUTABLE','BOOK',false,'retired',clock_timestamp());""")
    query(preview_db, """INSERT INTO trading.positions
        (portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type,quantity,average_price,
         daily_unrealized_pnl,daily_realized_pnl,last_update)
        VALUES ('BOOK','IMMUTABLE','OLD',%s,'IMM','qt',8,25,1.25,-0.5,clock_timestamp())""", (day,))
    service, first_request = saved_draft(preview_db)
    first = service.get_draft("BOOK", 101).to_wire()
    syn = next(row for row in first["selection_rows"] if row["editable"])
    new_key = {**syn["key"], "symbol": "NEW"}
    draft = service.save_draft("BOOK", 101, {"expected_source_digest": first["source_digest"],
        "expected_provenance_digest": first["provenance_digest"], "expected_draft_revision": first["draft_revision"],
        "idempotency_key": "00000000-0000-4000-8000-000000000051",
        "rationale": "Evaluate the reviewed target with a new component.",
        "selection_rows": [{"key": syn["key"], "quantity_exact": "5"},
                           {"key": new_key, "quantity_exact": "2"}]}).to_wire()
    authority(preview_db, case=case, selection=draft["selection_rows"])
    request = {**first_request, "draft_id": draft["draft_id"],
               "draft_revision": draft["draft_revision"], "draft_digest": draft["draft_digest"],
               "idempotency_key": "00000000-0000-4000-8000-000000000052"}
    preview = service.create_preview(101, request).to_wire()
    if case != "clean":
        assert calls == [], "Malformed full authority reached evaluator after projection"
    assert preview["confirmable"] is (case == "clean"), preview["unavailable_reasons"]
    if case != "clean":
        assert preview["unavailable_reasons"] == ["evaluator_evidence_unavailable"]
        assert not preview["requires_override"]
        assert query(preview_db, "SELECT count(*) FROM trading.positions WHERE symbol='NEW'") == [(0,)]
        return
    rows = {row["key"]["symbol"]: row for row in preview["selection_rows"]}
    assert rows["IMM"]["quantity_exact"] == "8" and rows["IMM"]["key"]["portfolio_type"] == "qt"
    assert rows["NEW"]["basis_status"] == "unfilled" and rows["NEW"]["average_price_exact"] is None
    assert preview["evaluation"]["selected_costs"]["total_exact"] == "0.07"
    assert preview["optimizer_book_digest"] != preview["selected_book_digest"]
    assert query(preview_db, "SELECT count(*) FROM trading.positions WHERE symbol='NEW'") == [(0,)]

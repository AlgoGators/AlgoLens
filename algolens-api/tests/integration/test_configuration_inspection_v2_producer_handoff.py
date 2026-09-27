"""Generated C++ v2 JSONB children through the real SQL reader and Flask route."""

from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from algolens.application.configuration_inspection import ConfigurationInspectionService
from algolens.infrastructure.portfolio.configuration_inspection import PostgresConfigurationInspectionReader
from tests.integration.conftest import claim_schema, require_test_dsn
from tests.test_incubation_routes import _set_jwt_cookie


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "configuration_inspection_cpp_v2"
URL = "/portfolio/strategies/trend/configuration?portfolio_id=book"
PRIVATE_SENTINEL = "synthetic-v2-private-parent-must-not-escape"
OTHER_BOOK_SENTINEL = "synthetic-v2-other-book-must-not-escape"
DECIMAL_SENTINEL = "-92233720368.54775808"
CASES = (
    ("publish_required_complete-5bcf79c0c445", "available", "none", "complete", "none", 16, "uncontrolled"),
    ("publish_required_complete_controlled-0e2623f596ae", "available", "none", "complete", "none", 18, "controlled"),
    ("publish_required_partial-0a62072ce366", "available", "none", "partial", "nonfatal_error", 16, "uncontrolled"),
    ("publish_required_partial_controlled-e2aa4e09194b", "available", "none", "partial", "nonfatal_error", 18, "controlled"),
    ("publish_required_unavailable-8568faf3d85d", "available", "none", "unavailable", "instrumentation_missing", 0, "uncontrolled"),
    ("publish_required_unavailable_controlled-94e729d78eab", "available", "none", "unavailable", "instrumentation_missing", 0, "controlled"),
    ("publish_required_bad_capture_complete-cacaaeacf2f5", "unavailable", "capture_failed", "complete", "none", 16, "uncontrolled"),
    ("publish_required_bad_capture_complete_controlled-b5b8278979fe", "unavailable", "capture_failed", "complete", "none", 18, "controlled"),
    ("publish_required_early_unavailable_complete-d5324353f082", "unavailable", "projection_invalid", "complete", "none", 16, "uncontrolled"),
    ("publish_required_early_unavailable_complete_controlled-5a257484e45c", "unavailable", "projection_invalid", "complete", "none", 18, "controlled"),
)


def _connect():
    return psycopg2.connect(require_test_dsn(), cursor_factory=RealDictCursor)


def _write(sql, params=()):
    connection = _connect()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
    finally:
        connection.close()


def _install(stem):
    """Keep original child text and producer sidecars; add only labeled test traps."""
    raw = (FIXTURES / f"{stem}.jsonb.txt").read_bytes()
    provenance = json.loads((FIXTURES / f"{stem}.provenance.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(raw).hexdigest() == provenance["fixture_sha256"]
    assert len(raw) == provenance["fixture_bytes_jsonb_text"]
    publication = json.loads(raw)
    identity = publication["identity"]
    registry = provenance["registry"]
    assert provenance["capture_helper"] == "build_live_config_inspection_capture"
    assert provenance["recorded_time_provenance"] == "transaction clock_timestamp"
    assert (identity["registry_id"], identity["registry_revision"],
            identity["engine_strategy_id"], identity["portfolio_id"], identity["run_date"]) == (
        registry["id"], registry["runtime_revision"], registry["strategy_type"],
        registry["primary_book"], "2026-09-22")
    assert len(provenance["intents"]) == len(provenance["attempts"]) == (1 if identity["control_mode"] == "controlled" else 0)
    if identity["control_mode"] == "uncontrolled":
        assert identity["runtime_attempt_id"] is None
    else:
        intent, attempt = provenance["intents"][0], provenance["attempts"][0]
        assert identity["runtime_attempt_id"] == attempt["id"]
        assert identity["publication_id"] == attempt["publication_id"]
        assert attempt["intent_id"] == intent["id"]
        assert (attempt["status"], attempt["outcome"], intent["status"]) == ("applied", "published", "approved")

    # The owned-database guard runs before any fixture schema DROP/CREATE.
    connection = psycopg2.connect(require_test_dsn())
    try:
        with connection:
            with connection.cursor() as cursor:
                claim_schema(cursor)
                cursor.execute("""
                    CREATE TABLE trading.strategy_registry (
                        id text PRIMARY KEY, strategy_type text NOT NULL,
                        portfolio_id text NOT NULL, runtime_revision bigint NOT NULL);
                    CREATE TABLE trading.strategy_book_memberships (
                        strategy_id text NOT NULL, portfolio_id text NOT NULL);
                    CREATE TABLE trading.live_run_metadata (
                        strategy_id text NOT NULL, portfolio_id text NOT NULL,
                        date date NOT NULL, portfolio_config jsonb,
                        UNIQUE(strategy_id, portfolio_id, date));
                    CREATE TABLE trading.live_results (
                        strategy_id text NOT NULL, portfolio_id text NOT NULL,
                        portfolio_type text NOT NULL, date timestamptz NOT NULL,
                        source_row jsonb);
                    CREATE TABLE trading.runtime_intents (
                        id bigint PRIMARY KEY, registry_id text NOT NULL,
                        portfolio_id text NOT NULL, engine_strategy_id text NOT NULL,
                        registry_revision bigint NOT NULL, action text NOT NULL, status text);
                    CREATE TABLE trading.runtime_attempts (
                        id text PRIMARY KEY, intent_id bigint NOT NULL,
                        registry_revision bigint NOT NULL, run_date date NOT NULL,
                        status text NOT NULL, outcome text, publication_id text);
                """)
                cursor.execute("INSERT INTO trading.strategy_registry VALUES (%s,%s,%s,%s)",
                               (registry["id"], registry["strategy_type"], registry["primary_book"], registry["runtime_revision"]))
                for book in provenance["membership_books"]:
                    cursor.execute("INSERT INTO trading.strategy_book_memberships VALUES (%s,%s)", (registry["id"], book))
                for intent in provenance["intents"]:
                    cursor.execute("INSERT INTO trading.runtime_intents VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                   (intent["id"], intent["registry_id"], intent["portfolio_id"],
                                    intent["engine_strategy_id"], intent["registry_revision"],
                                    intent["action"], intent["status"]))
                for attempt in provenance["attempts"]:
                    cursor.execute("INSERT INTO trading.runtime_attempts VALUES (%s,%s,%s,%s,%s,%s,%s)",
                                   (attempt["id"], attempt["intent_id"], attempt["registry_revision"],
                                    attempt["run_date"], attempt["status"], attempt["outcome"],
                                    attempt["publication_id"]))
                # Original UTF-8 child text is cast directly to JSONB. Do not pass a Python reserialization.
                cursor.execute("""
                    INSERT INTO trading.live_run_metadata VALUES
                    (%s,%s,%s,jsonb_build_object('config_inspection', %s::jsonb, 'private_sentinel', %s))
                """, (identity["engine_strategy_id"], identity["portfolio_id"],
                      identity["run_date"], raw.decode("utf-8"), PRIVATE_SENTINEL))
                for row in provenance["system_results"]:
                    result = json.loads(row["row_jsonb_text"])
                    assert row["run_date"] == "2026-09-22" == identity["run_date"]
                    assert result["date"] == "2026-09-22T00:00:00+00:00"
                    assert (result["strategy_id"], result["portfolio_id"], result["portfolio_type"]) == (
                        identity["engine_strategy_id"], identity["portfolio_id"], "system")
                    cursor.execute("""
                        INSERT INTO trading.live_results VALUES (%s,%s,%s,%s,%s::jsonb)
                    """, (result["strategy_id"], result["portfolio_id"], result["portfolio_type"],
                          result["date"], row["row_jsonb_text"]))
                # Synthetic selection traps, not producer provenance.
                later = (datetime.fromisoformat(identity["run_date"]) + timedelta(days=1)).date().isoformat()
                cursor.execute("INSERT INTO trading.live_results VALUES (%s,%s,%s,%s,NULL),(%s,%s,%s,%s,NULL)",
                               (identity["engine_strategy_id"], identity["portfolio_id"], "qt", later + "T16:00:00Z",
                                identity["engine_strategy_id"], "OTHER_BOOK", "system", later + "T16:00:00Z"))
                cursor.execute("INSERT INTO trading.live_run_metadata VALUES (%s,%s,%s,%s::jsonb)",
                               (identity["engine_strategy_id"], "OTHER_BOOK", later,
                                json.dumps({"config_inspection": {"sentinel": OTHER_BOOK_SENTINEL}})))
    finally:
        connection.close()

    with _connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT (portfolio_config -> 'config_inspection')::text AS child_text,
                       octet_length((portfolio_config -> 'config_inspection')::text) AS child_bytes
                FROM trading.live_run_metadata WHERE strategy_id=%s AND portfolio_id=%s
            """, (identity["engine_strategy_id"], identity["portfolio_id"]))
            row = cursor.fetchone()
    assert row["child_text"].encode("utf-8") == raw
    assert row["child_bytes"] == len(raw)
    print(f"GENERATED_V2_SQL_CASE={stem} SHA256={hashlib.sha256(raw).hexdigest()} BYTES={row['child_bytes']}")
    return publication, provenance


def _get(client, monkeypatch, publication):
    import algolens.adapters.http.configuration_inspection as http

    recorded_at = datetime.fromisoformat(publication["publication_recorded_at"].replace("Z", "+00:00"))
    captured_at = datetime.fromisoformat(publication["captured_at"].replace("Z", "+00:00"))
    read_at = max(recorded_at, captured_at) + timedelta(minutes=1)
    service = ConfigurationInspectionService(PostgresConfigurationInspectionReader(_connect), clock=lambda: read_at)
    monkeypatch.setattr(http, "create_configuration_inspection_service", lambda: service)
    _set_jwt_cookie(client, role="admin", identity="7")
    return client.get(URL), read_at


def _assert_no_private_data(response):
    body = response.get_data(as_text=True)
    assert PRIVATE_SENTINEL not in body
    assert OTHER_BOOK_SENTINEL not in body
    assert response.headers["Cache-Control"] == "no-store"


def _assert_refusal(response, reason):
    assert response.status_code == 200
    _assert_no_private_data(response)
    assert (response.json["status"], response.json["reason"], response.json["publication"]) == (
        "unavailable", reason, None)


def _capture(response, tmp_path, label):
    # The fixture copy after pytest is mechanical; never rebuild these bytes.
    response_path = tmp_path / f"{label}.http.json"
    response_path.write_bytes(response.get_data())
    wire = response_path.read_bytes()
    print(f"GENERATED_V2_HTTP_CASE={label} PATH={response_path} SHA256={hashlib.sha256(wire).hexdigest()} BYTES={len(wire)}")


@pytest.mark.parametrize("case", CASES, ids=[row[0] for row in CASES])
def test_generated_v2_child_survives_sql_and_authenticated_http(case, client, monkeypatch, tmp_path):
    # Catches silent loss of a valid generated child, final-consumption replacement,
    # wrong early-status envelope, book/stream selection, and Decimal8 coercion.
    stem, early_status, early_reason, consumption_status, consumption_reason, nodes, control_mode = case
    publication, provenance = _install(stem)
    response, read_at = _get(client, monkeypatch, publication)
    assert response.status_code == 200
    _assert_no_private_data(response)
    body = response.json
    assert set(body) == {"api_version", "scope", "read_at", "status", "reason", "publication"}
    assert body["api_version"] == 1
    assert body["scope"] == {"registry_id": "trend", "portfolio_id": "BOOK"}
    assert body["read_at"] == read_at.isoformat().replace("+00:00", "Z")
    assert (body["status"], body["reason"]) == (early_status, early_reason)
    assert body["publication"] == publication
    assert publication["publication_schema_version"] == 2
    assert (publication["status"], publication["reason"]) == (early_status, early_reason)
    assert (publication["consumption"]["status"], publication["consumption"]["reason"]) == (
        consumption_status, consumption_reason)
    assert len(publication["consumption"]["nodes"]) == nodes
    assert set(publication["consumption"]["coverage"]) == {
        "setup", "control_flow", "market_input", "preparation", "primary",
        "execution", "cost_history", "diagnostics"}
    assert publication["consumption"]["coverage"]["control_flow"] == (
        {"status": "partial", "reason": "nonfatal_error"} if consumption_status == "partial" else
        {"status": "unavailable", "reason": "instrumentation_missing"} if consumption_status == "unavailable" else
        {"status": "complete", "reason": "none"})
    assert publication["identity"]["control_mode"] == control_mode
    assert publication["identity"]["producer_version"] == "local-test"
    assert publication["identity"]["runtime_attempt_id"] == (
        provenance["attempts"][0]["id"] if control_mode == "controlled" else None)
    assert publication["identity"]["run_date"] == "2026-09-22"
    if early_status == "unavailable":
        assert publication["supplied"] is None and publication["selected_trend"] is None
        assert consumption_status == "complete"
        assert publication["consumption"]["coverage"] == {
            "setup": {"status": "complete", "reason": "none"},
            "control_flow": {"status": "complete", "reason": "none"},
            "market_input": {"status": "complete", "reason": "none"},
            "preparation": {"status": "complete", "reason": "none"},
            "primary": {"status": "complete", "reason": "none"},
            "execution": {"status": "complete", "reason": "none"},
            "cost_history": {"status": "complete", "reason": "none"},
            "diagnostics": {"status": "complete", "reason": "none"},
        }
    else:
        assert publication["supplied"]["fields"]
        assert next(field["value"] for field in publication["supplied"]["fields"]
                    if field["path"] == "/initial_capital") == 500000
        assert publication["selected_trend"]["strategies"][0]["strategy_id"] == "TREND"
    if nodes:
        diagnostics = [node for node in publication["consumption"]["nodes"]
                       if node["consumer"] == "risk.diagnostics"]
        assert len(diagnostics) == 1
        reads = [row for row in diagnostics[0]["reads"] if row["field"] == "risk.capital"]
        assert reads == [{"field": "risk.capital", "value_type": "fixed_decimal8",
                          "value": DECIMAL_SENTINEL, "origin": "derived"}]

    # Capture Flask's actual response bytes under pytest-owned scratch.
    _capture(response, tmp_path, stem)


@pytest.mark.parametrize("stem", [CASES[0][0], CASES[7][0]])
def test_malformed_newest_v2_mutation_blocks_older_generated_publication(stem, client, monkeypatch, tmp_path):
    # Catches skipping a malformed latest row and exposing stale good values.
    publication, _ = _install(stem)
    newest = deepcopy(publication)  # Synthetic negative mutation, never a generated fixture.
    newest["identity"]["run_date"] = "2026-09-23"
    newest["captured_at"] = "2026-09-23T15:00:00Z"
    newest["publication_recorded_at"] = "2026-09-23T15:01:00Z"
    newest["consumption"]["reason"] = "synthetic-invalid-reason"
    _write("INSERT INTO trading.live_run_metadata VALUES (%s,%s,%s,%s::jsonb)",
           ("LIVE_TREND", "BOOK", "2026-09-23",
            json.dumps({"config_inspection": newest, "private_sentinel": PRIVATE_SENTINEL})))
    _write("INSERT INTO trading.live_results VALUES (%s,%s,%s,%s,NULL)",
           ("LIVE_TREND", "BOOK", "system", "2026-09-23T16:00:00Z"))
    response, _ = _get(client, monkeypatch, publication)
    _assert_refusal(response, "invalid_publication")
    assert "synthetic-invalid-reason" not in response.get_data(as_text=True)
    _capture(response, tmp_path, f"mutation-malformed-newest-{stem}")


def test_controlled_generated_attempt_link_mutation_refuses(client, monkeypatch, tmp_path):
    # Catches an applied attempt certifying a different publication UUID.
    publication, _ = _install(CASES[1][0])
    _write("UPDATE trading.runtime_attempts SET publication_id=%s",
           ("00000000-0000-4000-8000-000000000000",))
    response, _ = _get(client, monkeypatch, publication)
    _assert_refusal(response, "invalid_publication")
    _capture(response, tmp_path, "mutation-mismatched-attempt")


def test_generated_publication_current_scope_change_refuses(client, monkeypatch, tmp_path):
    # Catches presenting a past generated child as the current registry revision.
    publication, _ = _install(CASES[0][0])
    _write("UPDATE trading.strategy_registry SET runtime_revision=runtime_revision+1")
    response, _ = _get(client, monkeypatch, publication)
    _assert_refusal(response, "scope_changed")
    _capture(response, tmp_path, "mutation-scope-changed")

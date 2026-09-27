"""Real C++ publication bytes through PostgreSQL and the authenticated API."""

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


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PUBLICATION_PATH = FIXTURES / "configuration_inspection_cpp_controlled_v1.json"
PROVENANCE_PATH = FIXTURES / "configuration_inspection_cpp_controlled_v1.provenance.json"
URL = "/portfolio/strategies/trend/configuration?portfolio_id=book"
PRIVATE_SENTINEL = "synthetic-private-parent-must-not-escape"
OTHER_BOOK_SENTINEL = "synthetic-other-book-must-not-escape"


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


@pytest.fixture
def published_record():
    """Recreate the companion records; keep the C++ JSON child unchanged."""
    dsn = require_test_dsn()
    publication_bytes = PUBLICATION_PATH.read_bytes()
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(publication_bytes).hexdigest() == provenance["fixture_sha256"].lower()
    publication = json.loads(publication_bytes)
    identity = publication["identity"]
    registry = provenance["registry"]
    intent = provenance["intent"]
    attempt = provenance["attempt"]
    assert provenance["membership_books"] == []  # Actual producer: legacy primary-book fallback.
    assert provenance["capture_helper"] == "build_live_config_inspection_capture"
    assert provenance["recorded_time_provenance"] == "database clock_timestamp in final publication transaction"
    assert (identity["registry_id"], identity["registry_revision"],
            identity["engine_strategy_id"], identity["portfolio_id"]) == (
                registry["id"], registry["runtime_revision"],
                registry["strategy_type"], registry["primary_book"])
    assert identity["run_date"] == provenance["system_result_run_date"]
    assert identity["runtime_attempt_id"] == attempt["id"]
    assert identity["publication_id"] == attempt["publication_id"]
    assert identity["registry_revision"] == intent["registry_revision"] == attempt["registry_revision"]
    assert (intent["registry_id"], intent["portfolio_id"], intent["engine_strategy_id"]) == (
        registry["id"], registry["primary_book"], registry["strategy_type"])
    assert attempt["intent_id"] == intent["id"]
    assert attempt["run_date"] == identity["run_date"]

    connection = psycopg2.connect(dsn)
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
                        portfolio_type text NOT NULL, date timestamptz NOT NULL);
                    CREATE TABLE trading.runtime_intents (
                        id bigint PRIMARY KEY, registry_id text NOT NULL,
                        portfolio_id text NOT NULL, engine_strategy_id text NOT NULL,
                        registry_revision bigint NOT NULL, action text NOT NULL);
                    CREATE TABLE trading.runtime_attempts (
                        id text PRIMARY KEY, intent_id bigint NOT NULL,
                        registry_revision bigint NOT NULL, run_date date NOT NULL,
                        status text NOT NULL, outcome text, publication_id text);
                """)
                cursor.execute(
                    "INSERT INTO trading.strategy_registry VALUES (%s,%s,%s,%s)",
                    (registry["id"], registry["strategy_type"],
                     registry["primary_book"], registry["runtime_revision"]),
                )
                # The real sidecar has no explicit memberships. Do not invent one.
                cursor.execute(
                    "INSERT INTO trading.runtime_intents VALUES (%s,%s,%s,%s,%s,%s)",
                    (intent["id"], intent["registry_id"], intent["portfolio_id"],
                     intent["engine_strategy_id"], intent["registry_revision"], intent["action"]),
                )
                cursor.execute(
                    "INSERT INTO trading.runtime_attempts VALUES (%s,%s,%s,%s,%s,%s,%s)",
                    (attempt["id"], attempt["intent_id"], attempt["registry_revision"],
                     attempt["run_date"], attempt["status"], attempt["outcome"],
                     attempt["publication_id"]),
                )
                cursor.execute(
                    "INSERT INTO trading.live_run_metadata VALUES (%s,%s,%s,%s::jsonb)",
                    (identity["engine_strategy_id"], identity["portfolio_id"],
                     identity["run_date"], json.dumps({
                         "config_inspection": publication,
                         "private_sentinel": PRIVATE_SENTINEL,
                     })),
                )
                cursor.execute(
                    "INSERT INTO trading.live_results VALUES (%s,%s,%s,%s)",
                    (identity["engine_strategy_id"], identity["portfolio_id"],
                     "system", identity["run_date"] + "T16:00:00Z"),
                )
                # A newer QT row and another book make missing stream/book filters fail.
                later = (datetime.fromisoformat(identity["run_date"]) + timedelta(days=1)).date().isoformat()
                cursor.execute(
                    "INSERT INTO trading.live_results VALUES (%s,%s,%s,%s),(%s,%s,%s,%s)",
                    (identity["engine_strategy_id"], identity["portfolio_id"],
                     "qt", later + "T16:00:00Z",
                     identity["engine_strategy_id"], "OTHER_BOOK", "system",
                     later + "T16:00:00Z"),
                )
                cursor.execute(
                    "INSERT INTO trading.live_run_metadata VALUES (%s,%s,%s,%s::jsonb)",
                    (identity["engine_strategy_id"], "OTHER_BOOK", later,
                     json.dumps({"config_inspection": {"sentinel": OTHER_BOOK_SENTINEL}})),
                )
    finally:
        connection.close()
    return publication


def _get(client, monkeypatch, publication):
    import algolens.adapters.http.configuration_inspection as http

    recorded_at = datetime.fromisoformat(publication["publication_recorded_at"].replace("Z", "+00:00"))
    captured_at = datetime.fromisoformat(publication["captured_at"].replace("Z", "+00:00"))
    read_at = max(recorded_at, captured_at) + timedelta(minutes=1)
    service = ConfigurationInspectionService(
        PostgresConfigurationInspectionReader(_connect), clock=lambda: read_at)
    monkeypatch.setattr(http, "create_configuration_inspection_service", lambda: service)
    _set_jwt_cookie(client, role="admin", identity="7")
    return client.get(URL), read_at


def _assert_unavailable(response, expected_reason):
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json["status"] == "unavailable"
    assert response.json["reason"] == expected_reason
    assert response.json["publication"] is None
    assert PRIVATE_SENTINEL not in response.get_data(as_text=True)
    assert OTHER_BOOK_SENTINEL not in response.get_data(as_text=True)


def test_cpp_publication_survives_authenticated_postgres_http_handoff(
    published_record, client, monkeypatch, tmp_path
):
    response, read_at = _get(client, monkeypatch, published_record)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json
    assert set(body) == {"api_version", "scope", "read_at", "status", "reason", "publication"}
    assert body["api_version"] == 1
    assert body["scope"] == {"registry_id": "trend", "portfolio_id": "BOOK"}
    assert body["read_at"] == read_at.isoformat().replace("+00:00", "Z")
    assert (body["status"], body["reason"]) == ("available", "none")
    assert body["publication"] == published_record
    assert body["publication"]["identity"] == published_record["identity"]
    assert body["publication"]["captured_at"] == published_record["captured_at"]
    assert body["publication"]["publication_recorded_at"] == published_record["publication_recorded_at"]
    assert body["publication"]["consumption"] == {"status": "not_collected"}
    selected = body["publication"]["selected_trend"]
    assert selected["provenance"] == "shared_resolver_same_inputs"
    assert selected["slow_concentration_override"] == {"state": "absent"}
    assert len(selected["strategies"]) == 1
    strategy = selected["strategies"][0]
    assert (strategy["strategy_id"], strategy["strategy_type"],
            strategy["selected_allocation"]) == ("TREND", "TrendFollowingStrategy", 1.0)
    assert strategy["factory_resolved"]["max_history_size"] == 0
    assert strategy["constructor_normalized"]["max_history_size"] == 2520
    assert strategy["factory_resolved"]["ema_windows"][0] == [2, 8]
    assert PRIVATE_SENTINEL not in response.get_data(as_text=True)
    assert OTHER_BOOK_SENTINEL not in response.get_data(as_text=True)

    # Preserve Flask's actual wire bytes for the UI handoff, not a re-serialized dict.
    response_path = tmp_path / "config-inspection-producer-handoff-http-response.json"
    response_path.write_bytes(response.get_data())
    digest = hashlib.sha256(response_path.read_bytes()).hexdigest()
    print(f"CONFIG_INSPECTION_HTTP_RESPONSE_PATH={response_path} SHA256={digest}")


def test_mismatched_attempt_publication_link_rejects_without_old_values(
    published_record, client, monkeypatch
):
    # Fault caught: an applied attempt cannot attest a different publication UUID.
    _write("UPDATE trading.runtime_attempts SET publication_id=%s",
           ("00000000-0000-4000-8000-000000000000",))
    response, _ = _get(client, monkeypatch, published_record)
    _assert_unavailable(response, "invalid_publication")


def test_changed_current_registry_revision_rejects_without_old_values(
    published_record, client, monkeypatch
):
    # Fault caught: a past capture cannot be presented for the new registry scope.
    _write("UPDATE trading.strategy_registry SET runtime_revision=runtime_revision+1")
    response, _ = _get(client, monkeypatch, published_record)
    _assert_unavailable(response, "scope_changed")

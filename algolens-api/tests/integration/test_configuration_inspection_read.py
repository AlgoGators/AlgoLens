"""Actual read-only SQL boundary against disposable synthetic PostgreSQL."""

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from algolens.application.configuration_inspection import ConfigurationInspectionService, InspectionError
from algolens.infrastructure.portfolio.configuration_inspection import PostgresConfigurationInspectionReader
from tests.integration.conftest import claim_schema
from tests.test_incubation_routes import _set_jwt_cookie


FIXTURE = Path(__file__).parents[1] / "fixtures" / "configuration_inspection_v1.json"
NOW = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)


def _connect():
    return psycopg2.connect(os.environ["ALGOLENS_TEST_DB"], cursor_factory=RealDictCursor)


@pytest.fixture
def database():
    conn = psycopg2.connect(os.environ["ALGOLENS_TEST_DB"])
    with conn:
        with conn.cursor() as cur:
            claim_schema(cur)
            cur.execute("""
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
                INSERT INTO trading.strategy_registry VALUES ('trend','LIVE_TREND','BOOK',1);
                INSERT INTO trading.strategy_book_memberships VALUES ('trend','BOOK'),('trend','OTHER');
                INSERT INTO trading.live_results VALUES
                    ('LIVE_TREND','BOOK','system','2026-09-22T16:00:00Z'),
                    ('LIVE_TREND','BOOK','qt','2026-09-23T16:00:00Z'),
                    ('LIVE_TREND','OTHER','system','2026-09-22T16:00:00Z');
                INSERT INTO trading.runtime_intents VALUES (1,'trend','BOOK','LIVE_TREND',1,'run');
                INSERT INTO trading.runtime_attempts VALUES
                    ('11111111-1111-4111-8111-111111111111',1,1,'2026-09-22',
                     'applied','published','11111111-1111-4111-8111-111111111111');
            """)
            publication = json.loads(FIXTURE.read_text(encoding="utf-8"))
            cur.execute("""
                INSERT INTO trading.live_run_metadata VALUES (%s,%s,%s,%s::jsonb)
            """, ("LIVE_TREND", "BOOK", "2026-09-22",
                  json.dumps({"old_key": "synthetic-private-sentinel",
                              "config_inspection": publication})))
            cur.execute("""
                INSERT INTO trading.live_run_metadata VALUES (%s,%s,%s,%s::jsonb)
            """, ("LIVE_TREND", "OTHER", "2026-09-22", json.dumps({"old_key": "other"})))
    conn.close()
    return publication


def _service(connection_factory=_connect):
    return ConfigurationInspectionService(
        PostgresConfigurationInspectionReader(connection_factory), clock=lambda: NOW)


def _exec(sql, params=()):
    conn = _connect()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
    finally:
        conn.close()


def test_actual_sql_reads_valid_system_publication_not_newer_qt_or_parent(database):
    response = _service().inspect("trend", "book")
    assert response["status"] == "available"
    assert response["reason"] == "none"
    assert response["scope"] == {"registry_id": "trend", "portfolio_id": "BOOK"}
    assert response["publication"]["identity"]["run_date"] == "2026-09-22"
    assert "synthetic-private-sentinel" not in json.dumps(response)
    assert _service().inspect("trend", "OTHER")["reason"] == "legacy_publication"
    assert _service().inspect("trend", "OTHER")["publication"] is None


def test_newest_invalid_metadata_is_not_replaced_by_older_valid(database):
    _exec("INSERT INTO trading.live_results VALUES ('LIVE_TREND','BOOK','system','2026-09-23T00:00:00Z')")
    _exec("INSERT INTO trading.live_run_metadata VALUES ('LIVE_TREND','BOOK','2026-09-23',%s::jsonb)",
          (json.dumps({"config_inspection": {"secret": "must-not-escape"}}),))
    response = _service().inspect("trend", "BOOK")
    assert response["reason"] == "invalid_publication"
    assert response["publication"] is None
    assert "must-not-escape" not in json.dumps(response)


def test_membership_fallback_is_only_for_successful_empty_query(database):
    _exec("DELETE FROM trading.strategy_book_memberships")
    assert _service().inspect("trend", "BOOK")["status"] == "available"
    with pytest.raises(InspectionError) as exc:
        _service().inspect("trend", "OTHER")
    assert (exc.value.code, exc.value.status) == ("not_a_member_of_book", 400)
    _exec("DROP TABLE trading.strategy_book_memberships")
    with pytest.raises(InspectionError) as exc:
        _service().inspect("trend", "BOOK")
    assert exc.value.status == 503


def test_controlled_attempt_and_intent_are_required(database):
    _exec("UPDATE trading.runtime_attempts SET outcome='stopped'")
    assert _service().inspect("trend", "BOOK")["reason"] == "invalid_publication"
    _exec("UPDATE trading.runtime_attempts SET outcome='published'")
    _exec("UPDATE trading.runtime_intents SET portfolio_id='OTHER'")
    assert _service().inspect("trend", "BOOK")["reason"] == "invalid_publication"


def test_missing_stream_or_runtime_schema_is_storage_unavailable(database):
    _exec("ALTER TABLE trading.live_results DROP COLUMN portfolio_type")
    with pytest.raises(InspectionError) as exc:
        _service().inspect("trend", "BOOK")
    assert exc.value.status == 503
    _exec("ALTER TABLE trading.live_results ADD COLUMN portfolio_type text DEFAULT 'system'")
    _exec("DROP TABLE trading.runtime_attempts")
    with pytest.raises(InspectionError) as exc:
        _service().inspect("trend", "BOOK")
    assert exc.value.status == 503


def test_date_mismatch_and_changed_registry_revision(database):
    _exec("UPDATE trading.live_results SET date='2026-09-21T00:00:00Z' WHERE portfolio_type='system' AND portfolio_id='BOOK'")
    assert _service().inspect("trend", "BOOK")["reason"] == "publication_date_mismatch"
    _exec("UPDATE trading.live_results SET date='2026-09-22T00:00:00Z' WHERE portfolio_type='system' AND portfolio_id='BOOK'")
    _exec("UPDATE trading.strategy_registry SET runtime_revision=2")
    assert _service().inspect("trend", "BOOK")["reason"] == "scope_changed"


def test_system_result_date_column_is_timezone_independent(database):
    _exec("ALTER TABLE trading.live_results ALTER COLUMN date TYPE date USING date::date")

    def non_utc_connection():
        conn = _connect()
        with conn:
            with conn.cursor() as cur:
                cur.execute("SET TIME ZONE 'Pacific/Honolulu'")
        return conn

    response = _service(non_utc_connection).inspect("trend", "BOOK")
    assert response["status"] == "available"


def test_large_reserved_child_is_rejected_without_returning_its_text(database):
    huge = {"sentinel": "private" * 400000}
    _exec("UPDATE trading.live_run_metadata SET portfolio_config=%s::jsonb WHERE portfolio_id='BOOK'",
          (json.dumps({"config_inspection": huge}),))
    response = _service().inspect("trend", "BOOK")
    assert response["reason"] == "invalid_publication"
    assert response["publication"] is None


def test_producer_unavailable_keeps_bound_envelope_and_null_stages(database):
    unavailable = deepcopy(database)
    unavailable.update(status="unavailable", reason="projection_invalid",
                       supplied=None, selected_trend=None)
    _exec("UPDATE trading.live_run_metadata SET portfolio_config=%s::jsonb WHERE portfolio_id='BOOK'",
          (json.dumps({"config_inspection": unavailable}),))
    response = _service().inspect("trend", "BOOK")
    assert response["status"] == "unavailable"
    assert response["reason"] == "projection_invalid"
    assert response["publication"] == unavailable


def test_absent_publication_stays_unavailable_without_book_fallback(database):
    _exec("DELETE FROM trading.live_run_metadata WHERE portfolio_id='BOOK'")
    response = _service().inspect("trend", "BOOK")
    assert response["reason"] == "not_published"
    assert response["publication"] is None


@pytest.mark.parametrize("reason", [[], {}])
def test_malformed_unavailable_reason_is_200_through_sql_and_http(
    database, reason, client, monkeypatch
):
    import algolens.adapters.http.configuration_inspection as http

    malformed = deepcopy(database)
    malformed.update(status="unavailable", reason=reason, supplied=None,
                     selected_trend=None)
    _exec("UPDATE trading.live_run_metadata SET portfolio_config=%s::jsonb WHERE portfolio_id='BOOK'",
          (json.dumps({"config_inspection": malformed}),))
    service = _service()
    direct = service.inspect("trend", "BOOK")
    assert direct["status"] == "unavailable"
    assert direct["reason"] == "invalid_publication"
    assert direct["publication"] is None

    monkeypatch.setattr(http, "create_configuration_inspection_service", lambda: service)
    _set_jwt_cookie(client, role="admin", identity="7")
    response = client.get("/portfolio/strategies/trend/configuration?portfolio_id=BOOK")
    assert response.status_code == 200
    assert response.json["reason"] == "invalid_publication"
    assert response.json["publication"] is None


def test_repeatable_read_keeps_the_first_database_snapshot(database):
    updated = False
    session = {}

    class HookCursor(RealDictCursor):
        def execute(self, query, vars=None):
            nonlocal updated
            if not session and "FROM trading.strategy_registry WHERE id" in query:
                super().execute("SHOW transaction_read_only")
                session["read_only"] = self.fetchone()["transaction_read_only"]
                super().execute("SHOW transaction_isolation")
                session["isolation"] = self.fetchone()["transaction_isolation"]
            result = super().execute(query, vars)
            if not updated and "FROM trading.strategy_registry WHERE id" in query:
                updated = True
                _exec("UPDATE trading.live_run_metadata SET portfolio_config=%s::jsonb WHERE portfolio_id='BOOK'",
                      (json.dumps({"config_inspection": {"new_bad": True}}),))
            return result

    def hooked_connection():
        return psycopg2.connect(os.environ["ALGOLENS_TEST_DB"], cursor_factory=HookCursor)

    assert _service(hooked_connection).inspect("trend", "BOOK")["status"] == "available"
    assert updated
    assert session == {"read_only": "on", "isolation": "repeatable read"}
    assert _service().inspect("trend", "BOOK")["reason"] == "invalid_publication"

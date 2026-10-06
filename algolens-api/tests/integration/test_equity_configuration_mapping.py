"""Issue 84: exact equity SQL identity, without inventing an equity profile.

These tests characterize unavailable configuration inspection. The currently
accepted futures projection/consumption contract is not an equity manifest.
"""

from datetime import date, datetime, timezone
import json

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from algolens.application.configuration_inspection import ConfigurationInspectionService
from algolens.infrastructure.portfolio.configuration_inspection import PostgresConfigurationInspectionReader
from tests.integration.test_incubation_equity_mapping import synthetic_books
from tests.test_incubation_routes import _set_jwt_cookie


pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
CONFIG_PATH = "/portfolio/strategies/inc_meanrev/configuration"


def _execute(dsn, sql, params=()):
    connection = psycopg2.connect(dsn)
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
    finally:
        connection.close()


def _snapshot(dsn):
    connection = psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    connection.set_session(readonly=True)
    try:
        snapshot = {}
        with connection.cursor() as cursor:
            for table in (
                "strategy_registry", "strategy_book_memberships", "positions",
                "equity_curve", "portfolio_assignments", "live_results",
                "live_run_metadata", "runtime_intents", "runtime_attempts",
            ):
                cursor.execute(f"SELECT * FROM trading.{table} ORDER BY 1, 2")
                snapshot[table] = [dict(row) for row in cursor.fetchall()]
        return snapshot
    finally:
        connection.close()


@pytest.fixture
def equity_configuration(synthetic_books, monkeypatch):
    dsn = synthetic_books
    _execute(dsn, """
        ALTER TABLE trading.strategy_registry
            ADD COLUMN runtime_revision bigint NOT NULL DEFAULT 1;
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
        INSERT INTO trading.live_results VALUES
            ('LIVE_EQUITY_MEAN_REVERSION','EQUITY_MR_PORTFOLIO','system','2026-09-22T16:00:00Z'),
            ('LIVE_EQUITY_MEAN_REVERSION','EQUITY_MR_PORTFOLIO','qt','2026-09-24T16:00:00Z'),
            ('LIVE_EQUITY_MEAN_REVERSION','BASE_PORTFOLIO','system','2026-09-23T16:00:00Z'),
            ('LIVE_OTHER_ENGINE','EQUITY_MR_PORTFOLIO','system','2026-09-24T16:00:00Z');
        INSERT INTO trading.live_run_metadata VALUES
            ('LIVE_EQUITY_MEAN_REVERSION','EQUITY_MR_PORTFOLIO','2026-09-22',
             '{"parent_equity_knobs":"private-equity-parent-sentinel"}'),
            ('LIVE_EQUITY_MEAN_REVERSION','BASE_PORTFOLIO','2026-09-23',
             '{"parent_base_knobs":"private-base-parent-sentinel","config_inspection":{}}'),
            ('LIVE_OTHER_ENGINE','EQUITY_MR_PORTFOLIO','2026-09-24',
             '{"parent_other_knobs":"private-other-engine-sentinel","config_inspection":{}}');
    """)
    reads = []

    class ObservedCursor(RealDictCursor):
        """Observe real PostgreSQL rows; do not replace query results."""

        def execute(self, query, vars=None):
            self.selection = None
            if "FROM trading.live_run_metadata" in query:
                self.selection = "metadata"
            elif "FROM trading.live_results" in query:
                self.selection = "system_result"
            return super().execute(query, vars)

        def fetchone(self):
            row = super().fetchone()
            if self.selection:
                reads.append((self.selection, dict(row) if row is not None else None))
            return row

    service = ConfigurationInspectionService(
        PostgresConfigurationInspectionReader(
            lambda: psycopg2.connect(dsn, cursor_factory=ObservedCursor)
        ),
        clock=lambda: NOW,
    )
    import algolens.adapters.http.configuration_inspection as configuration_http

    monkeypatch.setattr(
        configuration_http, "create_configuration_inspection_service", lambda: service
    )
    return dsn, reads


def _assert_unavailable(response, reason):
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.get_json() == {
        "api_version": 1,
        "scope": {"registry_id": "inc_meanrev", "portfolio_id": "EQUITY_MR_PORTFOLIO"},
        "read_at": "2026-09-25T12:00:00Z",
        "status": "unavailable", "reason": reason, "publication": None,
    }
    assert "private-" not in response.get_data(as_text=True)


def test_incubation_selected_equity_book_config_uses_exact_sql_identity(
    equity_configuration, client
):
    """Fails if registry/engine/book selection, stream, or parent isolation leaks."""
    dsn, reads = equity_configuration
    before = _snapshot(dsn)
    _set_jwt_cookie(client, role="admin")

    listing = client.get("/portfolio/incubation")
    assert listing.status_code == 200
    selected = next(row for row in listing.get_json()["incubating_strategies"]
                    if row["id"] == "inc_meanrev")
    assert (selected["id"], selected["strategy_type"], selected["portfolio_id"]) == (
        "inc_meanrev", "LIVE_EQUITY_MEAN_REVERSION", "EQUITY_MR_PORTFOLIO"
    )
    performance = client.get(f"/portfolio/incubation/{selected['id']}/performance")
    assert performance.status_code == 200
    assert [row["symbol"] for row in performance.get_json()["positions"]] == ["EQ_A", "EQ_B"]
    assert [row["equity"] for row in performance.get_json()["equity_curve"]] == [310125.75, 312430.25]

    response = client.get(CONFIG_PATH, query_string={"portfolio_id": selected["portfolio_id"]})
    _assert_unavailable(response, "legacy_publication")
    assert reads == [
        ("metadata", {"date": date(2026, 9, 22),
                      "strategy_id": "LIVE_EQUITY_MEAN_REVERSION",
                      "portfolio_id": "EQUITY_MR_PORTFOLIO",
                      "child_bytes": None, "child_text": None}),
        ("system_result", {"run_date": date(2026, 9, 22)}),
    ]
    base = client.get(CONFIG_PATH, query_string={"portfolio_id": "BASE_PORTFOLIO"})
    assert base.status_code == 200
    assert base.get_json()["scope"]["portfolio_id"] == "BASE_PORTFOLIO"
    assert base.get_json()["reason"] == "invalid_publication"
    assert base.get_json()["publication"] is None
    assert _snapshot(dsn) == before


def test_absent_equity_publication_does_not_fall_back_to_base_or_other_engine(
    equity_configuration, client
):
    """Fails if absent target data is replaced by a member/control publication."""
    dsn, reads = equity_configuration
    _execute(dsn, "DELETE FROM trading.live_run_metadata WHERE strategy_id=%s AND portfolio_id=%s",
             ("LIVE_EQUITY_MEAN_REVERSION", "EQUITY_MR_PORTFOLIO"))
    before = _snapshot(dsn)
    _set_jwt_cookie(client, role="admin")
    response = client.get(CONFIG_PATH, query_string={"portfolio_id": "EQUITY_MR_PORTFOLIO"})
    _assert_unavailable(response, "not_published")
    assert reads == [("metadata", None), ("system_result", {"run_date": date(2026, 9, 22)})]
    assert _snapshot(dsn) == before


def test_unimplemented_equity_profile_is_rejected_without_futures_substitution(
    equity_configuration, client
):
    """Negative protocol candidate only; this is not an accepted equity manifest."""
    dsn, reads = equity_configuration
    candidate = {
        "publication_schema_version": 1, "profile": "live_portfolio_runner_equity",
        "authority": "inspection_only", "stream": "system",
        "identity": {
            "registry_id": "inc_meanrev", "registry_revision": 1,
            "engine_strategy_id": "LIVE_EQUITY_MEAN_REVERSION",
            "portfolio_id": "EQUITY_MR_PORTFOLIO", "run_date": "2026-09-22",
            "capture_id": "11111111-1111-4111-8111-111111111111",
            "publication_id": "11111111-1111-4111-8111-111111111111",
            "runtime_attempt_id": None, "producer_version": "synthetic-equity-negative-case",
            "control_mode": "uncontrolled",
        },
        "captured_at": "2026-09-22T16:00:00Z",
        "publication_recorded_at": "2026-09-22T16:01:00Z",
        "status": "unavailable", "reason": "projection_invalid",
        "supplied": None, "selected_trend": None,
        "consumption": {"status": "not_collected"},
    }
    _execute(dsn, "UPDATE trading.live_run_metadata SET portfolio_config=%s::jsonb "
             "WHERE strategy_id=%s AND portfolio_id=%s",
             (json.dumps({"parent_equity_knobs": "private-equity-parent-sentinel",
                          "config_inspection": candidate}),
              "LIVE_EQUITY_MEAN_REVERSION", "EQUITY_MR_PORTFOLIO"))
    before = _snapshot(dsn)
    _set_jwt_cookie(client, role="admin")
    response = client.get(CONFIG_PATH, query_string={"portfolio_id": "EQUITY_MR_PORTFOLIO"})
    _assert_unavailable(response, "unsupported_publication")
    metadata = reads[0][1]
    assert (metadata["strategy_id"], metadata["portfolio_id"], metadata["date"]) == (
        "LIVE_EQUITY_MEAN_REVERSION", "EQUITY_MR_PORTFOLIO", date(2026, 9, 22)
    )
    assert json.loads(metadata["child_text"]) == candidate
    assert reads[1] == ("system_result", {"run_date": date(2026, 9, 22)})
    assert _snapshot(dsn) == before


def test_equity_configuration_requires_jwt_and_current_internal_role(
    equity_configuration, client
):
    """Fails if unauthenticated or demoted users reach the configuration SQL."""
    dsn, reads = equity_configuration
    before = _snapshot(dsn)
    response = client.get(CONFIG_PATH, query_string={"portfolio_id": "EQUITY_MR_PORTFOLIO"})
    assert response.status_code == 401
    _set_jwt_cookie(client, role="admin", current_role="subscriber_individual")
    response = client.get(CONFIG_PATH, query_string={"portfolio_id": "EQUITY_MR_PORTFOLIO"})
    assert response.status_code == 403
    assert response.get_json() == {"error": "Insufficient permissions"}
    assert reads == []
    assert _snapshot(dsn) == before

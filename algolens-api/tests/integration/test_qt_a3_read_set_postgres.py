"""A3 source SELECTs against an owned disposable PostgreSQL schema."""

from pathlib import Path

import psycopg2
from psycopg2.extras import Json
import pytest

from tests.integration.conftest import claim_schema, require_test_dsn
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.infrastructure.portfolio.qt_read_set import internal_snapshot_digest
from algolens.infrastructure.portfolio.qt_read_set import capture_qt_read_set
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository


MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "003_qt_decision_workflow.sql"
REVISION = "30000000-0000-4000-8000-000000000001"
PUBLICATION = "10000000-0000-4000-8000-000000000001"


@pytest.fixture
def a3_db():
    dsn = require_test_dsn()
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            claim_schema(cursor)
            cursor.execute("CREATE SCHEMA IF NOT EXISTS auth")
            cursor.execute("CREATE TABLE IF NOT EXISTS auth.users (id bigint PRIMARY KEY)")
            cursor.execute("ALTER TABLE auth.users ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'general_member'")
            cursor.execute("INSERT INTO auth.users(id,role) VALUES (101,'general_member') "
                           "ON CONFLICT (id) DO UPDATE SET role=EXCLUDED.role")
            cursor.execute(MIGRATION.read_text(encoding="utf-8"))
            cursor.execute("""
                CREATE TABLE trading.strategy_registry (
                    id text PRIMARY KEY, strategy_type text NOT NULL,
                    portfolio_id text NOT NULL, is_active boolean NOT NULL,
                    lifecycle text NOT NULL, updated_at timestamptz NOT NULL);
                CREATE TABLE trading.strategy_book_memberships (
                    strategy_id text NOT NULL REFERENCES trading.strategy_registry(id), portfolio_id text NOT NULL,
                    PRIMARY KEY (strategy_id, portfolio_id));
                CREATE TABLE trading.positions (
                    portfolio_id text NOT NULL, strategy_id text NOT NULL,
                    strategy_name text NOT NULL, date date NOT NULL,
                    symbol text NOT NULL, portfolio_type text NOT NULL,
                    quantity numeric(20,8) NOT NULL,
                    average_price numeric(20,8) NOT NULL,
                    qt_proposal_revision uuid,
                    PRIMARY KEY (portfolio_id, strategy_id, strategy_name,
                                 date, symbol, portfolio_type));
                CREATE TABLE trading.qt_model_seed_publications (
                    publication_id uuid PRIMARY KEY, attempt_id uuid,
                    portfolio_id text NOT NULL, strategy_id text NOT NULL,
                    source_day date NOT NULL, publication_version bigint NOT NULL,
                    system_components jsonb NOT NULL, seed_digest text NOT NULL,
                    producer_version text NOT NULL, proposal_components jsonb,
                    proposal_manifest_digest text);
                CREATE TABLE trading.position_overrides (
                    id bigint PRIMARY KEY, user_id bigint, portfolio_id text, strategy_id text,
                    symbol text, source_app text, before_state jsonb,
                    after_state jsonb);
                CREATE TABLE trading.position_override_legacy_scopes (
                    override_id bigint PRIMARY KEY, portfolio_id text);
                CREATE TABLE trading.risk_limits (
                    id bigint PRIMARY KEY, strategy_id text NOT NULL,
                    portfolio_id text NOT NULL, limits jsonb NOT NULL,
                    published_at timestamptz NOT NULL);
            """)
            cursor.execute("""
                INSERT INTO trading.strategy_registry VALUES
                  ('ui-one', 'engine-one', 'BOOK', true, 'live', now());
                INSERT INTO trading.strategy_book_memberships VALUES ('ui-one', 'BOOK');
                INSERT INTO trading.qt_workflow_capabilities VALUES ('BOOK', true, 1);
                INSERT INTO trading.qt_action_grants
                  (user_id, capability, active, version) VALUES (101, 'qt_submit', true, 1);
                INSERT INTO trading.positions VALUES
                  ('BOOK','engine-one','ONE',(clock_timestamp() AT TIME ZONE 'UTC')::date,
                   'SYN','system',4,100,NULL),
                  ('BOOK','engine-one','ONE',(clock_timestamp() AT TIME ZONE 'UTC')::date,
                   'SYN','qt_proposal',4,100,%s),
                  ('BOOK','engine-one','ONE',(clock_timestamp() AT TIME ZONE 'UTC')::date,
                   'SYN','qt',0,100,NULL);
                INSERT INTO trading.risk_limits VALUES
                  (7,'engine-one','BOOK','{"max_net_leverage":"2"}',now());
            """, (REVISION,))
            cursor.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")
            day = cursor.fetchone()[0]
            system_key = {"portfolio_id": "BOOK", "strategy_id": "engine-one",
                          "strategy_name": "ONE", "date": day.isoformat(),
                          "symbol": "SYN", "portfolio_type": "system"}
            seed = [{"key": system_key, "quantity_exact": "4",
                     "average_price_exact": "100"}]
            manifest = [{"key": {**system_key, "portfolio_type": "qt_proposal"},
                         "quantity_exact": "4", "average_price_exact": "100",
                         "action": "inserted", "position_revision": REVISION,
                         "origin_publication_id": PUBLICATION}]
            cursor.execute("""
                INSERT INTO trading.qt_model_seed_publications
                (publication_id, portfolio_id, strategy_id, source_day,
                 publication_version, system_components, seed_digest,
                 producer_version, proposal_components, proposal_manifest_digest)
                VALUES (%s, 'BOOK', 'engine-one', %s, 1, %s, %s, 'synthetic', %s, %s)
            """, (PUBLICATION, day, Json(seed), qt_digest_v1({"seed_rows": seed}),
                  Json(manifest), internal_snapshot_digest(
                      "qt-proposal-manifest/v1", {"proposal_rows": manifest})))
    return dsn


def _read(dsn):
    repository = QtWorkflowRepository(lambda: psycopg2.connect(dsn))
    with repository.transaction("BOOK", 101) as transaction:
        transaction.lock_authorities([101])
        transaction.lock_registries(["ui-one"])
        transaction.lock_books(["BOOK"])
        transaction.lock_mutable()
        return capture_qt_read_set(transaction.read_current_facts())


def test_actual_book_selects_include_zero_token_and_config_changes(a3_db):
    first = _read(a3_db)
    assert first.payload["provenance"]["status"] == "ready"
    assert first.payload["source_rows"][0]["position_revision"] == REVISION
    assert first.payload["saved_rows"][0]["quantity_exact"] == "0"
    assert first.payload["risk_inventory"][0]["id"] == 7
    assert first.available is False
    with psycopg2.connect(a3_db) as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE trading.positions SET quantity = 1 "
                           "WHERE portfolio_id = 'BOOK' AND portfolio_type = 'qt'")
            cursor.execute("UPDATE trading.qt_action_grants SET version = 2 "
                           "WHERE user_id = 101 AND capability = 'qt_submit'")
    later = _read(a3_db)
    assert later.payload["saved_rows"][0]["quantity_exact"] == "1"
    assert later.payload["grants"][0]["version"] == 2
    assert later.digest != first.digest


def test_unpublished_physical_system_component_blocks_model_provenance(a3_db):
    before = _read(a3_db)
    assert before.payload["provenance"]["status"] == "ready"
    with psycopg2.connect(a3_db) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO trading.positions
                (portfolio_id, strategy_id, strategy_name, date, symbol,
                 portfolio_type, quantity, average_price)
                VALUES ('BOOK', 'engine-two', 'TWO',
                        (clock_timestamp() AT TIME ZONE 'UTC')::date,
                        'SYN', 'system', 0, 200)
            """)
    after = _read(a3_db)
    assert after.payload["provenance"]["status"] == "provenance_unresolved"
    assert len(after.payload["system_rows"]) == 2
    assert after.digest != before.digest

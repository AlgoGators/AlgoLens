"""GET /proposal resolves instrument type from the book's registered
strategy's asset_class when the catalog has no row -- production shape.

Production's metadata.contract_metadata holds futures only. Before this fix,
any real equity book with positions 409'd on GET /proposal: see
DIAGNOSIS-422-1.md. This never invents an asset class from a strategy's
name -- it reads the asset_class column an operator explicitly set (migration
007; see PRODUCTION-PREREQUISITE.md), read under the same registry lock the
proposal already takes.
"""

import psycopg2
import pytest

from algolens.infrastructure.config.dependencies import create_qt_decision_read_service
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from tests.integration.test_qt_a3_read_set_postgres import a3_db  # noqa: F401  (fixture)


def _query(dsn, sql, params=()):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else None


@pytest.fixture
def futures_only_catalog_db(a3_db):
    """Production-shaped: contract_metadata knows futures only. SYN, the
    symbol a3_db already seeded as a live equity-shaped MODEL position, has
    no row here -- exactly the production gap in DIAGNOSIS-422-1.md."""
    _query(a3_db, '''CREATE SCHEMA IF NOT EXISTS metadata;
        CREATE TABLE IF NOT EXISTS metadata.contract_metadata (
            "Databento Symbol" text, "IB Symbol" text, "Asset Type" text);
        TRUNCATE metadata.contract_metadata;
        INSERT INTO metadata.contract_metadata VALUES ('ES', 'ES', 'FUTURE');''')
    return a3_db


def test_futures_only_catalog_falls_back_to_the_registered_strategys_asset_class(futures_only_catalog_db):
    _query(futures_only_catalog_db, "UPDATE trading.strategy_registry SET asset_class = 'EQUITY' WHERE id = 'ui-one'")
    service = create_qt_decision_read_service(connection_factory=lambda: psycopg2.connect(futures_only_catalog_db))
    proposal = service.get_proposal("BOOK", 101).to_wire()
    seed = next(row for row in proposal["seed_rows"] if row["key"]["symbol"] == "SYN")
    assert seed["asset_type"] == "EQUITY"
    saved = next(row for row in proposal["saved_qt_rows"] if row["key"]["symbol"] == "SYN")
    assert saved["asset_type"] == "EQUITY"


def test_null_asset_class_still_fails_closed(futures_only_catalog_db):
    # a3_db's registry row already has asset_class NULL -- the pre-operator,
    # freshly-migrated state.
    service = create_qt_decision_read_service(connection_factory=lambda: psycopg2.connect(futures_only_catalog_db))
    with pytest.raises(QtWorkflowError) as blocked:
        service.get_proposal("BOOK", 101)
    assert blocked.value.code == "draft_identity_unresolved"


def test_conflicting_catalog_and_registry_still_fails_closed(futures_only_catalog_db):
    _query(futures_only_catalog_db, "INSERT INTO metadata.contract_metadata VALUES ('SYN', 'SYN', 'FUTURE')")
    _query(futures_only_catalog_db, "UPDATE trading.strategy_registry SET asset_class = 'EQUITY' WHERE id = 'ui-one'")
    service = create_qt_decision_read_service(connection_factory=lambda: psycopg2.connect(futures_only_catalog_db))
    with pytest.raises(QtWorkflowError) as blocked:
        service.get_proposal("BOOK", 101)
    assert blocked.value.code == "draft_identity_unresolved"

"""Every QT read/write path -- not only GET /proposal -- must resolve an
equity book's instrument type from the registry when the catalog has no row.

Independent review (INDEPENDENT-REVIEW-1.md) found GET /draft, PUT /draft and
POST /qt-previews still 409 draft_identity_unresolved for the identical
symbol, because only qt_decision_read.py's get_proposal threaded
registry_asset_class through. This walks the real routes' services
(algolens/adapters/http/qt_workflow.py: GET proposal and GET draft go through
QtDecisionReadService; PUT draft and POST preview go through QtWorkflowService)
end to end for one equity book and asserts none of them ever raises
draft_identity_unresolved.
"""

from pathlib import Path

import psycopg2
import pytest

from algolens.infrastructure.config.dependencies import create_qt_decision_read_service, create_qt_workflow_service
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from tests.integration.test_qt_a3_read_set_postgres import a3_db  # noqa: F401  (fixture)

GOVERNED_SOURCES_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "004_qt_governed_sources.sql"


def _query(dsn, sql, params=()):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else None


@pytest.fixture
def futures_only_catalog_db(a3_db):
    """Production-shaped: contract_metadata knows futures only; SYN is absent.
    Governed-sources tables (migration 004) exist so POST preview's input
    loader fails closed with 'preview_unavailable', not a missing-table
    error -- no compiled evaluator is configured or needed for this test."""
    _query(a3_db, GOVERNED_SOURCES_MIGRATION.read_text(encoding="utf-8"))
    _query(a3_db, '''CREATE SCHEMA IF NOT EXISTS metadata;
        CREATE TABLE IF NOT EXISTS metadata.contract_metadata (
            "Databento Symbol" text, "IB Symbol" text, "Asset Type" text);
        TRUNCATE metadata.contract_metadata;
        INSERT INTO metadata.contract_metadata VALUES ('ES', 'ES', 'FUTURE');''')
    return a3_db


def test_equity_book_never_409s_across_proposal_draft_and_preview(futures_only_catalog_db):
    _query(futures_only_catalog_db, "UPDATE trading.strategy_registry SET asset_class = 'EQUITY' WHERE id = 'ui-one'")
    dsn = futures_only_catalog_db
    read = create_qt_decision_read_service(connection_factory=lambda: psycopg2.connect(dsn))
    workflow = create_qt_workflow_service(connection_factory=lambda: psycopg2.connect(dsn))

    proposal = read.get_proposal("BOOK", 101).to_wire()
    seed = next(row for row in proposal["seed_rows"] if row["key"]["symbol"] == "SYN")
    assert seed["asset_type"] == "EQUITY"

    initial = read.get_draft("BOOK", 101).to_wire()  # the real GET /draft route
    editable = next(row for row in initial["selection_rows"] if row["editable"])
    assert editable["asset_type"] == "EQUITY"

    saved = workflow.save_draft("BOOK", 101, {  # the real PUT /draft route
        "expected_source_digest": initial["source_digest"],
        "expected_provenance_digest": initial["provenance_digest"],
        "expected_draft_revision": 0,
        "idempotency_key": "00000000-0000-4000-8000-000000000201",
        "selection_rows": [{"key": editable["key"], "quantity_exact": "4"}],
    }).to_wire()
    assert saved["selection_rows"][0]["asset_type"] == "EQUITY"

    preview = workflow.create_preview(101, {  # the real POST /qt-previews route
        "book_id": "BOOK", "draft_id": saved["draft_id"], "draft_revision": saved["draft_revision"],
        "draft_digest": saved["draft_digest"], "expected_source_digest": saved["source_digest"],
        "expected_provenance_digest": saved["provenance_digest"],
        "idempotency_key": "00000000-0000-4000-8000-000000000202",
    }).to_wire()
    # Not necessarily confirmable (no evaluator bundle is configured here) --
    # the point is that reaching this response never raised
    # draft_identity_unresolved for SYN.
    assert "draft_identity_unresolved" not in preview.get("unavailable_reasons", [])


def test_null_asset_class_still_fails_closed_on_get_draft(futures_only_catalog_db):
    # a3_db's registry row already has asset_class NULL -- the pre-operator,
    # freshly-migrated state.
    read = create_qt_decision_read_service(connection_factory=lambda: psycopg2.connect(futures_only_catalog_db))
    with pytest.raises(QtWorkflowError) as blocked:
        read.get_draft("BOOK", 101)
    assert blocked.value.code == "draft_identity_unresolved"

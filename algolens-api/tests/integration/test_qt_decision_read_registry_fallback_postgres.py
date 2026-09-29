"""F2 Postgres proof: GET /decision's can_approve for a pending_override
decision must use the same per-key registry fallback get_proposal/get_draft
already thread through -- or an equity book the catalog does not know can
never be approved through the UI (QtDecisionStatus.tsx only shows the
approve button when can_approve is true).

Reuses the a7 approval flow's pending_override fixture, then removes the
catalog's only row for the book's symbol (simulating the production gap:
metadata.contract_metadata holds futures only) before reading the decision,
so `_validate_preview_evidence`'s instrument-type resolution depends
entirely on trading.strategy_registry.asset_class. The catalog is not part of
the read set (only registry ids/updated_at, memberships and the governed
inputs are), and updating asset_class does not touch updated_at, so the
stored preview's read-set digest still matches.

PLAN15 fix. The reader must be built WITH the evaluator bundle directory,
exactly as test_qt_a8_http_postgres.http_harness builds it
(`evaluator_bundle_directory=service.evaluator_bundle_directory`):
QtDecisionReadQueries.enabled_prerequisites (qt_decision_read_repository.py)
returns False when the directory is None, and can_approve requires it. Built
without it, can_approve is False for EVERY reason, so the earlier version of
the positive case failed and the NULL control passed for the wrong reason.
The control now proves its own cause: it stays False while asset_class is
NULL and flips to True once the class is EQUITY, with nothing else changed.

Written per this task's PostgreSQL-integration-lane convention; the
integration lane runs it against an owned database.
"""
import psycopg2

from algolens.infrastructure.config.dependencies import create_qt_decision_read_service
from tests.integration.test_qt_a3_read_set_postgres import a3_db  # noqa: F401  (fixture)
from tests.integration.test_qt_preview_evaluator import preview_db, query  # noqa: F401  (fixture)
from tests.integration.test_qt_a7_approval_postgres import pending, approval_request


def _catalog_silent_for_syn(dsn):
    query(dsn, "DELETE FROM metadata.contract_metadata WHERE \"Databento Symbol\" = 'SYN'")


def _reader(dsn, service):
    # As http_harness builds it: without the bundle directory
    # enabled_prerequisites() is False and can_approve is always False.
    return create_qt_decision_read_service(
        connection_factory=lambda: psycopg2.connect(dsn),
        evaluator_bundle_directory=service.evaluator_bundle_directory)


def test_equity_book_not_in_the_catalog_still_shows_can_approve_true(preview_db):
    service, decision = pending(preview_db)
    _catalog_silent_for_syn(preview_db)
    query(preview_db, "UPDATE trading.strategy_registry SET asset_class = 'EQUITY' WHERE id = 'ui-one'")
    reader = _reader(preview_db, service)
    # 202 ('john_riley') is an eligible second approver in a7's `pending()`
    # allowlist, distinct from the 101 submitter -- exactly the reader used
    # by the frontend's QtDecisionStatus approve button.
    read = reader.get_decision(decision["decision_id"], 202).to_wire()
    assert read["status"] == "pending_override"
    assert read["can_approve"] is True
    # The real write path (which already threads the registry fallback --
    # INDEPENDENT-REVIEW-1's fix) then approves: the requester 101 counts
    # explicitly, the eligible second approver 202 promotes. The read-side
    # flag is therefore not a false positive, and it stays true for 202 after
    # 101 has approved.
    first = service.approve_override(decision["request_id"], 101, approval_request()).to_wire()
    assert first["status"] == "pending_override" and first["approvals_count"] == 1
    assert reader.get_decision(decision["decision_id"], 202).to_wire()["can_approve"] is True
    second = service.approve_override(decision["request_id"], 202, approval_request()).to_wire()
    assert second["status"] == "confirmed_decision" and second["approvals_count"] == 2


def test_null_asset_class_still_shows_can_approve_false(preview_db):
    service, decision = pending(preview_db)
    _catalog_silent_for_syn(preview_db)
    # a3_db's registry row has asset_class NULL -- the freshly-migrated state.
    # Same reader as the positive case (bundle directory present), so the only
    # thing that can make can_approve False here is the missing class.
    reader = _reader(preview_db, service)
    blocked = reader.get_decision(decision["decision_id"], 202).to_wire()
    assert blocked["status"] == "pending_override"
    assert blocked["can_approve"] is False
    assert blocked["report_ready"] is False
    # Proof that the class is the cause: change ONLY asset_class and the very
    # same decision, reader and approver flip to True.
    query(preview_db, "UPDATE trading.strategy_registry SET asset_class = 'EQUITY' WHERE id = 'ui-one'")
    allowed = reader.get_decision(decision["decision_id"], 202).to_wire()
    assert allowed["can_approve"] is True

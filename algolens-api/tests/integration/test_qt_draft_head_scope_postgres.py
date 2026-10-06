"""Real saved-draft SQL identity and foreign-book isolation on owned PostgreSQL."""
from datetime import date
from uuid import uuid4
import psycopg2
from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from tests.integration.test_qt_a4_draft_postgres import draft_db,_query
from tests.integration.test_qt_a3_read_set_postgres import a3_db


def test_saved_draft_repository_retains_actual_book_and_foreign_book_cannot_read_it(draft_db):
    repository=QtWorkflowRepository(lambda:psycopg2.connect(draft_db))
    service=create_qt_workflow_service(repository)
    absent=service.get_draft('BOOK',101).to_wire()
    key=next(row['key'] for row in absent['selection_rows'] if row['editable'])
    saved=service.save_draft('BOOK',101,dict(expected_source_digest=absent['source_digest'],
        expected_provenance_digest=absent['provenance_digest'],expected_draft_revision=0,
        idempotency_key=str(uuid4()),rationale='Exercise draft-head scope.',
        selection_rows=[dict(key=key,quantity_exact='2')])).to_wire()
    before=_query(draft_db,'SELECT to_jsonb(d)::text FROM trading.qt_drafts d ORDER BY draft_id')
    day=date.fromisoformat(saved['source_day'])
    for book in ('BOOK','FOREIGN_BOOK'):
        with repository.transaction(book,101) as tx:
            tx.lock_authorities([101]);tx.lock_registries(tx.registry_ids_for_book())
            tx.lock_books([book]);tx.lock_mutable(source_day=day)
            head=tx.get_draft_head(day)
            if book=='BOOK':
                assert head['book_id']==book
                assert str(head['draft_id'])==saved['draft_id']
                assert head['revision']==saved['draft_revision']
                assert head['draft_digest']==saved['draft_digest']
            else:assert head is None
    assert _query(draft_db,'SELECT to_jsonb(d)::text FROM trading.qt_drafts d ORDER BY draft_id')==before

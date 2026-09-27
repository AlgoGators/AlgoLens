"""Actual repository SQL projection; cursor operand is a declared driver seam.

The retained owned-PG diagnostic proves this omission on actual storage. These
controls prevent a fake transaction containing unselected book_id masking it.
"""
from datetime import date
import re
from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction


class ProjectionCursor:
    def __init__(self,stored):self.stored=stored;self.calls=[];self.row=None
    def execute(self,sql,params):
        self.calls.append((sql,params))
        # Model only the driver result shape of the actual SELECT projection.
        columns=re.findall(r'\bd\.([a-z_]+)',sql.split('FROM',1)[0])
        self.row=None if self.stored is None else {name:self.stored[name] for name in columns}
    def fetchone(self):return self.row


def transaction(stored,book='BOOK'):
    cursor=ProjectionCursor(stored)
    tx=QtTransaction(cursor,book,101)
    tx._stage=4  # Ordered-lock protocol is independently covered by its tests.
    return tx,cursor


def test_actual_repository_projection_retains_stored_book_identity():
    stored=dict(book_id='BOOK',draft_id='draft',revision=7,source_digest='a'*64,
        provenance_digest='b'*64,draft_digest='c'*64,selection_payload={'selection_rows':[]},
        model_publication_id='publication',model_publication_version=3,seed_digest='d'*64)
    tx,cursor=transaction(stored)
    head=tx.get_draft_head(date(2026,9,27))
    assert head==stored,'successor must receive actual stored book identity, not a fake-port extra'
    assert cursor.calls[0][1]==('BOOK',date(2026,9,27))
    sql=cursor.calls[0][0]
    assert 'd.book_id = h.book_id' in sql and 'h.book_id = %s AND h.source_day = %s' in sql


def test_actual_repository_absent_head_stays_none_and_foreign_book_is_scoped():
    tx,cursor=transaction(None,'OTHER_BOOK')
    assert tx.get_draft_head(date(2026,9,27)) is None
    assert cursor.calls[0][1]==('OTHER_BOOK',date(2026,9,27))

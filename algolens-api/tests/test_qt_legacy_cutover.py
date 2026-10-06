"""Only explicit disabled capability permits the existing position writer."""
import pytest
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError


class Cursor:
    def __init__(self, row): self.row, self.queries = row, []
    def execute(self, query, args): self.queries.append((query, args))
    def fetchone(self): return self.row


@pytest.mark.parametrize('row,code', [(None,'workflow_unavailable'), ({'enabled':True,'version':1},'preview_required'),
    ({'enabled':False,'version':0},'workflow_unavailable'), ({'enabled':None,'version':1},'workflow_unavailable')])
def test_missing_enabled_or_uncertain_capability_refuses_before_writes(row, code):
    from algolens.infrastructure.portfolio import qt_publication_proof as module
    assert hasattr(module, 'require_legacy_qt_disabled'), 'A8 transaction cutover gate is missing'
    cursor = Cursor(row)
    with pytest.raises(QtWorkflowError) as exc: module.require_legacy_qt_disabled(cursor, 'BOOK')
    assert exc.value.code == code
    assert all('INSERT' not in sql and 'UPDATE' not in sql for sql, _ in cursor.queries)


def test_explicit_versioned_disabled_admits_legacy_tuple_cursor():
    from algolens.infrastructure.portfolio import qt_publication_proof as module
    assert hasattr(module, 'require_legacy_qt_disabled'), 'A8 transaction cutover gate is missing'
    module.require_legacy_qt_disabled(Cursor((False, 1)), 'BOOK')

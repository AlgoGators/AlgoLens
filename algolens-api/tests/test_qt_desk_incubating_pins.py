"""N5 (d): model publication admits incubating strategies; the QT desk stays live-only.

Every test calls the real AlgoLens desk code with an incubating owner (active or not) and a live control:
  - qt_workflow.QtWorkflowService._preview_access (the preview rule for editable rows);
  - qt_workflow.QtWorkflowService._validate_catalog (the governed-catalog authority rule);
  - qt_decision_read.QtDecisionReadService._access (desk read access to a book).
The save-draft owner rule (qt_workflow.py:274) is the same inline filter; it is not called here.
"""
import pytest

from algolens.application.portfolio.qt_decision_read import QtDecisionReadService
from algolens.application.portfolio.qt_workflow import QtWorkflowService
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtKey, QtSelectionRow

BOOK = 'SYNTHETIC_BOOK'
KEY = {'portfolio_id': BOOK, 'strategy_id': 'LIVE_EQUITY_MEAN_REVERSION', 'strategy_name': 'EQUITY_MEAN_REVERSION',
       'date': '2026-09-22', 'symbol': 'SYN', 'portfolio_type': 'qt_proposal'}
CLOSED = [('incubating', True), ('incubating', False), ('retired', True)]


def facts(lifecycle, active=True):
    return {'registry': [{'id': 'inc_meanrev', 'strategy_type': 'LIVE_EQUITY_MEAN_REVERSION', 'portfolio_id': BOOK,
                          'is_active': active, 'lifecycle': lifecycle, 'updated_at': '2026-09-22T11:00:00Z'}],
            'memberships': [{'strategy_id': 'inc_meanrev', 'portfolio_id': BOOK}]}


def preview(lifecycle, active=True):
    QtWorkflowService._preview_access(facts(lifecycle, active), {'selection_rows': [{'editable': True, 'key': KEY}]})


def test_live_owner_is_desk_editable_control():
    preview('live')


@pytest.mark.parametrize('lifecycle,active', CLOSED)
def test_incubating_owner_is_not_desk_editable(lifecycle, active):
    with pytest.raises(QtWorkflowError) as refused:
        preview(lifecycle, active)
    assert refused.value.code == 'authorization_changed'


class _Catalog:
    instrument_catalog = [{'key': KEY, 'editable': True, 'instrument_type': 'EQUITY'}]


class _CatalogTx:
    @staticmethod
    def resolve_instrument_types(expected, registry_kind):
        return {key: 'EQUITY' for key in expected}


def validate_catalog(lifecycle, active=True):
    service = object.__new__(QtWorkflowService)  # _validate_catalog reads no service state
    row = QtSelectionRow(key=QtKey(**KEY), quantity_exact='3', basis_status='preserved_source', average_price_exact='100',
                         asset_type='EQUITY', editable=True, origin='qt_draft')
    service._validate_catalog(_CatalogTx(), _Catalog(), [row], facts(lifecycle, active))


def test_live_owner_passes_the_governed_catalog_rule_control():
    validate_catalog('live')


@pytest.mark.parametrize('lifecycle,active', CLOSED)
def test_incubating_owner_fails_the_governed_catalog_rule(lifecycle, active):
    with pytest.raises(QtWorkflowError) as refused:
        validate_catalog(lifecycle, active)
    assert refused.value.code == 'preview_unavailable'


class _Tx:
    book_id = BOOK

    @staticmethod
    def approval_authority(actor):
        return {'grants': [{'user_id': actor, 'capability': 'qt_submit', 'active': True}]}


def access(lifecycle, active=True):
    QtDecisionReadService._access(_Tx(), [{'id': '101', 'role': 'admin'}], facts(lifecycle, active),
                                  ('inc_meanrev',), '101', require_desk_grant=False)


def test_live_owner_grants_desk_read_access_control():
    access('live')


@pytest.mark.parametrize('lifecycle,active', CLOSED)
def test_incubating_owner_grants_no_desk_read_access(lifecycle, active):
    with pytest.raises(QtWorkflowError) as refused:
        access(lifecycle, active)
    assert refused.value.code == 'authorization_changed'

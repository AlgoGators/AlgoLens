"""Pure tests: QtTransaction.resolve_instrument_types resolves PER KEY from
the key's own registry row, never book-wide (F1's actual wiring point, one
layer below the pure domain-function tests in
test_qt_instrument_type_resolution.py).

A fake cursor stands in for metadata.contract_metadata: no database.
"""
from collections.abc import Mapping

import pytest

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_instrument_type_resolution import registry_asset_class
from algolens.domain.portfolio.qt_workflow_models import QtKey
from algolens.infrastructure.portfolio.qt_workflow_repository import QtTransaction


class _FakeCatalogCursor:
    """Mimics metadata.contract_metadata: symbol -> 'Asset Type', or absent."""

    def __init__(self, catalog):
        self._catalog = catalog
        self._pending = None

    def execute(self, sql, params):
        symbol = params[0]
        self._pending = self._catalog.get(symbol)

    def fetchall(self):
        if self._pending is None:
            return []
        return [{"asset_type": self._pending}]


def _tx(catalog):
    tx = QtTransaction(_FakeCatalogCursor(catalog), "BOOK", 101)
    tx._stage = 4  # bypass the ordered-lock stages: pure white-box unit test.
    return tx


def _key(strategy_id, symbol, strategy_name="NAME"):
    return QtKey("BOOK", strategy_id, strategy_name, "2026-09-25", symbol, "qt_proposal")


# Two registered strategies reachable for one book: engine-null declares no
# asset_class at all, engine-equity declares EQUITY. Neither symbol (SYN) is
# in the catalog.
TWO_STRATEGY_REGISTRIES = (
    {"id": "registry-1", "strategy_type": "engine-null", "portfolio_id": "BOOK",
     "is_active": True, "lifecycle": "live", "asset_class": None},
    {"id": "registry-2", "strategy_type": "engine-equity", "portfolio_id": "BOOK",
     "is_active": True, "lifecycle": "live", "asset_class": "EQUITY"},
)


def test_a_null_siblings_key_does_not_inherit_the_declared_siblings_class():
    # This is the exact F1 regression: before the fix, registry_asset_class
    # unioned the book's registry rows into one scalar, so engine-null's own
    # SYN key silently resolved EQUITY from its sibling. Now it must fail
    # closed instead.
    tx = _tx(catalog={})  # SYN unknown to the catalog either way
    fallback = registry_asset_class(TWO_STRATEGY_REGISTRIES)
    with pytest.raises(QtWorkflowError) as blocked:
        tx.resolve_instrument_types([_key("engine-null", "SYN")], fallback)
    assert blocked.value.code == "draft_identity_unresolved"


def test_the_declared_siblings_own_key_still_resolves():
    tx = _tx(catalog={})
    fallback = registry_asset_class(TWO_STRATEGY_REGISTRIES)
    resolved = tx.resolve_instrument_types([_key("engine-equity", "SYN")], fallback)
    assert resolved == {_key("engine-equity", "SYN"): "EQUITY"}


def test_a_null_siblings_own_catalog_known_futures_symbol_still_resolves():
    # The fail-OPEN scenario F1 describes: a catalog-known futures symbol
    # belonging to the NULL strategy must resolve FUTURE from the catalog,
    # untouched by the sibling's EQUITY declaration -- and the whole-number
    # FUTURE check downstream still applies to it.
    tx = _tx(catalog={"ES": "FUTURE"})
    fallback = registry_asset_class(TWO_STRATEGY_REGISTRIES)
    resolved = tx.resolve_instrument_types([_key("engine-null", "ES")], fallback)
    assert resolved == {_key("engine-null", "ES"): "FUTURE"}


def test_each_key_in_a_mixed_batch_resolves_from_its_own_strategy_only():
    tx = _tx(catalog={})
    fallback = registry_asset_class(TWO_STRATEGY_REGISTRIES)
    keys = [_key("engine-equity", "SYN"), _key("engine-equity", "SYN2")]
    resolved = tx.resolve_instrument_types(keys, fallback)
    assert resolved == {key: "EQUITY" for key in keys}


def test_catalog_vs_registry_conflict_for_the_keys_own_strategy_fails_closed():
    tx = _tx(catalog={"SYN": "FUTURE"})
    fallback = registry_asset_class(TWO_STRATEGY_REGISTRIES)
    with pytest.raises(QtWorkflowError) as blocked:
        tx.resolve_instrument_types([_key("engine-equity", "SYN")], fallback)
    assert blocked.value.code == "draft_identity_unresolved"


def test_missing_registry_row_for_the_keys_strategy_fails_closed():
    tx = _tx(catalog={})
    fallback = registry_asset_class(TWO_STRATEGY_REGISTRIES)
    with pytest.raises(QtWorkflowError) as blocked:
        tx.resolve_instrument_types([_key("engine-unknown", "SYN")], fallback)
    assert blocked.value.code == "draft_identity_unresolved"


def test_none_fallback_keeps_prior_catalog_only_behavior():
    tx = _tx(catalog={"ES": "FUTURE"})
    assert tx.resolve_instrument_types([_key("engine-null", "ES")]) == {_key("engine-null", "ES"): "FUTURE"}
    with pytest.raises(QtWorkflowError):
        tx.resolve_instrument_types([_key("engine-null", "SYN")])


def test_non_mapping_fallback_is_treated_as_no_fallback():
    tx = _tx(catalog={"ES": "FUTURE"})
    assert tx.resolve_instrument_types([_key("engine-null", "ES")], "EQUITY") == {_key("engine-null", "ES"): "FUTURE"}
    with pytest.raises(QtWorkflowError):
        tx.resolve_instrument_types([_key("engine-null", "SYN")], "EQUITY")


def test_registry_asset_class_result_is_a_mapping_not_a_scalar():
    # Guards the F1 API shape change itself: a book-wide scalar can no
    # longer be handed to resolve_instrument_types as a correct fallback.
    fallback = registry_asset_class(TWO_STRATEGY_REGISTRIES)
    assert isinstance(fallback, Mapping)
    assert fallback == {"engine-equity": "EQUITY"}


# --- single-reachable-row semantics at the wiring layer (F1 revision 3) ----

def test_a_single_retired_strategy_type_still_resolves_at_this_layer():
    # Revision 2 ("...has_no_fallback_at_this_layer") refused this: a
    # single retired row was treated as having no owner at all. Revision 3
    # matches _validate_catalog's actual type gate (exactly one reachable
    # row, any status) -- a single retired row is its strategy_type's own,
    # unambiguous declaration and resolves normally.
    registries = (
        {"id": "registry-1", "strategy_type": "engine-retired", "portfolio_id": "BOOK",
         "is_active": False, "lifecycle": "retired", "asset_class": "EQUITY"},
    )
    tx = _tx(catalog={})
    fallback = registry_asset_class(registries)
    resolved = tx.resolve_instrument_types([_key("engine-retired", "SYN")], fallback)
    assert resolved == {_key("engine-retired", "SYN"): "EQUITY"}


def test_two_agreeing_active_live_owners_same_type_has_no_fallback_at_this_layer():
    # Unchanged by revision 3: two reachable rows for one strategy_type is
    # ambiguous ownership regardless of status or agreement.
    registries = (
        {"id": "registry-1", "strategy_type": "engine-dup", "portfolio_id": "BOOK",
         "is_active": True, "lifecycle": "live", "asset_class": "EQUITY"},
        {"id": "registry-2", "strategy_type": "engine-dup", "portfolio_id": "BOOK",
         "is_active": True, "lifecycle": "live", "asset_class": "EQUITY"},
    )
    tx = _tx(catalog={})
    fallback = registry_asset_class(registries)
    with pytest.raises(QtWorkflowError) as blocked:
        tx.resolve_instrument_types([_key("engine-dup", "SYN")], fallback)
    assert blocked.value.code == "draft_identity_unresolved"


def test_live_and_old_distinct_strategy_types_both_resolve_in_one_batch():
    # The independent review's own regression shape, at the wiring layer:
    # a batch with one key under an active+live strategy (LIVE) and one key
    # under a DIFFERENT strategy_type with a single retired row (OLD).
    # Under revision 2 the OLD key raised, which (since
    # resolve_instrument_types raises on the first unresolved key) failed
    # the WHOLE batch -- including LIVE's own key -- with
    # draft_identity_unresolved.
    registries = (
        {"id": "registry-live", "strategy_type": "LIVE", "portfolio_id": "BOOK",
         "is_active": True, "lifecycle": "live", "asset_class": "EQUITY"},
        {"id": "registry-old", "strategy_type": "OLD", "portfolio_id": "BOOK",
         "is_active": False, "lifecycle": "retired", "asset_class": "EQUITY"},
    )
    tx = _tx(catalog={})  # neither AAPL nor MSFT is in the catalog
    fallback = registry_asset_class(registries)
    keys = [_key("LIVE", "AAPL"), _key("OLD", "MSFT")]
    resolved = tx.resolve_instrument_types(keys, fallback)
    assert resolved == {_key("LIVE", "AAPL"): "EQUITY", _key("OLD", "MSFT"): "EQUITY"}

"""Pure tests for the catalog/registry instrument-type resolver.

No database. Exercises the user's decided precedence: the catalog wins
whenever it has a row; the key's OWN registered strategy's asset_class is
consulted only when the catalog is silent, resolved PER KEY from that key's
own registry row only -- joined on strategy_type (what a key's strategy_id
actually names; NOT the registry row's own 'id' primary key) -- never unioned
or inherited from a sibling strategy in the same book.

A strategy_type resolves only when EXACTLY ONE reachable registry row has
that strategy_type -- any is_active or lifecycle -- and that row declares a
recognized class. This is `qt_workflow.py._validate_catalog`'s own type
gate (`len(owners) != 1` refuses regardless of status; active+live is
required only when the row being checked is editable, a separate concern
`_preview_access`/`save_draft`/`_validate_catalog` enforce on their own,
never duplicated here). A disagreement between the catalog and that row, a
strategy_type with no reachable row at all, two or more reachable rows
(even if they agree, and regardless of is_active/lifecycle), or that one
row's own NULL/unrecognized asset_class, all fail closed with the same
refusal. A single retired or incubating row (migration 002's real
lifecycle values) resolves normally: an instrument's type does not depend
on whether its strategy is currently live (independent review 1, revision
2's finding 1 -- revision 1's stricter "active+live owner" rule wrongly
refused a legitimate single retired/incubating owner).
"""

import pytest

from algolens.domain.portfolio.position_edit import PositionValidationError
from algolens.domain.portfolio.qt_instrument_type_resolution import (
    registry_asset_class,
    resolve_asset_type,
)


def _row(asset_class=None, strategy_type="engine-one", id="registry-1",
         is_active=True, lifecycle="live", **extra):
    # Mirrors QtTransaction.lock_registries' shape: 'id' is the registry
    # row's own primary key; 'strategy_type' is the engine identity a
    # position/draft key's strategy_id actually equals -- the real join
    # field. Defaults to a single active+live owner row, matching the
    # normal case; tests that need an inactive/non-live/duplicate shape
    # override is_active/lifecycle/id explicitly.
    return {"id": id, "strategy_type": strategy_type, "portfolio_id": "BOOK",
            "is_active": is_active, "lifecycle": lifecycle, "asset_class": asset_class, **extra}


# --- resolve_asset_type: catalog vs. registry precedence --------------------

def test_catalog_only_resolves_from_catalog():
    assert resolve_asset_type("FUTURE", None) == "FUTURE"


def test_registry_only_resolves_equity_from_registry():
    assert resolve_asset_type(None, "EQUITY") == "EQUITY"


def test_conflict_between_catalog_and_registry_refuses():
    with pytest.raises(PositionValidationError) as excinfo:
        resolve_asset_type("FUTURE", "EQUITY")
    assert excinfo.value.code == "instrument_type_conflict"


def test_neither_authority_has_an_answer_refuses():
    with pytest.raises(PositionValidationError) as excinfo:
        resolve_asset_type(None, None)
    assert excinfo.value.code == "instrument_type_unavailable"


def test_future_in_both_agreeing_resolves():
    assert resolve_asset_type("FUTURE", "FUTURE") == "FUTURE"


def test_catalog_still_wins_when_registry_agrees_too():
    assert resolve_asset_type("EQUITY", "EQUITY") == "EQUITY"


# --- registry_asset_class: PER-KEY resolution, keyed by strategy_type -------

def test_single_registered_strategy_with_equity_resolves():
    assert registry_asset_class([_row("EQUITY")]) == {"engine-one": "EQUITY"}


def test_valid_single_active_live_owner_row_resolves():
    # The coordinator's explicit "valid single-row case": one reachable
    # row (here, active and live -- the common case), one recognized
    # class -- must resolve.
    row = _row("EQUITY", strategy_type="engine-valid", id="registry-1", is_active=True, lifecycle="live")
    assert registry_asset_class([row]) == {"engine-valid": "EQUITY"}


def test_normalizes_recognized_spellings():
    assert registry_asset_class([_row("FUT")]) == {"engine-one": "FUTURE"}


def test_strategy_with_no_declared_asset_class_has_no_entry():
    assert registry_asset_class([_row(None)]) == {}


def test_several_strategies_with_the_same_class_each_resolve_independently():
    mapping = registry_asset_class([
        _row("EQUITY", strategy_type="engine-one", id="registry-1"),
        _row("EQUITY", strategy_type="engine-two", id="registry-2"),
    ])
    assert mapping == {"engine-one": "EQUITY", "engine-two": "EQUITY"}


def test_two_strategies_with_different_classes_in_one_book_each_key_gets_its_own():
    # This is the F1 fix: a book reaching two registered strategies that
    # disagree must not block (or cross-pollinate) either strategy's own
    # keys -- each strategy_type resolves from its own row only.
    mapping = registry_asset_class([
        _row("EQUITY", strategy_type="engine-one", id="registry-1"),
        _row("FUTURE", strategy_type="engine-two", id="registry-2"),
    ])
    assert mapping == {"engine-one": "EQUITY", "engine-two": "FUTURE"}
    assert resolve_asset_type(None, mapping.get("engine-one")) == "EQUITY"
    assert resolve_asset_type(None, mapping.get("engine-two")) == "FUTURE"


def test_a_null_sibling_does_not_block_or_leak_into_the_declared_strategys_key():
    # Was (wrongly) test_a_null_row_among_declared_rows_does_not_block_the_agreed_class,
    # which asserted book-wide union behavior: a NULL strategy's key inherited
    # its sibling's EQUITY class. Flipped per the coordinator's finding F1 --
    # NULL fails closed for the NULL strategy's OWN key; it must not affect,
    # and must not borrow from, a different strategy's key either.
    mapping = registry_asset_class([
        _row(None, strategy_type="engine-null", id="registry-1"),
        _row("EQUITY", strategy_type="engine-declared", id="registry-2"),
    ])
    assert mapping == {"engine-declared": "EQUITY"}
    # The NULL strategy's own key: no fallback, fails closed if the catalog is silent.
    assert mapping.get("engine-null") is None
    with pytest.raises(PositionValidationError) as excinfo:
        resolve_asset_type(None, mapping.get("engine-null"))
    assert excinfo.value.code == "instrument_type_unavailable"
    # The declared sibling's own key still resolves.
    assert resolve_asset_type(None, mapping.get("engine-declared")) == "EQUITY"


def test_a_null_sibling_does_not_block_a_catalog_futures_symbol_of_its_own_key():
    # The exact fail-open scenario F1 describes: a catalog-known futures
    # symbol belonging to the NULL strategy must still resolve FUTURE from
    # the catalog -- untouched by the sibling's EQUITY declaration.
    mapping = registry_asset_class([
        _row(None, strategy_type="engine-null", id="registry-1"),
        _row("EQUITY", strategy_type="engine-declared", id="registry-2"),
    ])
    assert resolve_asset_type("FUTURE", mapping.get("engine-null")) == "FUTURE"


def test_missing_registry_row_for_the_keys_strategy_has_no_fallback():
    # A key whose strategy_id never appears (by strategy_type) in the locked
    # registries at all (unknown or missing strategy) gets no fallback.
    mapping = registry_asset_class([_row("EQUITY", strategy_type="engine-two", id="registry-2")])
    assert mapping.get("engine-one") is None
    with pytest.raises(PositionValidationError) as excinfo:
        resolve_asset_type(None, mapping.get("engine-one"))
    assert excinfo.value.code == "instrument_type_unavailable"


def test_conflicting_registry_rows_for_the_same_strategy_type_have_no_fallback():
    # Two reachable registry rows (different ids) sharing one strategy_type
    # is itself ambiguous ownership (more than one reachable row), so this
    # refuses regardless of whether the two rows' classes agree or
    # disagree, and regardless of is_active/lifecycle -- see
    # test_two_agreeing_active_live_rows_same_type_still_refuse below for
    # the agreeing case.
    mapping = registry_asset_class([
        _row("EQUITY", strategy_type="engine-one", id="registry-1"),
        _row("FUTURE", strategy_type="engine-one", id="registry-2"),
    ])
    assert mapping.get("engine-one") is None


def test_no_rows_is_empty():
    assert registry_asset_class([]) == {}


def test_unrecognized_or_blank_asset_class_has_no_entry():
    mapping = registry_asset_class([
        _row("CRYPTO", strategy_type="engine-one"),
        _row("   ", strategy_type="engine-two"),
    ])
    assert mapping == {}


def test_non_sequence_registries_yields_no_fallback_for_any_key():
    assert registry_asset_class(None) == {}
    assert registry_asset_class("not-a-sequence") == {}
    assert registry_asset_class(object()) == {}


def test_non_mapping_row_is_skipped():
    assert registry_asset_class([_row("EQUITY", strategy_type="engine-one"), "not-a-row"]) == {"engine-one": "EQUITY"}


def test_row_without_a_usable_strategy_type_is_skipped():
    assert registry_asset_class([_row("EQUITY", strategy_type=None), _row("EQUITY", strategy_type="")]) == {}


# --- single-reachable-row semantics (F1 revision 3, independent review 1 ---
# --- revision-2 review, finding 1) ------------------------------------------
#
# Revision 2 required exactly one ACTIVE+LIVE owner row per strategy_type,
# which was too strict: `_validate_catalog` (the actual type gate,
# qt_workflow.py:324-326) requires exactly one REACHABLE row of any status,
# and active+live only when that row is editable. Revision 2 therefore
# refused a legitimate, codebase-supported shape: an immutable row under a
# single retired or incubating owner (migration 002's real lifecycle
# values). Verified-wrong results under revision 2, for a book with a
# LIVE (active+live, EQUITY) strategy and an OLD (single retired, EQUITY)
# strategy -- two DIFFERENT strategy_types, each with exactly one reachable
# row: revision 2 resolved LIVE but refused OLD outright, and (per the
# review) the SAME book's whole draft/preview/proposal read refused because
# resolve_instrument_types raises on the first unresolved key in a batch.
#
# Flipped from revision 2 (both now RESOLVE under revision 3):
#   - test_single_inactive_row_has_no_fallback -> ..._still_resolves
#   - test_single_active_but_non_live_row_has_no_fallback -> ..._still_resolves
# Flipped from revision 2 (now REFUSES: two reachable rows, previously "the
# inactive sibling doesn't block the one active+live owner" -- under
# revision 3 there is no "owner" filtering step at all, so a same-type
# sibling of ANY status is simply a second reachable row, and two reachable
# rows for one strategy_type is exactly the ambiguous-ownership shape that
# must refuse):
#   - test_inactive_sibling_of_the_wrong_class_does_not_block_a_clean_single_owner
#     -> test_a_same_type_sibling_of_any_status_makes_two_reachable_rows_and_refuses
# Kept unchanged (still correctly refuse under revision 3, for the same
# "two or more reachable rows" reason, not an active/live reason):
#   - test_active_null_plus_inactive_equity_same_type_has_no_fallback
#   - test_two_agreeing_active_live_rows_same_type_still_refuse
#   - test_active_null_owner_with_no_inactive_sibling_still_has_no_fallback
#     (the sole reachable row's own NULL, independent of any status)

def test_active_null_plus_inactive_equity_same_type_has_no_fallback():
    # Two reachable rows for one strategy_type -> refused, regardless of
    # is_active/lifecycle or which one is NULL.
    rows = [
        _row(None, strategy_type="ENG", id="registry-active", is_active=True, lifecycle="live"),
        _row("EQUITY", strategy_type="ENG", id="registry-inactive", is_active=False, lifecycle="retired"),
    ]
    assert registry_asset_class(rows) == {}


def test_two_agreeing_active_live_rows_same_type_still_refuse():
    # Ownership ambiguity (more than one reachable row) is refused even
    # when both rows agree on the class and both are active+live --
    # exactly like _validate_catalog's own `len(owners) != 1` check, which
    # does not special-case either agreement or status.
    rows = [
        _row("EQUITY", strategy_type="ENG", id="registry-1", is_active=True, lifecycle="live"),
        _row("EQUITY", strategy_type="ENG", id="registry-2", is_active=True, lifecycle="live"),
    ]
    assert registry_asset_class(rows) == {}


def test_single_inactive_row_still_resolves():
    # A single retired row is a legitimate sole owner of its strategy_type:
    # `_validate_catalog` does not require active+live except for editable
    # rows, a concern this function does not (and must not) duplicate.
    rows = [_row("EQUITY", strategy_type="ENG", id="registry-1", is_active=False, lifecycle="retired")]
    assert registry_asset_class(rows) == {"ENG": "EQUITY"}


def test_single_non_live_row_still_resolves():
    # Same for a single incubating row: lifecycle does not gate the type
    # itself, only editable-row ownership elsewhere.
    rows = [_row("EQUITY", strategy_type="ENG", id="registry-1", is_active=True, lifecycle="incubating")]
    assert registry_asset_class(rows) == {"ENG": "EQUITY"}


def test_active_null_owner_with_no_inactive_sibling_still_has_no_fallback():
    # The sole reachable row declaring NULL is refused on its own terms,
    # independent of is_active/lifecycle or any other row.
    rows = [_row(None, strategy_type="ENG", id="registry-1", is_active=True, lifecycle="live")]
    assert registry_asset_class(rows) == {}


def test_a_same_type_sibling_of_any_status_makes_two_reachable_rows_and_refuses():
    # Under revision 2 this was "an inactive sibling does not block a clean
    # single [active+live] owner" and resolved EQUITY. Under revision 3
    # there is no owner-filtering step: ANY second reachable row for the
    # same strategy_type, of any status, makes ownership itself ambiguous
    # for that type -- exactly what `_validate_catalog`'s `len(owners) != 1`
    # already refuses independently. This is correct, not a regression:
    # `_validate_catalog` would refuse this shape regardless of what
    # registry_asset_class returns, so resolving it here would only ever
    # produce a value nothing downstream can use.
    rows = [
        _row("EQUITY", strategy_type="ENG", id="registry-active", is_active=True, lifecycle="live"),
        _row("FUTURE", strategy_type="ENG", id="registry-inactive", is_active=False, lifecycle="retired"),
    ]
    assert registry_asset_class(rows) == {}


def test_live_and_old_different_strategy_types_each_resolve_from_their_own_single_row():
    # The independent review's own shape: a book with a LIVE (active+live
    # EQUITY) strategy and an OLD (single retired EQUITY) strategy -- two
    # DIFFERENT strategy_types, each with exactly one reachable row. Both
    # must resolve; under revision 2, OLD alone refused and (since
    # resolve_instrument_types raises on the first unresolved key in a
    # batch) that took the whole book's proposal/draft/preview/approval
    # reads down with it.
    rows = [
        _row("EQUITY", strategy_type="LIVE", id="registry-live", is_active=True, lifecycle="live"),
        _row("EQUITY", strategy_type="OLD", id="registry-old", is_active=False, lifecycle="retired"),
    ]
    mapping = registry_asset_class(rows)
    assert mapping == {"LIVE": "EQUITY", "OLD": "EQUITY"}
    assert resolve_asset_type(None, mapping.get("LIVE")) == "EQUITY"
    assert resolve_asset_type(None, mapping.get("OLD")) == "EQUITY"


# --- end-to-end through the same precedence rule, registry-supplied --------

def test_registry_fallback_resolves_a_symbol_the_catalog_has_never_heard_of():
    mapping = registry_asset_class([_row("EQUITY")])
    assert resolve_asset_type(None, mapping.get("engine-one")) == "EQUITY"


def test_registry_fallback_does_not_override_a_disagreeing_catalog_row():
    mapping = registry_asset_class([_row("EQUITY")])
    with pytest.raises(PositionValidationError) as excinfo:
        resolve_asset_type("FUTURE", mapping.get("engine-one"))
    assert excinfo.value.code == "instrument_type_conflict"


def test_conflicting_registry_rows_still_refuse_when_catalog_is_also_silent():
    mapping = registry_asset_class([
        _row("EQUITY", strategy_type="engine-one", id="registry-1"),
        _row("FUTURE", strategy_type="engine-one", id="registry-2"),
    ])
    with pytest.raises(PositionValidationError) as excinfo:
        resolve_asset_type(None, mapping.get("engine-one"))
    assert excinfo.value.code == "instrument_type_unavailable"

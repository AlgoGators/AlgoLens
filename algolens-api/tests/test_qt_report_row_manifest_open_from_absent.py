"""Pure tests for F3: report_row_manifest's new rule -- `after` keys must
cover (be a superset of) `before` keys; a `before` key missing from `after`
still refuses; an `after`-only key (a symbol with NO earlier position row at
all -- not even an explicit zero row) is treated as `before = 0`, exactly
like native's projection, instead of refusing the whole report.

These are written standalone (own vectors, own expected digests via
qt_digest_v1) per the coordinator's instruction: 'Until [vectors v2 is]
ready, write your own unit tests for these cases.' When the native lane's
qt-report-manifest-vectors-v2.json arrives, it should be copied byte-for-byte
into contracts/ and this file's cases cross-checked against it (see NOTES.md).
"""
from copy import deepcopy

from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.infrastructure.portfolio.qt_publication_proof import report_row_manifest


DAY = "2026-09-25"
BOOK = "QT_BOOK"


def _row(symbol, quantity, *, strategy_id="RUN", strategy_name="alpha", portfolio_type="qt"):
    return {
        "average_price_exact": "10", "daily_realized_pnl_exact": "0", "daily_unrealized_pnl_exact": "0",
        "key": {"date": DAY, "portfolio_id": BOOK, "portfolio_type": portfolio_type,
                "strategy_id": strategy_id, "strategy_name": strategy_name, "symbol": symbol},
        "last_update": f"{DAY}T20:00:00Z", "quantity_exact": quantity,
    }


def _selection(symbol, asset_type, *, strategy_id="RUN", strategy_name="alpha"):
    return {"asset_type": asset_type, "key": {"date": DAY, "portfolio_id": BOOK,
            "strategy_id": strategy_id, "strategy_name": strategy_name, "symbol": symbol}}


def _wire_key(row):
    return row["key"]


# --- open from absent: an after-only key is before = 0, not a refusal -------

def test_futures_open_from_absent_0_to_2():
    before = []
    after = [_row("ES", "2")]
    selection = [_selection("ES", "FUTURE")]
    digest = report_row_manifest(before, after, selection)
    assert digest is not None
    assert digest == qt_digest_v1({"component_keys": [_wire_key(after[0])]})


def test_equity_open_from_absent_0_to_9_25():
    before = []
    after = [_row("SYN", "9.25")]
    selection = [_selection("SYN", "EQUITY")]
    digest = report_row_manifest(before, after, selection)
    assert digest == qt_digest_v1({"component_keys": [_wire_key(after[0])]})


def test_short_opened_from_absent():
    before = []
    after = [_row("SYN", "-3")]
    selection = [_selection("SYN", "EQUITY")]
    digest = report_row_manifest(before, after, selection)
    assert digest == qt_digest_v1({"component_keys": [_wire_key(after[0])]})


def test_absent_to_zero_is_hidden_exactly_like_an_explicit_zero_row():
    # An after-only key with current quantity 0 is before=0 -> after=0:
    # never shown, same as the existing zero_stays_hidden vector.
    before = [_row("SYN", "5")]
    after = [_row("SYN", "5"), _row("ZERO", "0")]
    selection = [_selection("SYN", "EQUITY"), _selection("ZERO", "EQUITY")]
    digest = report_row_manifest(before, after, selection)
    assert digest == qt_digest_v1({"component_keys": [_wire_key(before[0])]})


def test_open_from_absent_alongside_an_existing_row_both_shown():
    before = [_row("SYN", "5")]
    after = [_row("SYN", "5"), _row("NEW", "2")]
    selection = [_selection("SYN", "EQUITY"), _selection("NEW", "EQUITY")]
    digest = report_row_manifest(before, after, selection)
    expected_keys = sorted([_wire_key(before[0]), _wire_key(after[1])],
                            key=lambda key: (key["strategy_name"], key["symbol"]))
    assert digest == qt_digest_v1({"component_keys": expected_keys})


def test_open_from_absent_still_enforces_whole_future_quantity():
    before = []
    after = [_row("ES", "2.5")]
    selection = [_selection("ES", "FUTURE")]
    assert report_row_manifest(before, after, selection) is None


def test_open_from_absent_without_a_selection_row_refuses():
    # An after-only key still needs its own asset-type/whole-FUTURE check
    # from its own selection row -- it gets no free pass just because it is
    # new.
    before = []
    after = [_row("ES", "2")]
    assert report_row_manifest(before, after, []) is None


# --- FUTURE closed to 0 (an existing before key, not an open) ---------------

def test_future_closed_to_zero_still_shown_at_zero():
    before = [_row("ES", "7")]
    after = [_row("ES", "0")]
    selection = [_selection("ES", "FUTURE")]
    digest = report_row_manifest(before, after, selection)
    assert digest == qt_digest_v1({"component_keys": [_wire_key(after[0])]})


# --- refusals that remain ----------------------------------------------------

def test_a_before_key_missing_from_after_refuses():
    # The saved row `before` proves existed is silently dropped from
    # `after` -- refuse, never treat a disappearance as anything but a bug.
    before = [_row("SYN", "5"), _row("GONE", "3")]
    after = [_row("SYN", "5")]
    selection = [_selection("SYN", "EQUITY"), _selection("GONE", "EQUITY")]
    assert report_row_manifest(before, after, selection) is None


def test_two_strategy_ids_refuses():
    before = []
    after = [_row("SYN", "5", strategy_id="RUN"), _row("OTHER", "2", strategy_id="DIFFERENT")]
    selection = [_selection("SYN", "EQUITY", strategy_id="RUN"),
                 _selection("OTHER", "EQUITY", strategy_id="DIFFERENT")]
    assert report_row_manifest(before, after, selection) is None


def test_after_totally_empty_refuses():
    assert report_row_manifest([], [], []) is None


def test_after_rows_disagreeing_on_portfolio_id_refuses():
    # `first = QtKey.from_wire(after[0]['key'])` fixes the book for every
    # row in both before and after (via `_accounting`'s per-row check); a
    # second after-only row from a different book is refused, not silently
    # merged into this book's report.
    before = []
    after = [_row("SYN", "5"), deepcopy(_row("ALT", "3"))]
    after[1]["key"]["portfolio_id"] = "OTHER_BOOK"
    selection = [_selection("SYN", "EQUITY"), _selection("ALT", "EQUITY")]
    assert report_row_manifest(before, after, selection) is None


def test_after_rows_disagreeing_on_date_refuses():
    before = []
    after = [_row("SYN", "5"), deepcopy(_row("ALT", "3"))]
    after[1]["key"]["date"] = "2026-09-26"
    selection = [_selection("SYN", "EQUITY"), _selection("ALT", "EQUITY")]
    assert report_row_manifest(before, after, selection) is None


def test_a_before_row_disagreeing_on_date_with_after_refuses():
    # before[0]'s date differs from after[0]'s -- book/day are fixed from
    # after[0], so a before row from a different day is refused the same
    # way a before key missing from after is.
    before = [deepcopy(_row("SYN", "5"))]
    before[0]["key"]["date"] = "2026-09-24"
    after = [_row("SYN", "5")]
    selection = [_selection("SYN", "EQUITY")]
    assert report_row_manifest(before, after, selection) is None


def test_before_not_a_list_refuses():
    after = [_row("SYN", "5")]
    selection = [_selection("SYN", "EQUITY")]
    assert report_row_manifest(None, after, selection) is None


# --- purity / non-mutation ---------------------------------------------------

def test_inputs_are_not_mutated():
    before = []
    after = [_row("ES", "2")]
    selection = [_selection("ES", "FUTURE")]
    original = deepcopy((before, after, selection))
    report_row_manifest(before, after, selection)
    assert (before, after, selection) == original

"""Registry grouping for the portfolio switcher (contract section 2, ruling 20)."""

from algolens.domain.portfolio.registry import (
    asset_class_for,
    desk_edit_allowed,
    group_portfolios,
    portfolio_entries,
)


def _row(portfolio_id, *, group=None, editable=False, strategy_type="LIVE_TREND_FOLLOWING", rid=None):
    return {
        "id": rid or portfolio_id.lower(),
        "portfolio_id": portfolio_id,
        "name": portfolio_id.title(),
        "strategy_type": strategy_type,
        "portfolio_group": group,
        "desk_editable": editable,
        "initial_equity": 500000.0,
        "managers": ["x"],
    }


def test_asset_class_from_strategy_type():
    assert asset_class_for("LIVE_TREND_FOLLOWING") == "futures"
    assert asset_class_for("LIVE_EQUITY_MEAN_REVERSION") == "equity"
    assert asset_class_for(None) == "futures"


def test_desk_editing_is_futures_only():
    assert desk_edit_allowed(_row("P", editable=True))
    assert not desk_edit_allowed(_row("P", editable=False))
    assert not desk_edit_allowed(
        _row("E", editable=True, strategy_type="LIVE_EQUITY_MEAN_REVERSION")
    )


def test_one_entry_per_portfolio_id_first_wins():
    entries = portfolio_entries(
        [_row("BASE", rid="inc_tf_fast"), _row("BASE", rid="inc_tf_base"), _row("C")]
    )
    assert [(e["portfolio_id"], e["id"]) for e in entries] == [
        ("BASE", "inc_tf_fast"),
        ("C", "c"),
    ]


def test_groups_follow_portfolio_group_with_editable_book_first():
    groups = group_portfolios(
        [
            _row("CONSERVATIVE_PORTFOLIO"),
            _row("QT_CONSERVATIVE_MODEL_PORTFOLIO", group="qt_conservative"),
            _row("QT_CONSERVATIVE_PORTFOLIO", group="qt_conservative", editable=True),
        ]
    )

    assert [g["group"] for g in groups] == ["CONSERVATIVE_PORTFOLIO", "qt_conservative"]
    assert groups[0]["grouped"] is False
    qt = groups[1]
    assert qt["grouped"] is True
    assert [p["portfolio_id"] for p in qt["portfolios"]] == [
        "QT_CONSERVATIVE_PORTFOLIO",
        "QT_CONSERVATIVE_MODEL_PORTFOLIO",
    ]
    assert [p["desk_editable"] for p in qt["portfolios"]] == [True, False]

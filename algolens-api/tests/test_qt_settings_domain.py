"""Desk settings rules (rulings 2, 3, 24; migration 022)."""

import pytest

from algolens.domain.qt.settings import (
    SettingsRuleError,
    changes_to_overrides,
    check_overrides_apply,
    deep_merge,
    flatten,
    settings_view,
    visible_config,
)

RUNNING = {
    "capital": 500000,
    "risk": {"max_leverage": 2.0, "max_drawdown": 0.3, "use_overlay": True},
    "strategies": {"tf": {"lookbacks": [16, 32, 64], "name": "trend"}},
    "database": {"host": "db", "password": "x"},
    "email": {"smtp": "x"},
    "broker": {"api_key": "k", "account": "U1"},
    "portfolio_id": "QT_CONSERVATIVE_PORTFOLIO",
    "backtest": {"lookback_years": 2},
    "execution": {"position_limit_live": 500, "position_limit_backtest": 1000},
    "live": {"historical_days": 730, "_note": "documentation"},
}


def test_hidden_sections_and_credentials_are_never_shown():
    visible = visible_config(RUNNING)
    assert "database" not in visible and "email" not in visible
    assert "portfolio_id" not in visible
    assert visible["broker"] == {"account": "U1"}


def test_backtest_settings_and_config_comments_are_never_shown():
    visible = visible_config(RUNNING)
    assert "backtest" not in visible
    # execution and live are kept from the desk whole (platform and ops switches).
    assert "execution" not in visible and "live" not in visible
    assert visible_config({"general": {"x": 1, "_note": "doc"}}) == {"general": {"x": 1}}


def test_flatten_lists_leaves_with_types():
    fields = {tuple(f["path"]): f["type"] for f in flatten(visible_config(RUNNING))}
    assert fields[("risk", "max_leverage")] == "number"
    assert fields[("risk", "use_overlay")] == "boolean"
    assert fields[("strategies", "tf", "lookbacks")] == "array"
    assert fields[("strategies", "tf", "name")] == "string"


def test_changes_become_a_nested_overrides_object():
    overrides = changes_to_overrides(
        RUNNING,
        [
            {"path": ["risk", "max_leverage"], "value": 1.5},
            {"path": ["capital"], "value": 600000},
            {"path": ["strategies", "tf", "lookbacks"], "value": [8, 16]},
        ],
    )
    assert overrides == {
        "risk": {"max_leverage": 1.5},
        "capital": 600000,
        "strategies": {"tf": {"lookbacks": [8, 16]}},
    }


@pytest.mark.parametrize(
    "change",
    [
        {"path": ["risk", "no_such_knob"], "value": 1},  # unknown key: refused
        {"path": ["database", "host"], "value": "evil"},
        {"path": ["email", "smtp"], "value": "x"},
        {"path": ["broker", "api_key"], "value": "k2"},
        {"path": ["portfolio_id"], "value": "OTHER"},
        {"path": ["backtest", "lookback_years"], "value": 3},
        {"path": ["execution", "position_limit_backtest"], "value": 5},
        {"path": ["live", "_note"], "value": "x"},
        {"path": ["risk", "max_leverage"], "value": None},
        {"path": ["risk", "max_leverage"], "value": "2"},
        {"path": ["risk", "use_overlay"], "value": 1},
        {"path": ["capital"], "value": True},
        {"path": ["strategies", "tf", "lookbacks"], "value": ["a"]},
        {"path": ["risk"], "value": 1},  # a section, not a setting
        {"path": "risk.max_leverage", "value": 1},
        {"path": [], "value": 1},
        {"value": 1},
    ],
)
def test_bad_changes_are_refused(change):
    with pytest.raises(SettingsRuleError):
        changes_to_overrides(RUNNING, [change])


def test_empty_changes_are_refused():
    with pytest.raises(SettingsRuleError):
        changes_to_overrides(RUNNING, [])


def test_a_value_equal_to_the_running_one_is_kept_to_undo_a_pending_change():
    assert changes_to_overrides(RUNNING, [{"path": ["risk", "max_leverage"], "value": 2.0}]) == {
        "risk": {"max_leverage": 2.0}
    }


def test_int_and_float_are_both_numbers():
    assert changes_to_overrides(RUNNING, [{"path": ["risk", "max_leverage"], "value": 3}]) == {
        "risk": {"max_leverage": 3}
    }


def test_deep_merge_keeps_the_earlier_desk_layer():
    assert deep_merge(
        {"risk": {"max_leverage": 1.5}, "capital": 1},
        {"risk": {"max_drawdown": 0.2}},
    ) == {"risk": {"max_leverage": 1.5, "max_drawdown": 0.2}, "capital": 1}


def test_restoring_a_version_with_a_retired_key_is_refused():
    check_overrides_apply(RUNNING, {"risk": {"max_leverage": 1.0}})
    check_overrides_apply(RUNNING, {})
    with pytest.raises(SettingsRuleError):
        check_overrides_apply(RUNNING, {"risk": {"gone": 1}})
    with pytest.raises(SettingsRuleError):
        check_overrides_apply(RUNNING, {"database": {"host": "x"}})


def test_view_shows_running_and_pending():
    fields = settings_view(
        {"risk": {"max_leverage": 1.5, "max_drawdown": 0.25}, "capital": 1},
        running_overrides={"risk": {"max_leverage": 1.5, "max_drawdown": 0.25}},
        active_overrides={"risk": {"max_leverage": 1.2}},
        pending=True,
    )
    by_path = {tuple(f["path"]): f for f in fields}
    assert by_path[("risk", "max_leverage")]["pending"] == 1.2
    assert by_path[("risk", "max_drawdown")]["pending_from_files"] is True
    assert by_path[("capital",)]["pending"] is None
    assert by_path[("risk", "max_leverage")]["overridden"] is True


# --- value rules (hardening spec, AlgoLens item 7) ---------------------------

TYPED = {
    "capital": 500000,
    "risk": {
        "max_leverage": 2.0,
        "max_drawdown": 0.3,
        "position_limit": 10,
        "vol_target": 0.2,
        "skew": -0.5,
        "unset": None,
    },
    "strategies": {"tf": {"lookbacks": [16, 32, 64]}},
}


@pytest.mark.parametrize(
    "path, value",
    [
        (["capital"], 500000.5),  # an integer stays an integer
        (["risk", "position_limit"], 20.5),
        (["strategies", "tf", "lookbacks"], [8, 16.5]),
        (["risk", "max_leverage"], -1.0),  # *leverage
        (["risk", "max_drawdown"], -0.1),  # *drawdown
        (["capital"], -1),  # *capital
        (["risk", "position_limit"], -3),  # *limit
        (["risk", "vol_target"], -0.2),  # contains vol
        (["risk", "unset"], [1, 2]),  # null running value: scalars only
        (["risk", "unset"], {"a": 1}),
        (["risk", "max_leverage"], float("nan")),
        (["risk", "max_leverage"], float("inf")),
    ],
)
def test_value_rules_refuse(path, value):
    with pytest.raises(SettingsRuleError):
        changes_to_overrides(TYPED, [{"path": path, "value": value}])


@pytest.mark.parametrize(
    "path, value, stored",
    [
        (["capital"], 600000.0, 600000),  # a whole float is stored as the int it is
        (["risk", "max_leverage"], 3, 3.0),  # a float may be given as an int
        (["risk", "skew"], -0.7, -0.7),  # no heuristic on this key
        (["risk", "unset"], 5, 5),
        (["risk", "unset"], "text", "text"),
        (["strategies", "tf", "lookbacks"], [8.0, 16], [8, 16]),
        (["risk", "position_limit"], 0, 0),
    ],
)
def test_value_rules_accept(path, value, stored):
    overrides = changes_to_overrides(TYPED, [{"path": path, "value": value}])
    node = overrides
    for key in path:
        node = node[key]
    assert node == stored and type(node) is type(stored)


def test_restoring_a_version_applies_the_value_rules():
    with pytest.raises(SettingsRuleError):
        check_overrides_apply(TYPED, {"risk": {"max_leverage": -2.0}})
    with pytest.raises(SettingsRuleError):
        check_overrides_apply(TYPED, {"capital": 1.5})
    check_overrides_apply(TYPED, {"risk": {"max_leverage": 1}})


# -- what the desk may not change (Dom, 2026-10-14) ------------------------------

FULL = {
    "qt": {"desk_editable": True},
    "live": {"historical_days": 730},
    "execution": {"slippage_bps": 1, "position_limit_live": 500},
    "strategy_defaults": {"fdm": [[1, 1]]},
    "optimization": {"max_iterations": 100},
    "general": {"initial_capital": 500000, "use_optimization": True,
                "covariance_stale_dates": 5, "covariance_history_prices": 756},
    "strategies": {"TREND": {"type": "TrendFollowingStrategy", "enabled_live": True,
                             "default_allocation": 1, "config": {"idm": 2.5, "risk_target": 0.2}}},
    "risk": {"max_drawdown": 0.3},
    "equity_slow_rule": {"pairs": [[32, 128]]},
}


def test_platform_ops_and_model_structure_are_kept_from_the_desk():
    visible = visible_config(FULL)
    assert set(visible) == {"general", "strategies", "risk", "equity_slow_rule"}
    assert visible["general"] == {"initial_capital": 500000}
    assert visible["strategies"] == {"TREND": {"config": {"idm": 2.5, "risk_target": 0.2}}}
    assert visible["risk"] == {"max_drawdown": 0.3}


@pytest.mark.parametrize("path", [
    ["qt", "desk_editable"], ["live", "historical_days"], ["execution", "position_limit_live"],
    ["strategy_defaults", "fdm"], ["optimization", "max_iterations"],
    ["general", "use_optimization"], ["general", "covariance_stale_dates"],
    ["strategies", "TREND", "type"], ["strategies", "TREND", "enabled_live"],
    ["strategies", "TREND", "default_allocation"],
])
def test_a_locked_setting_cannot_be_changed(path):
    with pytest.raises(SettingsRuleError, match="may not be changed from AlgoLens"):
        changes_to_overrides(FULL, [{"path": path, "value": 1}])


def test_the_desk_still_changes_risk_capital_and_signal_settings():
    overrides = changes_to_overrides(FULL, [
        {"path": ["risk", "max_drawdown"], "value": 0.25},
        {"path": ["general", "initial_capital"], "value": 400000},
        {"path": ["strategies", "TREND", "config", "idm"], "value": 2.0},
        {"path": ["equity_slow_rule", "pairs"], "value": [[16, 64]]},
    ])
    assert overrides["strategies"] == {"TREND": {"config": {"idm": 2.0}}}


def test_an_old_version_touching_a_locked_setting_cannot_be_restored():
    with pytest.raises(SettingsRuleError):
        check_overrides_apply(FULL, {"optimization": {"max_iterations": 50}})


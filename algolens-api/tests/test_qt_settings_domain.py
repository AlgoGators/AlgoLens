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


def test_backtest_settings_and_config_comments_are_never_shown_as_settings():
    visible = visible_config(RUNNING)
    assert "backtest" not in visible
    # D-14: execution and live are shown (locked), only their backtest keys are not.
    assert visible["execution"] == {"position_limit_live": 500}
    assert visible["live"] == {"historical_days": 730}
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


# -- D-14, D-19: everything shown; the admin's locks greyed out, never hidden ---------

FULL = {
    "qt": {"desk_editable": True},
    "live": {"historical_days": 730},
    "execution": {"slippage_bps": 1, "position_limit_live": 500},
    "strategy_defaults": {"fdm": [[1, 1]]},
    "optimization": {"max_iterations": 100},
    "initial_capital": 500000,
    "use_optimization": True,
    "covariance_stale_dates": 5,
    "covariance_history_prices": 756,
    "strategies": {"TREND": {"type": "TrendFollowingStrategy", "enabled_live": True,
                             "default_allocation": 1, "config": {"idm": 2.5, "risk_target": 0.2}}},
    "risk": {"max_drawdown": 0.3},
    "equity_slow_rule": {"pairs": [[32, 128]]},
}


def test_every_section_but_the_qt_block_is_shown():
    visible = visible_config(FULL)
    assert "qt" not in visible
    assert {"live", "execution", "strategy_defaults", "optimization", "use_optimization",
            "covariance_stale_dates", "strategies"} <= set(visible)


LOCKED = [
    ["live", "historical_days"], ["execution", "position_limit_live"],
    ["strategy_defaults", "fdm"], ["optimization", "max_iterations"],
    ["use_optimization"], ["covariance_stale_dates"], ["covariance_history_prices"],
    ["strategies", "TREND", "type"], ["strategies", "TREND", "enabled_live"],
    ["strategies", "TREND", "default_allocation"],
]


@pytest.mark.parametrize("path", LOCKED)
def test_a_locked_setting_is_shown_greyed_out_and_cannot_be_changed(path):
    field = next(f for f in settings_view(FULL, {}, {}, False) if f["path"] == path)
    assert field["locked"] is True and field["lockedBy"]
    with pytest.raises(SettingsRuleError, match="locked by an admin"):
        changes_to_overrides(FULL, [{"path": path, "value": "changed"}])


def test_the_qt_block_is_never_a_setting():
    with pytest.raises(SettingsRuleError, match="may not be changed from AlgoLens"):
        changes_to_overrides(FULL, [{"path": ["qt", "desk_editable"], "value": False}])


def test_an_admin_unlock_makes_a_setting_editable():
    overrides = changes_to_overrides(FULL, [{"path": ["use_optimization"], "value": False}], locks=())
    assert overrides == {"use_optimization": False}


def test_the_desk_still_changes_risk_capital_and_signal_settings():
    overrides = changes_to_overrides(FULL, [
        {"path": ["risk", "max_drawdown"], "value": 0.25},
        {"path": ["initial_capital"], "value": 400000},
        {"path": ["strategies", "TREND", "config", "idm"], "value": 2.0},
        {"path": ["equity_slow_rule", "pairs"], "value": [[16, 64]]},
    ])
    assert overrides["strategies"] == {"TREND": {"config": {"idm": 2.0}}}


def test_a_version_holding_a_now_locked_key_does_not_block_later_saves():
    # D-14: a version saved before #138 carries optimization.max_iterations; locking it must
    # not make every later save fail. The key is carried as it is.
    check_overrides_apply(FULL, {"optimization": {"max_iterations": 50}})


# -- D-15: the risk gate's limits as fields, with the engine's bounds and the mirror --------

RISK = {
    "sizing_mode": "half_compounding",
    "_sizing_note": "required; half_compounding sizes on starting capital less the drawdown",
    "risk": {
        "schema": 2,
        "modules": [{"id": "carver", "type": "carver", "R_max": 2.25, "R_jump_max": 4.5,
                     "R_shock_max": 4.0, "per_name_cap": 2, "trim_max": 5, "max_net_leverage": 6.0,
                     "max_gross_leverage": 8.0, "lookback_period": 252, "min_gate_dates": 21,
                     "lookback_unit": "dates", "confidence_level": 0.99,
                     "_overlay_limits_note": "the overlay limits"}],
        "risk_reporting": {"type": "carver", "window": "all_bars", "lookback_period": 252,
                           "confidence_level": 0.99, "max_net_leverage": 6.0,
                           "max_gross_leverage": 8.0, "_note": "mirrors the gate"},
        "max_drawdown": 0.3,
        "_description": "Risk configuration",
    },
}


def test_each_gate_limit_is_its_own_field_with_its_bounds():
    fields = {tuple(f["path"]): f for f in settings_view(RISK, {}, {}, False)}
    r_max = fields[("risk", "modules", "carver", "R_max")]
    assert r_max["value"] == 2.25 and r_max["bounds"]["max"] == 10.0
    assert fields[("risk", "modules", "carver", "trim_max")]["bounds"]["integer"] is True
    assert not any(f["type"] == "array" and f["path"][:2] == ["risk", "modules"]
                   for f in fields.values())


def test_a_gate_change_is_saved_as_the_whole_module_and_moves_its_mirror():
    overrides = changes_to_overrides(
        RISK, [{"path": ["risk", "modules", "carver", "max_gross_leverage"], "value": 6.0}])
    [module] = overrides["risk"]["modules"]
    assert module["max_gross_leverage"] == 6.0 and module["type"] == "carver"
    assert module["R_max"] == 2.25  # the rest of the module as it runs
    assert overrides["risk"]["risk_reporting"] == {"max_gross_leverage": 6.0}


@pytest.mark.parametrize("key, value, needle", [
    ("R_max", 1000, "at most 10"), ("per_name_cap", 9.0, "at most max_gross_leverage"),
    ("trim_max", 1000, "at most 100"), ("trim_max", 2.5, "whole number"),
    ("max_gross_leverage", 0, "above 0"), ("confidence_level", 1.5, "at most 1"),
])
def test_a_gate_limit_out_of_the_engines_bounds_is_refused(key, value, needle):
    with pytest.raises(SettingsRuleError, match=needle):
        changes_to_overrides(RISK, [{"path": ["risk", "modules", "carver", key], "value": value}])


@pytest.mark.parametrize("path, new", [
    (["risk", "modules", "carver", "type"], "none"),
    (["risk", "modules", "carver", "lookback_unit"], "bars"),
    (["risk", "risk_reporting", "max_gross_leverage"], 5.0),
    (["risk", "schema"], 3),
    (["sizing_mode"], "full_compounding"),
])
def test_read_only_settings_say_why_and_cannot_be_changed(path, new):
    field = next(f for f in settings_view(RISK, {}, {}, False) if f["path"] == path)
    assert field["readOnly"]
    with pytest.raises(SettingsRuleError, match="read-only"):
        changes_to_overrides(RISK, [{"path": path, "value": new}])


@pytest.mark.parametrize("overrides, needle", [
    ({"risk": {"modules": []}}, "list of modules"),
    ({"risk": {"modules": [{"id": "carver", "type": "none"}]}}, "type cannot be changed"),
    ({"risk": {"modules": [{"id": "other", "type": "carver"}]}}, "drops the carver module"),
])
def test_a_version_cannot_switch_the_gate_off_or_remove_it(overrides, needle):
    with pytest.raises(SettingsRuleError, match=needle):
        check_overrides_apply(RISK, overrides)


# -- D-16: every visible field has its explanation ---------------------------------------

def test_every_field_shows_the_config_files_explanation():
    fields = settings_view(RISK, {}, {}, False)
    assert all(f["help"] for f in fields)
    by_path = {tuple(f["path"]): f["help"] for f in fields}
    assert by_path[("risk", "modules", "carver", "R_max")] == "the overlay limits"
    assert by_path[("risk", "max_drawdown")] == "Risk configuration"


# -- D-19: the rules tested against the config the engine ships for the QT book -----------
# tests/fixtures/qt_conservative_settings_used.json is live_run_metadata.settings_used of a
# QT_CONSERVATIVE_PORTFOLIO run: trade-ngin's config_template/portfolios/qt_conservative as the
# engine merges and reports it (no database or e-mail section).

import json as _json
from pathlib import Path as _Path

from algolens.domain.qt.settings import DEFAULT_LOCKS, matches

SHIPPED = _json.loads(
    (_Path(__file__).parent / "fixtures" / "qt_conservative_settings_used.json").read_text("utf-8")
)["config"]


def test_every_starting_lock_covers_a_setting_of_the_shipped_config():
    paths = [f["path"] for f in settings_view(SHIPPED, {}, {}, False)]
    for lock in DEFAULT_LOCKS:
        assert any(matches(lock, p) for p in paths), lock


def test_the_shipped_config_shows_every_section_with_help_and_hides_only_the_qt_block():
    fields = settings_view(SHIPPED, {}, {}, False)
    sections = {f["path"][0] for f in fields}
    assert "qt" not in sections and "backtest" not in sections and "portfolio_id" not in sections
    assert {"live", "execution", "optimization", "use_optimization", "risk", "strategies"} <= sections
    assert [f["path"] for f in fields if not f["help"]] == []


def test_the_shipped_gate_limits_are_fields_and_a_change_moves_the_mirror():
    fields = {tuple(f["path"]): f for f in settings_view(SHIPPED, {}, {}, False)}
    assert fields[("risk", "modules", "carver", "per_name_cap")]["bounds"]["max"] == 10.0
    overrides = changes_to_overrides(
        SHIPPED, [{"path": ["risk", "modules", "carver", "max_net_leverage"], "value": 5.0}])
    assert overrides["risk"]["risk_reporting"] == {"max_net_leverage": 5.0}
    check_overrides_apply(SHIPPED, overrides)



def test_initial_capital_moves_starting_capital_which_is_read_only():
    # D-60 found it: the engine refuses a run whose starting_capital differs from initial_capital.
    overrides = changes_to_overrides(SHIPPED, [{"path": ["initial_capital"], "value": 450000.0}])
    assert overrides == {"initial_capital": 450000.0, "starting_capital": 450000.0}
    field = next(f for f in settings_view(SHIPPED, {}, {}, False) if f["path"] == ["starting_capital"])
    assert "Follows initial_capital" in field["readOnly"]
    with pytest.raises(SettingsRuleError, match="read-only"):
        changes_to_overrides(SHIPPED, [{"path": ["starting_capital"], "value": 450000.0}])

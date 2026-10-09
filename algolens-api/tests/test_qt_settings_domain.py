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
}


def test_hidden_sections_and_credentials_are_never_shown():
    visible = visible_config(RUNNING)
    assert "database" not in visible and "email" not in visible
    assert "portfolio_id" not in visible
    assert visible["broker"] == {"account": "U1"}


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

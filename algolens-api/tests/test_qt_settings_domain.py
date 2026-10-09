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

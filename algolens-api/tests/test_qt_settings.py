"""QT desk environment settings and approver parsing."""

from algolens.domain.qt.approvers import approver_role_for, parse_approvers
from algolens.infrastructure.config.qt import load_qt_settings


def test_defaults_are_safe():
    settings = load_qt_settings({})
    assert settings.desk_enabled is False
    assert settings.approvers == {}
    assert settings.desk_agent_addr == "desk-agent:50051"


def test_flag_and_address_from_env():
    settings = load_qt_settings(
        {"QT_DESK_ENABLED": "TRUE", "DESK_AGENT_ADDR": " engine:6000 "}
    )
    assert settings.desk_enabled is True
    assert settings.desk_agent_addr == "engine:6000"
    assert load_qt_settings({"QT_DESK_ENABLED": "false"}).desk_enabled is False
    assert load_qt_settings({"QT_DESK_ENABLED": "nonsense"}).desk_enabled is False


def test_parse_approvers_ignores_junk():
    assert parse_approvers("vp=A@x.com, president = b@x.com ,cfo=c@x.com,bad") == {
        "vp": "a@x.com",
        "president": "b@x.com",
    }
    assert parse_approvers("") == {}


def test_approver_role_for():
    approvers = {"vp": "a@x.com", "president": "b@x.com"}
    assert approver_role_for("A@X.com", approvers) == "vp"
    assert approver_role_for("b@x.com", approvers) == "president"
    assert approver_role_for("c@x.com", approvers) is None
    assert approver_role_for("", approvers) is None
    # One person holding both roles is reported as vp.
    assert approver_role_for("d@x.com", {"vp": "d@x.com", "president": "d@x.com"}) == "vp"

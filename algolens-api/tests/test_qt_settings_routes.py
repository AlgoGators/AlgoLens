"""Desk settings use cases and routes against an in-memory repository."""

from datetime import date, datetime, timezone

import pytest

import algolens.adapters.http.desk as desk_http
from algolens.application.qt.ports import DeskConflict, DeskForbidden
from algolens.application.qt.settings_use_cases import GetSettings, RevertSettings, SaveSettings
from algolens.domain.qt.desk import DeskRuleError
from algolens.domain.qt.settings import SettingsRuleError
from algolens.infrastructure.config.qt import load_qt_settings
from test_qt_desk_routes import FakeRegistry, _login

QT = {"portfolio_id": "QT_CONSERVATIVE_PORTFOLIO", "strategy_type": "LIVE_TREND_FOLLOWING", "desk_editable": True}
MODEL = {**QT, "portfolio_id": "QT_CONSERVATIVE_MODEL_PORTFOLIO", "desk_editable": False}
CONFIG = {"risk": {"max_leverage": 2.0, "max_drawdown": 0.3}, "capital": 500000, "database": {"host": "h"}}


class FakeSettingsRepo:
    def __init__(self, settings_used=None):
        self.settings_used = settings_used
        self.versions = []

    def latest_settings_used(self, portfolio_id):
        if self.settings_used is None:
            return None
        return {"date": date(2026, 10, 8), "settings_used": self.settings_used}

    def config_versions(self, portfolio_id, limit=50):
        return sorted(self.versions, key=lambda r: -r["version"])

    def config_version(self, portfolio_id, version):
        return next((r for r in self.versions if r["version"] == version), None)

    def insert_config_version(self, portfolio_id, overrides, reason, created_by, expected):
        active = next((r["version"] for r in self.versions if r["is_active"]), None)
        if active != expected:
            raise DeskConflict("changed meanwhile")
        for r in self.versions:
            r["is_active"] = False
        row = {
            "version": len(self.versions) + 1,
            "overrides": overrides,
            "reason": reason,
            "created_by": created_by,
            "created_at": datetime(2026, 10, 8, tzinfo=timezone.utc),
            "is_active": True,
        }
        self.versions.append(row)
        return row


def used(version=None):
    return {"strategy_config_version": version, "config": CONFIG}


def test_save_merges_over_the_active_layer_and_is_pending():
    repo = FakeSettingsRepo(used())
    SaveSettings(repo).execute(QT, [{"path": ["risk", "max_leverage"], "value": 1.5}], "less", "d@x.com")
    SaveSettings(repo).execute(QT, [{"path": ["capital"], "value": 400000}], "smaller", "d@x.com")

    assert [r["is_active"] for r in repo.versions] == [False, True]
    assert repo.versions[-1]["overrides"] == {"risk": {"max_leverage": 1.5}, "capital": 400000}

    view = GetSettings(repo).execute(QT)
    assert view["running"] == {"date": "2026-10-08", "version": None}
    assert view["pending"] is True
    assert view["active"]["version"] == 2
    assert all(f["path"][0] != "database" for f in view["fields"])


def test_setting_a_pending_key_back_to_its_running_value_undoes_it():
    repo = FakeSettingsRepo(used())
    SaveSettings(repo).execute(QT, [{"path": ["risk", "max_leverage"], "value": 1.5}], "a", "d@x.com")
    SaveSettings(repo).execute(QT, [{"path": ["risk", "max_leverage"], "value": 2.0}], "undo", "d@x.com")
    assert repo.versions[-1]["overrides"] == {"risk": {"max_leverage": 2.0}}
    with pytest.raises(SettingsRuleError, match="No setting changed"):
        SaveSettings(repo).execute(QT, [{"path": ["risk", "max_leverage"], "value": 2.0}], "again", "d@x.com")
    assert len(repo.versions) == 2


def test_running_version_equal_to_active_is_not_pending():
    repo = FakeSettingsRepo(used())
    SaveSettings(repo).execute(QT, [{"path": ["capital"], "value": 1}], "r", "d@x.com")
    repo.settings_used = used(version=1)
    assert GetSettings(repo).execute(QT)["pending"] is False


def test_revert_is_a_new_version():
    repo = FakeSettingsRepo(used())
    SaveSettings(repo).execute(QT, [{"path": ["capital"], "value": 1}], "a", "d@x.com")
    SaveSettings(repo).execute(QT, [{"path": ["capital"], "value": 2}], "b", "d@x.com")
    RevertSettings(repo).execute(QT, 1, "back to v1", "d@x.com")
    assert [(r["version"], r["is_active"]) for r in repo.versions] == [(1, False), (2, False), (3, True)]
    assert repo.versions[-1]["overrides"] == {"capital": 1}
    RevertSettings(repo).execute(QT, 0, "back to the files", "d@x.com")
    assert repo.versions[-1]["overrides"] == {}


def test_settings_refusals():
    repo = FakeSettingsRepo(None)
    with pytest.raises(DeskConflict):  # no run has reported settings_used yet
        SaveSettings(repo).execute(QT, [{"path": ["capital"], "value": 1}], "r", "d@x.com")
    repo.settings_used = used()
    with pytest.raises(DeskRuleError):
        SaveSettings(repo).execute(QT, [{"path": ["capital"], "value": 1}], " ", "d@x.com")
    with pytest.raises(SettingsRuleError):
        SaveSettings(repo).execute(QT, [{"path": ["risk", "unknown"], "value": 1}], "r", "d@x.com")
    with pytest.raises(DeskForbidden):
        SaveSettings(repo).execute(MODEL, [{"path": ["capital"], "value": 1}], "r", "d@x.com")
    with pytest.raises(SettingsRuleError):
        RevertSettings(repo).execute(QT, -1, "r", "d@x.com")
    assert repo.versions == []


@pytest.fixture
def settings_repo(monkeypatch):
    repo = FakeSettingsRepo(used())
    monkeypatch.setenv("QT_DESK_ENABLED", "true")
    monkeypatch.setattr(desk_http, "create_desk_dependencies", lambda: (repo, None, load_qt_settings()))
    monkeypatch.setattr(desk_http, "create_portfolio_dependencies", lambda: (FakeRegistry(), None))
    return repo


def test_settings_routes(client, settings_repo):
    headers = _login(client)
    assert client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/settings").status_code == 200
    ok = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/settings",
        json={"changes": [{"path": ["capital"], "value": 1}], "reason": "r"},
        headers=headers,
    )
    assert ok.status_code == 201 and ok.get_json()["version"]["version"] == 1
    bad = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/settings",
        json={"changes": [{"path": ["database", "host"], "value": "x"}], "reason": "r"},
        headers=headers,
    )
    assert bad.status_code == 400
    revert = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/settings/revert",
        json={"version": 0, "reason": "files"},
        headers=headers,
    )
    assert revert.status_code == 201


def test_settings_routes_are_404_without_the_flag(client, settings_repo, monkeypatch):
    monkeypatch.setenv("QT_DESK_ENABLED", "false")
    _login(client)
    assert client.get("/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/settings").status_code == 404

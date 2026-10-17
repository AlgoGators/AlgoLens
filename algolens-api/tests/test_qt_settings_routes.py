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
    def __init__(self, settings_used=None, locks=None):
        self.settings_used = settings_used
        self.versions = []
        # None: the lock table is absent and the starting locks apply.
        self.locks = locks
        self.lock_log = []

    def settings_locks(self):
        return None if self.locks is None else [{"path": list(p)} for p in self.locks]

    def set_settings_lock(self, path, locked, reason, by):
        self.locks = [p for p in self.locks if list(p) != list(path)] + ([tuple(path)] if locked else [])
        self.lock_log.append((tuple(path), locked, reason, by))

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


class Engine:
    """CheckSettings (D-17): accepts unless told otherwise; records what it was asked."""

    def __init__(self):
        self.answer, self.down, self.calls = (True, ""), None, []

    def check_settings(self, portfolio_id, overrides):
        from algolens.application.qt.ports import DeskRiskUnavailable

        self.calls.append((portfolio_id, overrides))
        if self.down:
            raise DeskRiskUnavailable(self.down)
        return self.answer


ENGINE = Engine()


@pytest.fixture(autouse=True)
def _fresh_engine():
    ENGINE.answer, ENGINE.down, ENGINE.calls = (True, ""), None, []


def used(version=None):
    return {"strategy_config_version": version, "config": CONFIG}


def test_save_merges_over_the_active_layer_and_is_pending():
    repo = FakeSettingsRepo(used())
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["risk", "max_leverage"], "value": 1.5}], "less", "d@x.com")
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 400000}], "smaller", "d@x.com")

    assert [r["is_active"] for r in repo.versions] == [False, True]
    assert repo.versions[-1]["overrides"] == {"risk": {"max_leverage": 1.5}, "capital": 400000}

    view = GetSettings(repo).execute(QT)
    assert view["running"] == {"date": "2026-10-08", "version": None}
    assert view["pending"] is True
    assert view["active"]["version"] == 2
    assert all(f["path"][0] != "database" for f in view["fields"])


def test_setting_a_pending_key_back_to_its_running_value_undoes_it():
    repo = FakeSettingsRepo(used())
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["risk", "max_leverage"], "value": 1.5}], "a", "d@x.com")
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["risk", "max_leverage"], "value": 2.0}], "undo", "d@x.com")
    assert repo.versions[-1]["overrides"] == {"risk": {"max_leverage": 2.0}}
    with pytest.raises(SettingsRuleError, match="No setting changed"):
        SaveSettings(repo, ENGINE).execute(QT, [{"path": ["risk", "max_leverage"], "value": 2.0}], "again", "d@x.com")
    assert len(repo.versions) == 2


def test_running_version_equal_to_active_is_not_pending():
    repo = FakeSettingsRepo(used())
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 1}], "r", "d@x.com")
    repo.settings_used = used(version=1)
    assert GetSettings(repo).execute(QT)["pending"] is False


def test_revert_is_a_new_version():
    repo = FakeSettingsRepo(used())
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 1}], "a", "d@x.com")
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 2}], "b", "d@x.com")
    RevertSettings(repo, ENGINE).execute(QT, 1, "back to v1", "d@x.com")
    assert [(r["version"], r["is_active"]) for r in repo.versions] == [(1, False), (2, False), (3, True)]
    assert repo.versions[-1]["overrides"] == {"capital": 1}
    RevertSettings(repo, ENGINE).execute(QT, 0, "back to the files", "d@x.com")
    assert repo.versions[-1]["overrides"] == {}


def test_settings_refusals():
    repo = FakeSettingsRepo(None)
    with pytest.raises(DeskConflict):  # no run has reported settings_used yet
        SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 1}], "r", "d@x.com")
    repo.settings_used = used()
    with pytest.raises(DeskRuleError):
        SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 1}], " ", "d@x.com")
    with pytest.raises(SettingsRuleError):
        SaveSettings(repo, ENGINE).execute(QT, [{"path": ["risk", "unknown"], "value": 1}], "r", "d@x.com")
    with pytest.raises(DeskForbidden):
        SaveSettings(repo, ENGINE).execute(MODEL, [{"path": ["capital"], "value": 1}], "r", "d@x.com")
    with pytest.raises(SettingsRuleError):
        RevertSettings(repo, ENGINE).execute(QT, -1, "r", "d@x.com")
    assert repo.versions == []


@pytest.fixture
def settings_repo(monkeypatch):
    repo = FakeSettingsRepo(used())
    monkeypatch.setenv("QT_DESK_ENABLED", "true")
    monkeypatch.setattr(desk_http, "create_desk_dependencies", lambda: (repo, ENGINE, load_qt_settings()))
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


def test_a_revert_may_not_change_a_locked_setting():
    # D-14: a version saved while a key was unlocked cannot bring that value back once it is.
    config = {**CONFIG, "use_optimization": True}
    repo = FakeSettingsRepo({"strategy_config_version": None, "config": config}, locks=[])
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["use_optimization"], "value": False}], "a", "d@x.com")
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["use_optimization"], "value": True}], "b", "d@x.com")
    repo.locks = [("use_optimization",)]
    with pytest.raises(SettingsRuleError, match="changes settings an admin locked: use_optimization"):
        RevertSettings(repo, ENGINE).execute(QT, 1, "back", "d@x.com")
    # A save of something else still goes through with the locked key carried as it is.
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 1}], "c", "d@x.com")
    assert repo.versions[-1]["overrides"]["use_optimization"] is True


def test_the_view_marks_locked_and_read_only_fields():
    config = {**CONFIG, "use_optimization": True, "sizing_mode": "half_compounding",
              "_sizing_note": "one value"}
    repo = FakeSettingsRepo({"strategy_config_version": None, "config": config}, locks=[("use_optimization",)])
    fields = {tuple(f["path"]): f for f in GetSettings(repo).execute(QT)["fields"]}
    assert fields[("use_optimization",)]["locked"] is True
    assert fields[("sizing_mode",)]["readOnly"] and fields[("sizing_mode",)]["help"] == "one value"
    assert fields[("capital",)]["locked"] is False and fields[("capital",)]["readOnly"] is None


def test_lock_routes_list_for_the_desk_and_change_for_an_admin(client, settings_repo):
    settings_repo.locks = [("live",)]
    member = _login(client, role="exec_board", email="desk@x.com")
    listed = client.get("/portfolio/desk/settings-locks")
    assert listed.status_code == 200 and listed.get_json()["locks"] == [{"path": ["live"], "reason": None, "lockedBy": None, "lockedAt": None}]

    desk_only = _login(client, role="team_lead")
    refused = client.post("/portfolio/desk/settings-locks",
                          json={"path": ["capital"], "locked": True, "reason": "r"}, headers=desk_only)
    assert refused.status_code == 403

    admin = _login(client, role="admin")
    done = client.post("/portfolio/desk/settings-locks",
                       json={"path": ["capital"], "locked": True, "reason": "freeze"}, headers=admin)
    assert done.status_code == 200
    assert ("capital",) in settings_repo.locks and settings_repo.lock_log[-1][1:3] == (True, "freeze")
    unlocked = client.post("/portfolio/desk/settings-locks",
                           json={"path": ["live"], "locked": False, "reason": "open"}, headers=admin)
    assert unlocked.status_code == 200 and ("live",) not in settings_repo.locks


def test_a_lock_change_needs_the_lock_table(client, settings_repo):
    settings_repo.locks = None  # migration 004 not applied: the starting locks apply
    admin = _login(client, role="admin")
    response = client.post("/portfolio/desk/settings-locks",
                           json={"path": ["capital"], "locked": True, "reason": "r"}, headers=admin)
    assert response.status_code == 409
    assert client.get("/portfolio/desk/settings-locks").get_json()["stored"] is False


def test_the_engine_checks_a_version_before_it_is_saved():
    # D-17: the whole desk layer the save would make active is checked; a refusal saves nothing
    # and carries the engine's reason.
    repo = FakeSettingsRepo(used())
    SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 1}], "a", "d@x.com")
    assert ENGINE.calls[-1] == ("QT_CONSERVATIVE_PORTFOLIO", {"capital": 1})

    ENGINE.answer = (False, "risk.modules[0].R_max must be at most 10")
    with pytest.raises(SettingsRuleError, match="The engine refuses this change: risk.modules"):
        SaveSettings(repo, ENGINE).execute(QT, [{"path": ["capital"], "value": 2}], "b", "d@x.com")
    with pytest.raises(SettingsRuleError, match="The engine refuses"):
        RevertSettings(repo, ENGINE).execute(QT, 0, "files", "d@x.com")
    assert len(repo.versions) == 1


def test_nothing_is_saved_while_the_engine_cannot_check(client, settings_repo):
    ENGINE.down = "UNAVAILABLE"
    headers = _login(client)
    response = client.post(
        "/portfolio/desk/QT_CONSERVATIVE_PORTFOLIO/settings",
        json={"changes": [{"path": ["capital"], "value": 1}], "reason": "r"},
        headers=headers,
    )
    assert response.status_code == 409 and "could not check" in response.get_json()["error"]
    assert settings_repo.versions == []

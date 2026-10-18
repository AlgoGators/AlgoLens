"""The desk's settings editor (A7; rulings 2, 3, 24, 26).

Running = the strategy_config version the last live run reported in
live_run_metadata.settings_used; Pending = an active version newer than that,
which the next live run merges over the config files.
"""

from collections.abc import Mapping
from typing import Any

from algolens.application.qt.ports import (
    DeskAgentPort,
    DeskConflict,
    DeskForbidden,
    DeskNotFound,
    DeskRiskUnavailable,
    SettingsRepositoryPort,
)
from algolens.domain.portfolio.registry import desk_edit_allowed
from algolens.domain.qt.desk import require_reason
from algolens.domain.qt.settings import (
    DEFAULT_LOCKS,
    SettingsRuleError,
    changed_paths,
    changes_to_overrides,
    check_overrides_apply,
    deep_merge,
    is_hidden_path,
    lock_for,
    settings_view,
)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _version_row(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "version": row["version"],
        "overrides": row["overrides"],
        "reason": row["reason"],
        "created_by": row["created_by"],
        "created_at": _iso(row["created_at"]),
        "is_active": row["is_active"],
    }


def _running(repo: SettingsRepositoryPort, portfolio_id: str):
    row = repo.latest_settings_used(portfolio_id)
    used = (row or {}).get("settings_used")
    if not isinstance(used, Mapping) or not isinstance(used.get("config"), Mapping):
        return None
    version = used.get("strategy_config_version")
    return {
        "date": _iso(row.get("date")),
        "version": version if isinstance(version, int) and not isinstance(version, bool) else None,
        "config": used["config"],
    }


def _active(history):
    return next((row for row in history if row["is_active"]), None)


def _locks(repo: SettingsRepositoryPort) -> list[tuple[str, ...]]:
    """D-14: the admin's lock list (trading.desk_settings_locks); the starting list while the
    table is absent (AlgoLens migration 004 not applied yet)."""
    rows = repo.settings_locks()
    if rows is None:
        return list(DEFAULT_LOCKS)
    return [tuple(row["path"]) for row in rows]


def _engine_accepts(agent: DeskAgentPort, portfolio_id: str, overrides: Mapping[str, Any]) -> None:
    """HD D-17: the engine checks a settings version before it is saved, with the checks a live
    run makes at start-up; a refused version is never saved, and nothing is saved while the
    engine cannot be asked (a bad version would stop the desk run, the 09:30 send and the 10:00
    fallback until reverted)."""
    try:
        ok, error = agent.check_settings(portfolio_id, dict(overrides))
    except DeskRiskUnavailable as exc:
        raise DeskConflict(
            f"The engine could not check this change ({exc.reason}); nothing was saved. Try again."
        ) from None
    if not ok:
        raise SettingsRuleError(f"The engine refuses this change: {error}")


def _require_settings_editor(entry: Mapping[str, Any]) -> None:
    if not desk_edit_allowed(entry):
        raise DeskForbidden("Settings are edited on the desk's own (desk-editable) portfolio only")


class GetSettings:
    def __init__(self, repo: SettingsRepositoryPort):
        self.repo = repo

    def execute(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        portfolio_id = entry["portfolio_id"]
        running = _running(self.repo, portfolio_id)
        history = list(self.repo.config_versions(portfolio_id))
        active = _active(history)
        result: dict[str, Any] = {
            "portfolioId": portfolio_id,
            "editable": desk_edit_allowed(entry),
            "running": None,
            "active": _version_row(active),
            "pending": False,
            "fields": [],
            "history": [_version_row(row) for row in history],
        }
        if running is None:
            return result
        pending = active is not None and (
            running["version"] is None or active["version"] > running["version"]
        )
        running_row = (
            self.repo.config_version(portfolio_id, running["version"])
            if running["version"] is not None
            else None
        )
        result.update(
            {
                "running": {"date": running["date"], "version": running["version"]},
                "pending": pending,
                "fields": settings_view(
                    running["config"],
                    running_row["overrides"] if running_row else {},
                    active["overrides"] if active else {},
                    pending,
                    _locks(self.repo),
                ),
            }
        )
        return result


def _require_running(repo, portfolio_id):
    running = _running(repo, portfolio_id)
    if running is None:
        raise DeskConflict(
            "No live run has reported the settings it used yet (settings_used); "
            "settings can be edited after the first such run"
        )
    return running


class SaveSettings:
    def __init__(self, repo: SettingsRepositoryPort, agent: DeskAgentPort):
        self.repo = repo
        self.agent = agent

    def execute(
        self, entry: Mapping[str, Any], changes: Any, reason: Any, created_by: str
    ) -> dict[str, Any]:
        _require_settings_editor(entry)
        reason = require_reason(reason)
        portfolio_id = entry["portfolio_id"]
        running = _require_running(self.repo, portfolio_id)
        active = _active(self.repo.config_versions(portfolio_id))
        base = active["overrides"] if active else {}
        edits = changes_to_overrides(running["config"], changes, _locks(self.repo), base)
        overrides = deep_merge(base, edits)
        if overrides == base:
            raise SettingsRuleError("No setting changed")
        check_overrides_apply(running["config"], overrides)
        _engine_accepts(self.agent, portfolio_id, overrides)
        row = self.repo.insert_config_version(
            portfolio_id,
            overrides,
            reason,
            created_by,
            active["version"] if active else None,
        )
        return _version_row(row)


def _check_lock_path(path: Any) -> list[str]:
    if (
        not isinstance(path, list)
        or not path
        or not all(isinstance(k, str) and k.strip() for k in path)
    ):
        raise SettingsRuleError("A lock needs a path: a list of keys, '*' for any key")
    if is_hidden_path(path):
        raise SettingsRuleError(f"{'.'.join(path)} is never shown to the desk; it needs no lock")
    return [k.strip() for k in path]


class ListSettingsLocks:
    def __init__(self, repo: SettingsRepositoryPort):
        self.repo = repo

    def execute(self) -> dict[str, Any]:
        rows = self.repo.settings_locks()
        if rows is None:
            return {"stored": False, "locks": [
                {"path": list(p), "reason": None, "lockedBy": None, "lockedAt": None}
                for p in DEFAULT_LOCKS]}
        return {"stored": True, "locks": [
            {"path": list(r["path"]), "reason": r.get("reason"), "lockedBy": r.get("locked_by"),
             "lockedAt": _iso(r.get("locked_at"))} for r in rows
        ]}


class ChangeSettingsLock:
    """D-14: an admin locks or unlocks one setting (a path, or a pattern) for the desk."""

    def __init__(self, repo: SettingsRepositoryPort):
        self.repo = repo

    def execute(self, path: Any, locked: Any, reason: Any, by: str) -> dict[str, Any]:
        path = _check_lock_path(path)
        if not isinstance(locked, bool):
            raise SettingsRuleError("locked must be true or false")
        reason = require_reason(reason)
        if self.repo.settings_locks() is None:
            raise DeskConflict(
                "The lock list is not in the database yet (AlgoLens migration 004); "
                "the starting locks apply until it is"
            )
        self.repo.set_settings_lock(path, locked, reason, by)
        return ListSettingsLocks(self.repo).execute()


class RevertSettings:
    """Restore an earlier version as a NEW version (history is append-only).
    Version 0 restores the config files alone (empty overrides)."""

    def __init__(self, repo: SettingsRepositoryPort, agent: DeskAgentPort):
        self.repo = repo
        self.agent = agent

    def execute(
        self, entry: Mapping[str, Any], version: Any, reason: Any, created_by: str
    ) -> dict[str, Any]:
        _require_settings_editor(entry)
        reason = require_reason(reason)
        if not isinstance(version, int) or isinstance(version, bool) or version < 0:
            raise SettingsRuleError("version must be a whole number (0 = the config files)")
        portfolio_id = entry["portfolio_id"]
        running = _require_running(self.repo, portfolio_id)
        if version == 0:
            overrides: Mapping[str, Any] = {}
        else:
            row = self.repo.config_version(portfolio_id, version)
            if row is None:
                raise DeskNotFound(f"No settings version {version}")
            overrides = row["overrides"]
        check_overrides_apply(running["config"], overrides)
        active = _active(self.repo.config_versions(portfolio_id))
        # D-14: a revert may not change a locked setting either (it would undo or redo a
        # locked value); a locked key it carries unchanged is fine.
        locks = _locks(self.repo)
        locked = [
            ".".join(path)
            for path in changed_paths(active["overrides"] if active else {}, overrides)
            if lock_for(path, locks)
        ]
        if locked:
            raise SettingsRuleError(
                "This version changes settings an admin locked: " + ", ".join(locked)
            )
        _engine_accepts(self.agent, portfolio_id, overrides)
        row = self.repo.insert_config_version(
            portfolio_id,
            dict(overrides),
            reason,
            created_by,
            active["version"] if active else None,
        )
        return _version_row(row)

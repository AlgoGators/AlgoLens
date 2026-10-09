"""The desk's settings editor (A7; rulings 2, 3, 24, 26).

Running = the strategy_config version the last live run reported in
live_run_metadata.settings_used; Pending = an active version newer than that,
which the next live run merges over the config files.
"""

from collections.abc import Mapping
from typing import Any

from algolens.application.qt.ports import (
    DeskConflict,
    DeskForbidden,
    DeskNotFound,
    SettingsRepositoryPort,
)
from algolens.domain.portfolio.registry import desk_edit_allowed
from algolens.domain.qt.desk import require_reason
from algolens.domain.qt.settings import (
    SettingsRuleError,
    changes_to_overrides,
    check_overrides_apply,
    deep_merge,
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
    def __init__(self, repo: SettingsRepositoryPort):
        self.repo = repo

    def execute(
        self, entry: Mapping[str, Any], changes: Any, reason: Any, created_by: str
    ) -> dict[str, Any]:
        _require_settings_editor(entry)
        reason = require_reason(reason)
        portfolio_id = entry["portfolio_id"]
        running = _require_running(self.repo, portfolio_id)
        edits = changes_to_overrides(running["config"], changes)
        active = _active(self.repo.config_versions(portfolio_id))
        base = active["overrides"] if active else {}
        overrides = deep_merge(base, edits)
        check_overrides_apply(running["config"], overrides)
        row = self.repo.insert_config_version(
            portfolio_id,
            overrides,
            reason,
            created_by,
            active["version"] if active else None,
        )
        return _version_row(row)


class RevertSettings:
    """Restore an earlier version as a NEW version (history is append-only).
    Version 0 restores the config files alone (empty overrides)."""

    def __init__(self, repo: SettingsRepositoryPort):
        self.repo = repo

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
        row = self.repo.insert_config_version(
            portfolio_id,
            dict(overrides),
            reason,
            created_by,
            active["version"] if active else None,
        )
        return _version_row(row)

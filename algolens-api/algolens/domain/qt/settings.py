"""The desk's settings lane (rulings 2, 3, 24, 26; trade-ngin migration 022).

The engine publishes the effective config each live run traded on as
trading.live_run_metadata.settings_used = {"strategy_config_version": n|null,
"config": {...}} (files merged with the active strategy_config row, with the
database and email sections removed). The desk may change any key that config
holds (ruling 3) and nothing else: an unknown key would be a dead knob, and
the engine refuses a run whose saved settings cannot be applied (ruling 24).

A change is saved as a new trading.strategy_config version whose `overrides`
is the whole desk layer (the previous active overrides with the change merged
in), because exactly one version is active and only it is merged over the
files at the next live run.

Paths are lists of keys (["risk", "max_leverage"]) so a key holding a dot
cannot be misread.
"""

import copy
from collections.abc import Mapping
from numbers import Real
from typing import Any

# Never shown, never editable (the engine also refuses them).
HIDDEN_SECTIONS = frozenset({"database", "email"})
FORBIDDEN_KEYS = frozenset({"portfolio_id", "host", "port", "user", "username", "dbname"})
FORBIDDEN_MARKERS = ("password", "secret", "token", "api_key", "apikey", "private_key", "credential")

MAX_PATH_DEPTH = 12


class SettingsRuleError(ValueError):
    """A settings change breaks a rule; the message says which."""


def is_forbidden_key(key: str) -> bool:
    lowered = str(key).lower()
    return lowered in FORBIDDEN_KEYS or any(marker in lowered for marker in FORBIDDEN_MARKERS)


def visible_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """The config without the hidden sections and credential-like keys."""

    def strip(node: Any, depth: int) -> Any:
        if isinstance(node, Mapping):
            return {
                k: strip(v, depth + 1)
                for k, v in node.items()
                if not is_forbidden_key(k) and not (depth == 0 and k in HIDDEN_SECTIONS)
            }
        return copy.deepcopy(node)

    return strip(config or {}, 0)


def value_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Real):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if value is None:
        return "null"
    return "object"


def flatten(config: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    """Every editable leaf of a (visible) config as {path, value, type}."""
    fields = []
    for key, value in config.items():
        path = prefix + (key,)
        if isinstance(value, Mapping) and value:
            fields.extend(flatten(value, path))
        else:
            fields.append({"path": list(path), "value": value, "type": value_type(value)})
    return fields


def lookup(config: Mapping[str, Any], path: list[str]) -> tuple[bool, Any]:
    node: Any = config
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            return False, None
        node = node[key]
    return True, node


def _types_match(new: Any, old: Any) -> bool:
    new_t, old_t = value_type(new), value_type(old)
    if new_t != old_t:
        return False
    if new_t == "array" and old:
        # Arrays replace the file's array whole; keep the element types.
        kinds = {value_type(v) for v in old}
        return all(value_type(v) in kinds for v in new)
    return True


def _check_path(path: Any) -> list[str]:
    if (
        not isinstance(path, list)
        or not path
        or len(path) > MAX_PATH_DEPTH
        or not all(isinstance(k, str) and k for k in path)
    ):
        raise SettingsRuleError("Each change needs a path: a list of keys")
    if path[0] in HIDDEN_SECTIONS or any(is_forbidden_key(k) for k in path):
        raise SettingsRuleError(f"{'.'.join(path)} may not be changed from AlgoLens")
    return path


def _set(tree: dict[str, Any], path: list[str], value: Any) -> None:
    node = tree
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = copy.deepcopy(value)


def changes_to_overrides(running: Mapping[str, Any], changes: Any) -> dict[str, Any]:
    """Validate {path, value} changes against the running config and return
    them as a nested overrides object. Refuses unknown keys, hidden sections,
    credential keys, null and a type change."""
    if not isinstance(changes, list) or not changes:
        raise SettingsRuleError("changes must be a non-empty list of {path, value}")
    visible = visible_config(running)
    overrides: dict[str, Any] = {}
    seen = set()
    for change in changes:
        if not isinstance(change, Mapping) or "value" not in change:
            raise SettingsRuleError("Each change must be an object with path and value")
        path = _check_path(change.get("path"))
        name = ".".join(path)
        if tuple(path) in seen:
            raise SettingsRuleError(f"{name} is changed twice")
        seen.add(tuple(path))
        found, old = lookup(visible, path)
        if not found:
            raise SettingsRuleError(
                f"{name} is not a setting the last run used; only keys the engine "
                "reported in settings_used can be changed"
            )
        if isinstance(old, Mapping) and old:
            raise SettingsRuleError(f"{name} is a section, not a setting")
        new = change["value"]
        if new is None:
            raise SettingsRuleError(f"{name} cannot be set to null")
        if old is not None and not _types_match(new, old):
            raise SettingsRuleError(
                f"{name} must stay a {value_type(old)} (got {value_type(new)})"
            )
        # A value equal to the running one is kept: it may undo a pending
        # change. Whether anything changes at all is judged against the desk
        # layer by the caller.
        _set(overrides, path, new)
    return overrides


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """overlay over base: objects merge key by key, anything else replaces."""
    merged = copy.deepcopy(dict(base))
    for key, value in overlay.items():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def check_overrides_apply(running: Mapping[str, Any], overrides: Mapping[str, Any]) -> None:
    """Refuse an overrides object (e.g. an old version being restored) that
    names a key the running config no longer holds: the engine would refuse
    the run (ruling 24)."""
    visible = visible_config(running)

    def walk(node: Mapping[str, Any], prefix: list[str]) -> None:
        for key, value in node.items():
            path = prefix + [key]
            _check_path(path)
            found, old = lookup(visible, path)
            if not found:
                raise SettingsRuleError(
                    f"{'.'.join(path)} is no longer a setting the engine uses; "
                    "this version cannot be restored"
                )
            if isinstance(value, Mapping) and isinstance(old, Mapping):
                walk(value, path)
            elif value is None or (old is not None and not _types_match(value, old)):
                raise SettingsRuleError(f"{'.'.join(path)} has a value the engine would refuse")

    if not isinstance(overrides, Mapping):
        raise SettingsRuleError("A settings version must be an object")
    walk(overrides, [])


def leaf_paths(tree: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    leaves: dict[tuple[str, ...], Any] = {}
    for key, value in tree.items():
        path = prefix + (key,)
        if isinstance(value, Mapping) and value:
            leaves.update(leaf_paths(value, path))
        else:
            leaves[path] = value
    return leaves


def settings_view(
    running_config: Mapping[str, Any],
    running_overrides: Mapping[str, Any] | None,
    active_overrides: Mapping[str, Any] | None,
    pending: bool,
) -> list[dict[str, Any]]:
    """Fields with what is running and, when a newer version is active, what
    the next run will use. A key the active version stops overriding goes back
    to the file value, which AlgoLens does not know: pending_from_files."""
    running_layer = leaf_paths(running_overrides or {})
    active_layer = leaf_paths(active_overrides or {})
    fields = []
    for field in flatten(visible_config(running_config)):
        path = tuple(field["path"])
        entry = {
            **field,
            "overridden": path in (active_layer if pending else running_layer),
            "pending": None,
            "pending_from_files": False,
        }
        if pending:
            if path in active_layer:
                if active_layer[path] != field["value"]:
                    entry["pending"] = active_layer[path]
            elif path in running_layer:
                entry["pending_from_files"] = True
        fields.append(entry)
    return fields

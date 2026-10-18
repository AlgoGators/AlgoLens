"""The desk's settings lane (rulings 2, 3, 24, 26; trade-ngin migration 022; HD D-14 to D-19).

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

What the desk sees (D-14, decision 7): every setting the QT book runs on except
the database, email and qt blocks (the engine refuses those), backtest keys,
credentials and the portfolio id. Nothing else is hidden:
  * a setting an admin locked (the lock list in the database, D-14) is shown
    greyed out and cannot be changed;
  * a setting with one legal value, or one that mirrors another, is shown
    read-only with the reason (D-16);
  * each config comment (_note, _description, _<key>_reason, ...) is shown as
    the explanation of the settings it documents, never as a setting (D-16).

Paths are lists of keys (["risk", "max_drawdown"]). A list of objects that each
carry an "id" (risk.modules) is shown one field per key, addressed by the id:
["risk", "modules", "carver", "R_max"]. A change to such a field is saved as the
whole list with that key changed, because the engine's overlay replaces a list
whole; a module can therefore never be dropped or retyped by a save (D-15).

Values (check_value):
  * the type stays the running value's type; an integer stays an integer
    (20.5 is refused where the engine runs 20; 20.0 is stored as 20), and a
    float may be given as an integer (stored as a float, which the engine
    reads as a double);
  * where the running value is null AlgoLens cannot know the type, so only
    a scalar (boolean, number, string) is accepted, and the change is logged;
  * a heuristic on the key name refuses negative numbers where a negative
    value is never meant: the key (its last path element, lowercased) ends
    in "leverage", "drawdown", "capital" or "limit", or contains "vol"
    (volatility targets and windows). It is a guard against a typo, not a
    schema; the engine stays the judge of what it can run;
  * the risk gate's limits carry the engine's own bounds (D-15, D-78).
"""

import copy
import logging
import math
from collections.abc import Mapping, Sequence
from numbers import Integral, Real
from typing import Any

logger = logging.getLogger(__name__)

# Never shown, never editable: the engine refuses these blocks in a saved version, and the
# database and e-mail settings never leave the engine.
HIDDEN_SECTIONS = frozenset({"database", "email", "qt"})
# A key holding one of these anywhere in its path is hidden too
# (execution.position_limit_backtest, strategies.<name>.enabled_backtest).
HIDDEN_KEY_MARKERS = ("backtest",)
FORBIDDEN_KEYS = frozenset({"portfolio_id", "host", "port", "user", "username", "dbname"})
FORBIDDEN_MARKERS = ("password", "secret", "token", "api_key", "apikey", "private_key", "credential")

# D-14: the lock list as it starts (AlgoLens migration 004 seeds trading.desk_settings_locks
# with it, and it stands in while that table is absent). Dom, 2026-10-14: platform and
# operations switches and the model's structure are not the desk's to change. An admin locks
# or unlocks any setting from the Admin screen. A pattern matches a setting when each of its
# keys matches the setting's key at that depth: "*" any key, "covariance_*" a key starting
# with "covariance_"; a section's pattern covers everything under it. D-19: use_optimization
# and covariance_* sit at the top level of portfolio.json, not under "general".
DEFAULT_LOCKS = (
    ("live",),
    ("execution",),
    ("strategy_defaults",),
    ("optimization",),
    ("use_optimization",),
    ("covariance_*",),
    ("strategies", "*", "type"),
    ("strategies", "*", "enabled_live"),
    ("strategies", "*", "default_allocation"),
)

# D-16: settings with one legal value or that follow another, shown read-only with the reason.
READ_ONLY = (
    (("risk", "schema"), "The risk file's schema version: the engine reads one value."),
    (("sizing_mode",), "One legal value on a live futures book (half_compounding)."),
    (("starting_capital",),
     "Follows initial_capital: the engine requires the two equal, so it moves with it."),
    (("risk", "risk_reporting", "*"),
     "Mirrors the risk gate's limit in risk.modules and moves with it; the engine refuses a run "
     "where the two differ."),
    (("risk", "modules", "*", "id"), "The risk module's identity."),
    (("risk", "modules", "*", "type"),
     "The risk module's type: changing it would switch the risk gate off."),
    (("risk", "modules", "*", "lookback_unit"), "One legal value (dates)."),
    (("risk", "modules", "*", "missing_symbol_policy"),
     "Schema-1 behaviour migrated as is; changing it is its own measured change (see its note)."),
)

# D-15, D-78: the engine's bounds on the risk gate's limits (trade-ngin
# src/risk/risk_module_config.cpp). Each is (lowest, highest, lowest exclusive, whole number).
# D-78, Dominick's hard caps (2026-10-18), as risk_module_config.cpp holds them.
MODULE_BOUNDS = {
    "R_max": (0.0, 3.0, True, False),
    "R_jump_max": (0.0, 6.0, True, False),
    "R_shock_max": (0.0, 6.0, True, False),
    "max_gross_leverage": (0.0, 10.0, True, False),
    "max_net_leverage": (0.0, 10.0, True, False),
    "per_name_cap": (0.0, 4.0, True, False),
    "trim_max": (0, 20, False, True),
    "confidence_level": (0.0, 1.0, True, False),
    "min_gate_dates": (3, None, False, True),
    "lookback_period": (3, None, False, True),
}
# The gate limits risk.risk_reporting mirrors; a change to one moves the other in the same save.
MIRRORED_KEYS = ("max_gross_leverage", "max_net_leverage", "lookback_period", "confidence_level")
MODULES_PATH = ("risk", "modules")
REPORTING_PATH = ("risk", "risk_reporting")

NOTE_SUFFIXES = ("note", "reason", "description", "rationale")

MAX_PATH_DEPTH = 12

NON_NEGATIVE_SUFFIXES = ("leverage", "drawdown", "capital", "limit")
NON_NEGATIVE_MARKERS = ("vol",)


class SettingsRuleError(ValueError):
    """A settings change breaks a rule; the message says which."""


def is_forbidden_key(key: str) -> bool:
    """A key never shown as a setting: credentials, connection details, backtest settings,
    and config comments (_note, _description, ...), which are shown as help instead."""
    lowered = str(key).lower()
    return (
        lowered in FORBIDDEN_KEYS
        or lowered.startswith("_")
        or any(marker in lowered for marker in FORBIDDEN_MARKERS)
        or any(marker in lowered for marker in HIDDEN_KEY_MARKERS)
    )


def _key_matches(pattern: str, key: str) -> bool:
    if pattern == "*":
        return True
    return key.startswith(pattern[:-1]) if pattern.endswith("*") else key == pattern


def matches(pattern: Sequence[str], path: Sequence[str]) -> bool:
    """Whether a lock or read-only pattern covers the setting at `path`."""
    return len(pattern) <= len(path) and all(
        _key_matches(p, k) for p, k in zip(pattern, path)
    )


def is_hidden_path(path: list[str] | tuple[str, ...]) -> bool:
    """Whether a setting at `path` is never shown: a hidden block, or a credential, backtest
    or comment key anywhere in its path."""
    if not path:
        return False
    return path[0] in HIDDEN_SECTIONS or any(is_forbidden_key(k) for k in path)


def lock_for(path: Sequence[str], locks: Sequence[Sequence[str]]) -> Sequence[str] | None:
    """The first lock pattern covering `path`, or None."""
    return next((tuple(lock) for lock in locks if matches(lock, path)), None)


def read_only_reason(path: Sequence[str]) -> str | None:
    return next((why for pattern, why in READ_ONLY if matches(pattern, path)), None)


def _is_id_list(value: Any) -> bool:
    """A list of objects each with a string "id" (risk.modules): shown one field per key."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(v, Mapping) and isinstance(v.get("id"), str) and v["id"] for v in value)
    )


def visible_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """The config without everything is_hidden_path keeps from the desk."""

    def strip(node: Any, prefix: tuple[str, ...]) -> Any:
        if isinstance(node, Mapping):
            return {
                k: strip(v, prefix + (k,))
                for k, v in node.items()
                if not is_hidden_path(prefix + (k,))
            }
        if _is_id_list(node):
            return [strip(item, prefix + (item["id"],)) for item in node]
        return copy.deepcopy(node)

    return strip(config or {}, ())


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
    """Every leaf of a (visible) config as {path, value, type}; a list of id-objects
    contributes one leaf per key of each object, addressed by its id."""
    fields = []
    for key, value in config.items():
        path = prefix + (key,)
        if isinstance(value, Mapping) and value:
            fields.extend(flatten(value, path))
        elif _is_id_list(value):
            for item in value:
                fields.extend(flatten(item, path + (item["id"],)))
        else:
            fields.append({"path": list(path), "value": value, "type": value_type(value)})
    return fields


def lookup(config: Mapping[str, Any], path: Sequence[str]) -> tuple[bool, Any]:
    """The value at `path`; an id-list is entered by the id of its item."""
    node: Any = config
    for key in path:
        if isinstance(node, Mapping) and key in node:
            node = node[key]
        elif _is_id_list(node):
            item = next((v for v in node if v["id"] == key), None)
            if item is None:
                return False, None
            node = item
        else:
            return False, None
    return True, node


def _id_list_prefix(config: Mapping[str, Any], path: Sequence[str]) -> int | None:
    """The length of the part of `path` that names an id-list (2 for risk.modules.carver.R_max),
    or None when no id-list lies on the path."""
    node: Any = config
    for depth, key in enumerate(path):
        if _is_id_list(node):
            return depth
        if not isinstance(node, Mapping) or key not in node:
            return None
        node = node[key]
    return None


def _types_match(new: Any, old: Any) -> bool:
    new_t, old_t = value_type(new), value_type(old)
    if new_t != old_t:
        return False
    if new_t == "array" and old:
        # Arrays replace the file's array whole; keep the element types.
        kinds = {value_type(v) for v in old}
        return all(value_type(v) in kinds for v in new)
    return True


def _is_int(value: Any) -> bool:
    return isinstance(value, Integral) and not isinstance(value, bool)


def must_not_be_negative(key: str) -> bool:
    """The key-name heuristic of the module docstring."""
    lowered = str(key).lower()
    return lowered.endswith(NON_NEGATIVE_SUFFIXES) or any(m in lowered for m in NON_NEGATIVE_MARKERS)


def _numbers(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [v for v in value if value_type(v) == "number"]
    return [value] if value_type(value) == "number" else []


def bounds_for(path: Sequence[str]) -> dict[str, Any] | None:
    """The engine's bounds on a risk gate limit (risk.modules.<id>.<key>), or None."""
    if len(path) == 4 and tuple(path[:2]) == MODULES_PATH and path[3] in MODULE_BOUNDS:
        low, high, exclusive, whole = MODULE_BOUNDS[path[3]]
        return {"min": low, "max": high, "minExclusive": exclusive, "integer": whole}
    return None


def _check_bounds(path: Sequence[str], value: Any) -> None:
    bounds = bounds_for(path)
    if bounds is None or value_type(value) != "number":
        return
    name = ".".join(path)
    low, high = bounds["min"], bounds["max"]
    if bounds["integer"] and not _is_int(value):
        raise SettingsRuleError(f"{name} must be a whole number (got {value})")
    if low is not None and (value <= low if bounds["minExclusive"] else value < low):
        raise SettingsRuleError(
            f"{name} must be {'above' if bounds['minExclusive'] else 'at least'} {low} (got {value})"
        )
    if high is not None and value > high:
        raise SettingsRuleError(f"{name} must be at most {high} (got {value})")


def check_value(path: list[str], new: Any, old: Any) -> Any:
    """The value to store for `path`, given the running value `old`, or a
    SettingsRuleError. See the module docstring."""
    name = ".".join(path)
    if new is None:
        raise SettingsRuleError(f"{name} cannot be set to null")
    if any(not math.isfinite(v) for v in _numbers(new)):
        raise SettingsRuleError(f"{name} must be a finite number")
    if old is None:
        if value_type(new) not in ("boolean", "number", "string"):
            raise SettingsRuleError(
                f"{name} runs as null, so only a plain value (number, text, true/false) "
                "can be set"
            )
        logger.info("[SETTINGS] %s runs as null; setting it to a %s", name, value_type(new))
    elif not _types_match(new, old):
        raise SettingsRuleError(f"{name} must stay a {value_type(old)} (got {value_type(new)})")
    if _is_int(old) and value_type(new) == "number" and not _is_int(new):
        if not float(new).is_integer():
            raise SettingsRuleError(f"{name} must stay a whole number (got {new})")
        new = int(new)
    elif isinstance(old, float) and _is_int(new):
        new = float(new)  # the engine reads a double
    if isinstance(old, list) and old and all(_is_int(v) for v in old):
        if not all(_is_int(v) or float(v).is_integer() for v in new):
            raise SettingsRuleError(f"{name} must hold whole numbers")
        new = [int(v) for v in new]
    if must_not_be_negative(path[-1]) and any(v < 0 for v in _numbers(new)):
        raise SettingsRuleError(f"{name} cannot be negative")
    _check_bounds(path, new)
    return new


def _check_path(path: Any) -> list[str]:
    if (
        not isinstance(path, list)
        or not path
        or len(path) > MAX_PATH_DEPTH
        or not all(isinstance(k, str) and k for k in path)
    ):
        raise SettingsRuleError("Each change needs a path: a list of keys")
    if is_hidden_path(path):
        raise SettingsRuleError(f"{'.'.join(path)} may not be changed from AlgoLens")
    return path


def _set(tree: dict[str, Any], path: Sequence[str], value: Any) -> None:
    node = tree
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = copy.deepcopy(value)


def _check_module(module: Mapping[str, Any], path: Sequence[str]) -> None:
    """The cross-field bounds of one risk gate module (risk_module_config.cpp)."""
    name = ".".join(path)
    gross, net = module.get("max_gross_leverage"), module.get("max_net_leverage")
    if value_type(gross) == "number" and value_type(net) == "number" and net > gross:
        raise SettingsRuleError(
            f"{name}.max_net_leverage must be at most max_gross_leverage: {net} against {gross}"
        )
    period, gate = module.get("lookback_period"), module.get("min_gate_dates")
    if value_type(period) == "number" and value_type(gate) == "number" and period < gate:
        raise SettingsRuleError(
            f"{name}.lookback_period ({period} dates) is shorter than min_gate_dates ({gate})"
        )


def changes_to_overrides(
    running: Mapping[str, Any],
    changes: Any,
    locks: Sequence[Sequence[str]] = DEFAULT_LOCKS,
    active_overrides: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate {path, value} changes against the running config and return them as a nested
    overrides object. Refuses unknown keys, hidden or locked or read-only settings, null, a
    type change and a value out of the engine's bounds. A change to a risk gate limit is
    saved as the whole module list with that limit changed (from the active version's list
    when it holds one), and moves its risk_reporting mirror too."""
    if not isinstance(changes, list) or not changes:
        raise SettingsRuleError("changes must be a non-empty list of {path, value}")
    visible = visible_config(running)
    overrides: dict[str, Any] = {}
    list_edits: dict[tuple[str, ...], dict[str, dict[str, Any]]] = {}
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
        why = read_only_reason(path)
        lock = lock_for(path, locks)
        if why or lock:
            # Refused whatever the value, unless it is the value the setting runs with.
            try:
                same = check_value(path, change["value"], old) == old
            except SettingsRuleError:
                same = False
            if not same:
                raise SettingsRuleError(
                    f"{name} is read-only: {why}" if why else
                    f"{name} is locked by an admin ({'.'.join(lock)}); an admin can unlock it"
                )
        new = check_value(path, change["value"], old)
        cut = _id_list_prefix(visible, path)
        if cut is not None:
            list_path, item_id, rest = tuple(path[:cut]), path[cut], path[cut + 1:]
            if len(rest) != 1:
                raise SettingsRuleError(f"{name} is not a setting of {'.'.join(list_path)}")
            list_edits.setdefault(list_path, {}).setdefault(item_id, {})[rest[0]] = new
            continue
        # A value equal to the running one is kept: it may undo a pending
        # change. Whether anything changes at all is judged against the desk
        # layer by the caller.
        _set(overrides, path, new)
    # D-60: the engine requires starting_capital to equal initial_capital; they move together.
    if "initial_capital" in overrides and lookup(running, ["starting_capital"])[0]:
        overrides["starting_capital"] = overrides["initial_capital"]
    for list_path, edits in list_edits.items():
        found, base = lookup(active_overrides or {}, list_path)
        if not found or not _is_id_list(base):
            base = lookup(running, list_path)[1]
        items = copy.deepcopy(list(base))
        for item in items:
            for key, value in edits.get(item["id"], {}).items():
                item[key] = value
            _check_module(item, list_path + (item["id"],))
        _set(overrides, list_path, items)
        if list_path == MODULES_PATH:
            _move_mirrors(running, overrides, items, edits)
    return overrides


def _move_mirrors(running, overrides, modules, edits) -> None:
    """D-15: a change to a gate limit risk.risk_reporting mirrors sets the mirror in the same
    save, so the engine never sees the two differ."""
    found, reporting = lookup(running, REPORTING_PATH)
    if not found or not isinstance(reporting, Mapping):
        return
    gate = next((m for m in modules if m.get("type") == reporting.get("type")), None)
    if gate is None:
        return
    for key in MIRRORED_KEYS:
        if key in edits.get(gate["id"], {}) and key in reporting:
            _set(overrides, REPORTING_PATH + (key,), gate[key])


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
    """Refuse an overrides object (e.g. an old version being restored) that names a key the
    running config no longer holds, has a value the engine would refuse, or would drop or
    retype a risk gate module (D-15). Locks are not applied here: a key a version saved
    before it was locked carries is kept as it is (D-14), and a revert is checked for locked
    changes by the caller."""
    visible = visible_config(running)

    def check_list(path: list[str], items: Any, old: Any) -> None:
        name = ".".join(path)
        if not _is_id_list(items):
            raise SettingsRuleError(f"{name} must stay a list of modules, each with its id")
        by_id = {item["id"]: item for item in items}
        for module in old:
            mine = by_id.get(module["id"])
            if mine is None:
                raise SettingsRuleError(f"{name} drops the {module['id']} module; it cannot be removed")
            if mine.get("type") != module.get("type"):
                raise SettingsRuleError(f"{name}.{module['id']}.type cannot be changed")
        for item in items:
            known = next((m for m in old if m["id"] == item["id"]), None)
            if known is None:
                raise SettingsRuleError(f"{name} adds a module ({item['id']}) the engine does not run")
            walk(item, path + [item["id"]], known)
            _check_module(item, tuple(path) + (item["id"],))

    def walk(node: Mapping[str, Any], prefix: list[str], old_node: Any) -> None:
        for key, value in node.items():
            path = prefix + [key]
            if is_hidden_path(path) and isinstance(old_node, Mapping) and key.startswith("_"):
                continue  # a comment carried in a module object: documentation
            _check_path(path)
            if not isinstance(old_node, Mapping) or key not in old_node:
                raise SettingsRuleError(
                    f"{'.'.join(path)} is no longer a setting the engine uses; "
                    "this version cannot be restored"
                )
            old = old_node[key]
            if _is_id_list(old):
                check_list(path, value, old)
                continue
            if isinstance(value, Mapping) and isinstance(old, Mapping):
                walk(value, path, old)
                continue
            try:
                check_value(path, value, old)
            except SettingsRuleError as exc:
                raise SettingsRuleError(
                    f"{'.'.join(path)} has a value the engine would refuse ({exc})"
                ) from None

    if not isinstance(overrides, Mapping):
        raise SettingsRuleError("A settings version must be an object")
    walk(overrides, [], visible)


def leaf_paths(tree: Mapping[str, Any], prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    """Every leaf of an overrides object by path; an id-list by the ids of its items."""
    leaves: dict[tuple[str, ...], Any] = {}
    for key, value in tree.items():
        path = prefix + (key,)
        if isinstance(value, Mapping) and value:
            leaves.update(leaf_paths(value, path))
        elif _is_id_list(value):
            for item in value:
                leaves.update(leaf_paths(item, path + (item["id"],)))
        else:
            leaves[path] = value
    return leaves


def changed_paths(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """The settings whose value differs between two overrides objects."""
    a, b = leaf_paths(before or {}), leaf_paths(after or {})
    return sorted(p for p in set(a) | set(b) if a.get(p, _MISSING) != b.get(p, _MISSING))


_MISSING = object()


def _notes(node: Mapping[str, Any]) -> dict[str, str]:
    return {k: v for k, v in node.items() if isinstance(k, str) and k.startswith("_")
            and isinstance(v, str) and v.strip()}


def _help_for(key: str, node: Mapping[str, Any], ancestors: list[Mapping[str, Any]]) -> str | None:
    """D-16: a setting's explanation from the config comments: its own (_<key>_note, ...), else
    the comment named for the start of its key (_sizing_note for sizing_mode), else the nearest
    section's _note or _description."""
    notes = _notes(node)
    for suffix in NOTE_SUFFIXES:
        if f"_{key}_{suffix}" in notes:
            return notes[f"_{key}_{suffix}"]
    stems = sorted(
        ((k[1:].rsplit("_", 1)[0], v) for k, v in notes.items()
         if "_" in k[1:] and k[1:].rsplit("_", 1)[1] in NOTE_SUFFIXES),
        key=lambda pair: -len(pair[0]),
    )
    for stem, text in stems:
        if stem and (key == stem or key.startswith(stem + "_")):
            return text
    # A comment of the same object that is not named for one of its other keys documents the
    # object's settings together (a risk module's _overlay_limits_note).
    own = [text for stem, text in stems
           if not any(k == stem or k.startswith(stem + "_") for k in node if not k.startswith("_"))]
    if own:
        return own[0]
    for section in [node] + ancestors:
        section_notes = _notes(section)
        for name in ("_note", "_description"):
            if name in section_notes:
                return section_notes[name]
    return None


def help_texts(config: Mapping[str, Any] | None) -> dict[tuple[str, ...], str]:
    """Every visible setting's explanation by path (see _help_for)."""
    out: dict[tuple[str, ...], str] = {}

    def walk(node: Mapping[str, Any], prefix: tuple[str, ...], ancestors: list) -> None:
        for key, value in node.items():
            path = prefix + (key,)
            if is_hidden_path(path):
                continue
            if isinstance(value, Mapping) and value:
                walk(value, path, [node] + ancestors)
            elif _is_id_list(value):
                for item in value:
                    walk(item, path + (item["id"],), [node] + ancestors)
            else:
                text = _help_for(key, node, ancestors)
                if text:
                    out[path] = text

    walk(config or {}, (), [])
    return out


def settings_view(
    running_config: Mapping[str, Any],
    running_overrides: Mapping[str, Any] | None,
    active_overrides: Mapping[str, Any] | None,
    pending: bool,
    locks: Sequence[Sequence[str]] = DEFAULT_LOCKS,
) -> list[dict[str, Any]]:
    """Fields with what is running and, when a newer version is active, what the next run will
    use; each with its explanation, whether an admin locked it, why it is read-only, and the
    engine's bounds. A key the active version stops overriding goes back to the file value,
    which AlgoLens does not know: pending_from_files."""
    running_layer = leaf_paths(running_overrides or {})
    active_layer = leaf_paths(active_overrides or {})
    helps = help_texts(running_config)
    fields = []
    for field in flatten(visible_config(running_config)):
        path = tuple(field["path"])
        lock = lock_for(path, locks)
        entry = {
            **field,
            "overridden": path in (active_layer if pending else running_layer),
            "pending": None,
            "pending_from_files": False,
            "help": helps.get(path),
            "locked": lock is not None,
            "lockedBy": list(lock) if lock else None,
            "readOnly": read_only_reason(path),
            "bounds": bounds_for(path),
        }
        if pending:
            if path in active_layer:
                if active_layer[path] != field["value"]:
                    entry["pending"] = active_layer[path]
            elif path in running_layer:
                entry["pending_from_files"] = True
        fields.append(entry)
    return fields

"""Framework-free application capabilities derived from current authority."""

from collections.abc import Iterable, Mapping


EDIT_CONFIG = "edit_config"
APPROVE_CONFIG = "approve_config"

VIEW_INTERNAL = "view_internal"
VIEW_QT_PLATFORM = "view_qt_platform"
EDIT_QT_BOOK = "edit_qt_book"
APPROVE_QT_OVERRIDE = "approve_qt_override"
MANAGE_INCUBATION = "manage_incubation"
MANAGE_BOOKS = "manage_books"
REQUEST_RUNTIME_CONTROL = "request_runtime_control"
APPROVE_RUNTIME_CONTROL = "approve_runtime_control"
PUBLISH_QT_BOOK = "publish_qt_book"
SAVE_ANALYSIS = "save_analysis"
VIEW_INVESTOR_BOOK = "view_investor_book"

CAPABILITIES = frozenset({
    EDIT_CONFIG, APPROVE_CONFIG,
    VIEW_INTERNAL,
    VIEW_QT_PLATFORM,
    EDIT_QT_BOOK,
    APPROVE_QT_OVERRIDE,
    MANAGE_INCUBATION,
    MANAGE_BOOKS,
    REQUEST_RUNTIME_CONTROL,
    APPROVE_RUNTIME_CONTROL,
    PUBLISH_QT_BOOK,
    SAVE_ANALYSIS,
    VIEW_INVESTOR_BOOK,
})

_ROLE_BUNDLES = {
    "admin": frozenset({
        VIEW_INTERNAL, VIEW_QT_PLATFORM, MANAGE_INCUBATION, MANAGE_BOOKS,
        REQUEST_RUNTIME_CONTROL, APPROVE_RUNTIME_CONTROL,
    }),
    "general_member": frozenset({
        VIEW_INTERNAL, VIEW_QT_PLATFORM, MANAGE_INCUBATION, MANAGE_BOOKS,
        REQUEST_RUNTIME_CONTROL,
    }),
    "exec_board": frozenset({VIEW_INTERNAL, VIEW_QT_PLATFORM}),
}

_SUBMIT_ROLES = frozenset({"admin", "general_member"})
_APPROVE_ROLES = frozenset({"admin", "general_member", "exec_board"})
CANONICAL_APPROVERS = frozenset({"hemdutt_rao", "xander_robbins", "dominick_dupuy"})


def _active(rows: Iterable[Mapping[str, object]], name: str) -> list[Mapping[str, object]]:
    return [row for row in rows if row.get(name) is True]


def resolve_capabilities(
    role: object,
    *,
    grants: Iterable[Mapping[str, object]] = (),
    mappings: Iterable[Mapping[str, object]] = (),
) -> tuple[str, ...]:
    """Return sorted current authority; unknown roles and ambiguous facts fail closed."""

    if not isinstance(role, str) or role not in _ROLE_BUNDLES:
        return ()
    resolved = set(_ROLE_BUNDLES[role])
    active_grants = _active(grants, "active")
    if role in _SUBMIT_ROLES and any(row.get("capability") == "qt_submit" for row in active_grants):
        resolved.add(EDIT_QT_BOOK)
        resolved.add(PUBLISH_QT_BOOK)
    active_mappings = _active(mappings, "active")
    if (
        role in _APPROVE_ROLES
        and any(row.get("capability") == "qt_approve" for row in active_grants)
        and len(active_mappings) == 1
        and active_mappings[0].get("person_id") in CANONICAL_APPROVERS
    ):
        resolved.add(APPROVE_QT_OVERRIDE)
    if (role in _APPROVE_ROLES and len(active_mappings) == 1
            and active_mappings[0].get("person_id") in CANONICAL_APPROVERS):
        for grant, capability in (("config_submit", EDIT_CONFIG), ("config_approve", APPROVE_CONFIG)):
            if len([row for row in active_grants if row.get("capability") == grant]) == 1:
                resolved.add(capability)
    return tuple(sorted(resolved))


def role_has_capability(role: object, capability: str) -> bool:
    return capability in resolve_capabilities(role)

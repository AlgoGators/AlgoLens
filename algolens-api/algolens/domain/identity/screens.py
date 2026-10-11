"""Screen access: which AlgoLens screens a user may open.

An admin assigns each user any of the screens below (Dom, 2026-10-11). The
roles stay as they are; a screen is a separate, per-user grant stored in
auth.user_screen_access (AlgoLens migration 003). Admin is a role, not a
screen: exec_board is exec, and exec equals admin (HD ruling 2026-09-25).
"""

MEMBER = "member"
INVESTOR = "investor"
QT = "qt"

# The order is the landing preference: a user holding several screens opens on
# the first one they hold.
SCREENS = (QT, MEMBER, INVESTOR)

# 'admin' is not in auth.user_role today; it is kept because the earlier
# internal-role map (and old tokens) carried it.
ADMIN_ROLES = frozenset({"exec_board", "admin"})

# Before migration 003 is applied the table does not exist. The backend then
# falls back to what 003's backfill grants, so a deploy that runs ahead of the
# migration keeps today's access instead of locking everyone out.
_LEGACY_MEMBER_ROLES = frozenset({"general_member", "team_lead", "exec_board", "admin"})


class ScreenRuleError(ValueError):
    """A screen set the rules refuse (an unknown screen, a malformed list)."""


def is_admin(role):
    return role in ADMIN_ROLES


def validate_screens(screens):
    """The requested screens as a sorted tuple, or ScreenRuleError."""
    if not isinstance(screens, (list, tuple)):
        raise ScreenRuleError("screens must be a list")
    result = set()
    for screen in screens:
        if not isinstance(screen, str) or screen not in SCREENS:
            raise ScreenRuleError(f"Unknown screen: {screen!r}")
        result.add(screen)
    return tuple(sorted(result))


def ordered(screens):
    """The screens in landing order (SCREENS), duplicates and unknowns dropped."""
    held = set(screens or ())
    return [screen for screen in SCREENS if screen in held]


def legacy_screens(role):
    """What migration 003's backfill grants a user of this role."""
    screens = []
    if role in _LEGACY_MEMBER_ROLES:
        screens.append(MEMBER)
    if role in ADMIN_ROLES:
        screens.append(QT)
    return ordered(screens)


def grant_changes(current, requested):
    """(granted, revoked): the screens to add and to remove, each sorted."""
    current, requested = set(current), set(requested)
    return tuple(sorted(requested - current)), tuple(sorted(current - requested))

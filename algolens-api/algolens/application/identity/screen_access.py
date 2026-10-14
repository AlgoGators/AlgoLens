"""Screen access use cases: read a user's screens, and let an admin assign them."""

from typing import Protocol

from algolens.application.shared.errors import NotFoundError
from algolens.domain.identity.screens import (
    SCREENS,
    is_admin,
    legacy_screens,
    ordered,
    validate_screens,
)


class ScreenAccessUnavailable(Exception):
    """auth.user_screen_access does not exist yet (migration 003 not applied)."""


class ScreenUserNotFound(NotFoundError):
    """No auth.users row with that id."""


class ScreenAccessRepositoryPort(Protocol):
    def screens_for(self, user_id) -> list[str]:
        """The user's screens; ScreenAccessUnavailable before migration 003."""
        ...

    def role_for(self, user_id) -> str | None:
        """The user's role as auth.users holds it now (None: no such user)."""
        ...

    def list_users(self) -> list[dict]:
        """Every user as {id, email, first_name, last_name, role, screens}."""
        ...

    def set_screens(self, user_id, screens, by_email):
        """Make the user's screen set exactly `screens`, logging each grant and
        revoke, in one transaction. Returns (screens, granted, revoked), or
        None when the user does not exist."""
        ...


class GetUserScreens:
    """A user's screens. An admin holds every screen (Dom, 2026-10-14: admins
    switch between member, qt and investor); everyone else the screens granted
    in auth.user_screen_access."""

    def __init__(self, repo: ScreenAccessRepositoryPort, on_fallback=None):
        self.repo = repo
        self.on_fallback = on_fallback

    def execute(self, user_id, role):
        if is_admin(role):
            return list(SCREENS)
        try:
            return ordered(self.repo.screens_for(user_id))
        except ScreenAccessUnavailable:
            if self.on_fallback is not None:
                self.on_fallback()
            return legacy_screens(role)


class ListUsersWithScreens:
    def __init__(self, repo: ScreenAccessRepositoryPort):
        self.repo = repo

    def execute(self):
        users = self.repo.list_users()
        for user in users:
            user["screens"] = ordered(user.get("screens"))
        return users


class SetUserScreens:
    """Replace a user's screen set. Returns (screens, granted, revoked)."""

    def __init__(self, repo: ScreenAccessRepositoryPort):
        self.repo = repo

    def execute(self, user_id, screens, by_email):
        requested = validate_screens(screens)
        result = self.repo.set_screens(user_id, requested, by_email)
        if result is None:
            raise ScreenUserNotFound("User not found")
        current, granted, revoked = result
        return ordered(current), granted, revoked

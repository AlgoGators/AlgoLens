"""Screen-access gates for the HTTP routes.

A user's screens (member / investor / qt) are read from the database on
every request, not from the JWT, so an admin's grant or revoke takes effect
on the user's next request. The server is the source of truth; the frontend
only hides what it would refuse.
"""

from functools import wraps

from flask import current_app, g, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from algolens.application.identity.screen_access import GetUserScreens
from algolens.domain.identity.screens import SCREENS, is_admin
from algolens.infrastructure.config.dependencies import (
    create_dev_auth_config,
    create_screen_access_dependencies,
)


def _warn_fallback():
    current_app.logger.warning(
        "[ACCESS] auth.user_screen_access is missing (AlgoLens migration 003 not "
        "applied): using the role-based fallback"
    )


def current_screens():
    """The signed-in user's screens, in landing order (cached per request)."""
    if "algolens_screens" in g:
        return g.algolens_screens
    user_id = get_jwt_identity()
    role = get_jwt().get("role")
    dev = create_dev_auth_config()
    if dev.is_enabled() and str(dev.user_id()) == str(user_id):
        # The dev-login user may have no auth.users row: every screen.
        screens = list(SCREENS)
    else:
        screens = GetUserScreens(
            create_screen_access_dependencies(), on_fallback=_warn_fallback
        ).execute(user_id, role)
    g.algolens_screens = screens
    return screens


def has_screen(*screens):
    held = set(current_screens())
    return any(screen in held for screen in screens)


def current_is_admin():
    return is_admin(get_jwt().get("role"))


def _refuse(what):
    current_app.logger.warning(
        "Refused %s to %s: user %s lacks %s",
        request.method,
        request.path,
        get_jwt_identity(),
        what,
    )
    return jsonify({"error": "Insufficient permissions"}), 403


def requires_screen(*screens):
    """403 unless the user holds at least one of `screens`. Put it after
    @jwt_required()."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not has_screen(*screens):
                return _refuse("screen " + "/".join(screens))
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def admin_only(fn):
    """403 unless the user's role is an admin one (exec_board)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_is_admin():
            return _refuse("an admin role")
        return fn(*args, **kwargs)

    return wrapper

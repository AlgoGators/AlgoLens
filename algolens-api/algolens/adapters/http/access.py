"""Screen-access gates for the HTTP routes.

A user's screens (member / investor / qt) AND their role are read from the
database on every request, never from the JWT, so an admin's grant or revoke,
a promotion and a demotion all take effect on the user's next request (a
token can live 12 hours). An admin (role exec_board) holds every screen and
is the only one who sees and uses the admin routes. A token whose user no
longer exists has no role and no screen. The server is the source of truth;
the frontend only hides what it would refuse.
"""

from functools import wraps

from flask import current_app, g, jsonify, request
from flask_jwt_extended import get_jwt_identity

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


def _is_dev_user(user_id):
    dev = create_dev_auth_config()
    return dev.is_enabled() and str(dev.user_id()) == str(user_id)


def current_role():
    """The signed-in user's role as auth.users holds it now (cached per
    request); None when the user no longer exists. The JWT's role claim is
    never trusted for access."""
    if "algolens_role" in g:
        return g.algolens_role
    user_id = get_jwt_identity()
    if _is_dev_user(user_id):
        # The dev-login user (never in production) may have no auth.users row.
        role = create_dev_auth_config().user_role()
    else:
        role = create_screen_access_dependencies().role_for(user_id)
    g.algolens_role = role
    return role


def current_screens():
    """The signed-in user's screens, in landing order (cached per request)."""
    if "algolens_screens" in g:
        return g.algolens_screens
    user_id = get_jwt_identity()
    if _is_dev_user(user_id):
        screens = list(SCREENS)
    else:
        role = current_role()
        screens = (
            []
            if role is None
            else GetUserScreens(
                create_screen_access_dependencies(), on_fallback=_warn_fallback
            ).execute(user_id, role)
        )
    g.algolens_screens = screens
    return screens


def has_screen(*screens):
    held = set(current_screens())
    return any(screen in held for screen in screens)


def current_is_admin():
    return is_admin(current_role())


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

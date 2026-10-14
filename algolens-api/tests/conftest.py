"""Pytest fixtures for the AlgoLens backend.

The app is a module-level singleton created at import time, and its fail-closed
behavior (JWT/CORS) is evaluated then. So we configure a safe DEVELOPMENT env
BEFORE importing app, and exercise the production fail-closed paths in separate
subprocesses (see test_security.py) where the import is expected to raise.
"""

import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

# Safe dev config so `import app` succeeds and does not require a real DB/secret.
os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest")


@pytest.fixture
def client():
    import app as app_module

    app_module.app.config.update(TESTING=True)
    # Clear rate-limit counters so tests don't bleed into each other.
    try:
        app_module.limiter.reset()
    except Exception:
        pass
    with app_module.app.test_client() as c:
        yield c


class FakeScreenAccess:
    """Stands in for auth.user_screen_access in route tests.

    `screens` maps a JWT identity (str) to its screens. An identity not in it
    behaves as before migration 003 (the role-based fallback: internal roles
    get member, exec_board/admin also get qt), so route tests that only mint a
    role keep working.
    """

    def __init__(self):
        self.screens = {}
        self.set_calls = []
        # identity -> its role in auth.users now (None: the user was deleted). An
        # identity not in it has the role the test minted into its token.
        self.roles = {}

    def role_for(self, user_id):
        if str(user_id) in self.roles:
            return self.roles[str(user_id)]
        from flask_jwt_extended import get_jwt

        return get_jwt().get("role")

    def screens_for(self, user_id):
        from algolens.application.identity.screen_access import ScreenAccessUnavailable

        if str(user_id) not in self.screens:
            raise ScreenAccessUnavailable("fake: no row")
        return list(self.screens[str(user_id)])

    def list_users(self):
        return [
            {"id": int(uid), "email": f"user{uid}@x.com", "first_name": "U", "last_name": uid,
             "role": "general_member", "screens": list(screens)}
            for uid, screens in sorted(self.screens.items())
        ]

    def set_screens(self, user_id, screens, by_email):
        from algolens.domain.identity.screens import grant_changes

        key = str(user_id)
        if key not in self.screens:
            return None
        granted, revoked = grant_changes(self.screens[key], screens)
        self.screens[key] = list(screens)
        self.set_calls.append((key, tuple(screens), by_email, granted, revoked))
        return list(screens), granted, revoked


@pytest.fixture(autouse=True)
def screen_access(monkeypatch):
    import algolens.adapters.http.access as access
    import algolens.adapters.http.api as api

    fake = FakeScreenAccess()
    monkeypatch.setattr(access, "create_screen_access_dependencies", lambda: fake)
    monkeypatch.setattr(api, "create_screen_access_dependencies", lambda: fake)
    return fake

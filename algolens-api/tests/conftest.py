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

from algolens.domain.identity.models import user_from_row

# Safe dev config so `import app` succeeds and does not require a real DB/secret.
os.environ.setdefault("FLASK_ENV", "development")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-pytest")


class InMemoryCurrentUsers:
    """Explicit current-user rows for protected HTTP route tests."""

    def __init__(self):
        self.rows = {}
        self.error = None

    def set(self, user_id, *, role, email="test-user@algolens.local"):
        self.rows[str(user_id)] = {
            "id": user_id,
            "email": email,
            "role": role,
        }

    def set_row(self, user_id, row):
        self.rows[str(user_id)] = {"id": user_id, **row}

    def remove(self, user_id):
        self.rows.pop(str(user_id), None)

    def find_by_id(self, user_id):
        if self.error is not None:
            raise self.error
        row = self.rows.get(str(user_id))
        return user_from_row(row) if row is not None else None


@pytest.fixture
def current_users(monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    users = InMemoryCurrentUsers()
    monkeypatch.setattr(
        portfolio_http,
        "create_identity_dependencies",
        lambda: (users, object(), object()),
        raising=False,
    )
    return users


@pytest.fixture
def client(current_users):
    import app as app_module

    app_module.app.config.update(TESTING=True)
    # Clear rate-limit counters so tests don't bleed into each other.
    try:
        app_module.limiter.reset()
    except Exception:
        pass
    with app_module.app.test_client() as c:
        c.current_users = current_users
        yield c

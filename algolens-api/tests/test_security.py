"""Security-behavior tests for the AlgoLens backend hardening.

Covers: server-side password policy, auth-endpoint rate limiting, health-endpoint
information masking, and the JWT/CORS fail-closed-in-production guards.
"""

import os
import subprocess
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --- password policy ---------------------------------------------------------


def test_validate_password_helper():
    from routes.auth import _validate_password, MIN_PASSWORD_LENGTH

    assert _validate_password("short") is not None
    assert _validate_password("a" * (MIN_PASSWORD_LENGTH - 1)) is not None
    assert _validate_password("a" * MIN_PASSWORD_LENGTH) is None


def test_register_rejects_weak_password(client):
    # Password validation runs before any DB access, so no DB is needed here.
    resp = client.post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "short",
            "first_name": "A",
            "last_name": "B",
        },
    )
    assert resp.status_code == 400
    assert "12 characters" in resp.get_json()["error"]


# --- rate limiting -----------------------------------------------------------


def test_login_is_rate_limited(client, monkeypatch):
    # Stub the DB lookup so every login attempt cleanly returns 401 (user not found)
    # and we can drive the endpoint past its 10/min limit.
    import routes.auth as auth_mod

    monkeypatch.setattr(auth_mod, "execute_query", lambda *a, **k: None)

    statuses = [
        client.post(
            "/auth/login",
            json={"email": "user@example.com", "password": "a" * 12},
        ).status_code
        for _ in range(12)
    ]
    assert 429 in statuses, f"expected a 429 after the limit; got {statuses}"


# --- health endpoint masking -------------------------------------------------


def test_health_exposes_detail_in_development(client):
    # In development the health payload includes diagnostic fields...
    body = client.get("/health").get_json()
    assert "environment" in body and "cors_origins" in body


# --- fail-closed guards (evaluated at import time, so run in subprocesses) ----


def _import_app(env):
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, "-c", "import app"],
        env=full_env,
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )


def test_jwt_secret_fail_closed_in_production():
    env = dict(os.environ)
    env.pop("JWT_SECRET_KEY", None)
    env["FLASK_ENV"] = "production"
    env["CORS_ORIGINS"] = "https://algolens.example.com"  # so CORS passes first
    result = _import_app({**env, "JWT_SECRET_KEY": ""})
    assert result.returncode != 0
    assert "JWT_SECRET_KEY must be set" in result.stderr


def test_cors_fail_closed_in_production():
    env = dict(os.environ)
    env["FLASK_ENV"] = "production"
    env["JWT_SECRET_KEY"] = "some-real-secret"
    env["CORS_ORIGINS"] = ""  # empty -> must fail closed
    result = _import_app(env)
    assert result.returncode != 0
    assert "CORS_ORIGINS must be set" in result.stderr


def test_production_boots_with_valid_config():
    # Sanity: with both secrets set, import succeeds (no DB needed at import time).
    env = dict(os.environ)
    env["FLASK_ENV"] = "production"
    env["JWT_SECRET_KEY"] = "some-real-secret"
    env["CORS_ORIGINS"] = "https://algolens.example.com"
    result = _import_app(env)
    assert result.returncode == 0, result.stderr


# --- httpOnly cookie auth transport ------------------------------------------


def _fake_user():
    return {
        "id": 1,
        "email": "user@example.com",
        "password_hash": "irrelevant-because-check-is-stubbed",
        "first_name": "A",
        "last_name": "B",
        "role": "general_member",
    }


def test_cookie_transport_configured():
    import app as app_module

    cfg = app_module.app.config
    # Token travels in a cookie only (no Authorization header path), with CSRF on.
    assert cfg["JWT_TOKEN_LOCATION"] == ["cookies"]
    assert cfg["JWT_COOKIE_CSRF_PROTECT"] is True


def test_login_sets_httponly_cookie_and_no_body_token(client, monkeypatch):
    import routes.auth as auth_mod

    monkeypatch.setattr(auth_mod, "execute_query", lambda *a, **k: _fake_user())
    monkeypatch.setattr(auth_mod, "check_password_hash", lambda *a, **k: True)

    resp = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "a" * 12},
    )
    assert resp.status_code == 200

    body = resp.get_json()
    # The token must NOT be handed back in the body anymore.
    assert "token" not in body, f"token leaked into body: {body}"
    assert body["user"]["email"] == "user@example.com"

    set_cookies = resp.headers.getlist("Set-Cookie")
    # httpOnly access cookie is present so JS can never read the token...
    access = [c for c in set_cookies if c.startswith("access_token_cookie=")]
    assert access, f"expected access_token_cookie; got {set_cookies}"
    assert "HttpOnly" in access[0], f"access cookie must be HttpOnly: {access[0]}"
    # ...and a JS-readable CSRF companion cookie is present (deliberately NOT httpOnly).
    csrf = [c for c in set_cookies if c.startswith("csrf_access_token=")]
    assert csrf, f"expected csrf_access_token; got {set_cookies}"
    assert "HttpOnly" not in csrf[0], "CSRF cookie must be readable by JS"


def test_verify_requires_session(client):
    # With no cookie, /verify is a clean 401 (unauthorized loader), not a 500.
    resp = client.get("/auth/verify")
    assert resp.status_code == 401


def test_logout_clears_cookies(client):
    resp = client.post("/auth/logout")
    assert resp.status_code == 200
    set_cookies = resp.headers.getlist("Set-Cookie")
    # The access cookie is being cleared (unset_jwt_cookies emits a Set-Cookie for it).
    assert any(c.startswith("access_token_cookie=") for c in set_cookies), (
        f"logout should clear access_token_cookie; got {set_cookies}"
    )

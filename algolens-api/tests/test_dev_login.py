"""Tests for the DEV_MODE cookie dev-login (POST /auth/dev-login).

The bypass must be off by default, force-disabled in production even if the flag
is set, and -- when enabled -- must deliver the session as an httpOnly cookie
(never a body token) that the existing @jwt_required routes accept unchanged.
"""

import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.app_context():
        yield app.test_client()


def test_dev_login_disabled_by_default_returns_404(client, monkeypatch):
    monkeypatch.delenv("DEV_MODE", raising=False)
    assert client.post("/auth/dev-login").status_code == 404


def test_dev_login_refused_in_production_even_if_flag_set(client, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "production")
    assert client.post("/auth/dev-login").status_code == 404


def test_dev_login_sets_httponly_cookie_and_no_body_token(client, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "development")
    resp = client.post("/auth/dev-login")
    assert resp.status_code == 200

    body = resp.get_json()
    # The token must be delivered as a cookie, never in the body.
    assert "token" not in body, f"token leaked into body: {body}"
    assert body["user"]["role"] == "admin"

    set_cookies = resp.headers.getlist("Set-Cookie")
    access = [c for c in set_cookies if c.startswith("access_token_cookie=")]
    assert access, f"expected access_token_cookie; got {set_cookies}"
    assert "HttpOnly" in access[0], f"access cookie must be HttpOnly: {access[0]}"
    csrf = [c for c in set_cookies if c.startswith("csrf_access_token=")]
    assert csrf, f"expected csrf_access_token; got {set_cookies}"
    assert "HttpOnly" not in csrf[0], "CSRF cookie must be readable by JS"


def test_dev_login_respects_env_overrides(client, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("DEV_USER_ID", "42")
    monkeypatch.setenv("DEV_USER_EMAIL", "someone@algolens.local")
    monkeypatch.setenv("DEV_USER_ROLE", "general_member")
    body = client.post("/auth/dev-login").get_json()
    assert body["user"]["id"] == 42
    assert body["user"]["email"] == "someone@algolens.local"
    assert body["user"]["role"] == "general_member"


def test_dev_cookie_passes_the_auth_gate(client, monkeypatch):
    """The cookie dev-login sets must satisfy @jwt_required on a protected GET.

    /portfolio/strategies is @jwt_required. A GET is a safe method, so no CSRF
    header is needed -- the cookie alone must get us past auth (not 401/422). It
    may still be 500 if no DB is configured, but that is behind the auth gate.
    """
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "development")
    client.post("/auth/dev-login")  # sets the cookie on the client's jar
    resp = client.get("/portfolio/strategies")
    assert resp.status_code not in (401, 422)

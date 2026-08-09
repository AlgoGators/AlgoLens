import pytest

from algolens.domain.identity.models import User
from algolens.infrastructure.identity.sessions import FlaskJwtSessionIssuer


class FakeUsers:
    def __init__(self, user=None):
        self.user = user
        self.completed = None

    def find_by_email(self, email):
        return self.user if self.user and self.user.email == email else None

    def find_by_id(self, user_id):
        return self.user if self.user and str(self.user.id) == str(user_id) else None

    def complete_registration(self, email, password_hash, first_name, last_name):
        self.completed = (email, password_hash, first_name, last_name)
        return User(
            id=1,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role="general_member",
            password_hash=password_hash,
        )


class FakeHasher:
    def __init__(self, valid=True):
        self.valid = valid

    def verify(self, password_hash, password):
        return self.valid

    def hash(self, password):
        return f"hashed:{password}"


def _patch_identity_dependencies(monkeypatch, users, hasher=None):
    import algolens.adapters.http.auth as auth_mod

    fake_hasher = hasher or FakeHasher()
    monkeypatch.setattr(
        auth_mod,
        "_identity_dependencies",
        lambda: (users, fake_hasher, FlaskJwtSessionIssuer()),
    )


def _assert_session_cookies(resp):
    set_cookies = resp.headers.getlist("Set-Cookie")
    access = [c for c in set_cookies if c.startswith("access_token_cookie=")]
    csrf = [c for c in set_cookies if c.startswith("csrf_access_token=")]
    assert access, f"expected access_token_cookie; got {set_cookies}"
    assert "HttpOnly" in access[0], f"access cookie must be HttpOnly: {access[0]}"
    assert csrf, f"expected csrf_access_token; got {set_cookies}"
    assert "HttpOnly" not in csrf[0], "CSRF cookie must be readable by JS"


def test_check_email_missing_email_returns_400(client):
    resp = client.post("/auth/check-email", json={})

    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Email is required"}


def test_check_email_not_found_shape_omits_registered(client, monkeypatch):
    _patch_identity_dependencies(monkeypatch, FakeUsers(user=None))

    resp = client.post("/auth/check-email", json={"email": "missing@example.com"})

    assert resp.status_code == 404
    assert resp.get_json() == {
        "exists": False,
        "message": "Email not found. Contact an administrator to be added.",
    }


def test_check_email_registered_shape(client, monkeypatch):
    _patch_identity_dependencies(
        monkeypatch,
        FakeUsers(User(id=1, email="user@example.com", password_hash="hashed")),
    )

    resp = client.post("/auth/check-email", json={"email": "user@example.com"})

    assert resp.status_code == 200
    assert resp.get_json() == {
        "exists": True,
        "registered": True,
        "message": "Account already registered. Please login.",
    }


def test_check_email_unregistered_shape(client, monkeypatch):
    _patch_identity_dependencies(
        monkeypatch,
        FakeUsers(User(id=1, email="user@example.com", password_hash=None)),
    )

    resp = client.post("/auth/check-email", json={"email": "user@example.com"})

    assert resp.status_code == 200
    assert resp.get_json() == {
        "exists": True,
        "registered": False,
        "message": "Email found. Please complete registration.",
    }


def test_register_success_sets_cookies_and_no_body_token(client, monkeypatch):
    users = FakeUsers(User(id=1, email="user@example.com", password_hash=None))
    _patch_identity_dependencies(monkeypatch, users)

    resp = client.post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "a" * 12,
            "first_name": "A",
            "last_name": "B",
        },
    )

    assert resp.status_code == 201
    body = resp.get_json()
    assert "token" not in body
    assert body["user"] == {
        "id": 1,
        "email": "user@example.com",
        "first_name": "A",
        "last_name": "B",
        "role": "general_member",
    }
    assert users.completed == ("user@example.com", "hashed:" + "a" * 12, "A", "B")
    _assert_session_cookies(resp)


def test_register_unauthorized_email_maps_to_403(client, monkeypatch):
    _patch_identity_dependencies(monkeypatch, FakeUsers(user=None))

    resp = client.post(
        "/auth/register",
        json={
            "email": "missing@example.com",
            "password": "a" * 12,
            "first_name": "A",
            "last_name": "B",
        },
    )

    assert resp.status_code == 403
    assert resp.get_json() == {
        "error": "Email not authorized. Contact an administrator."
    }


def test_register_already_registered_maps_to_400(client, monkeypatch):
    _patch_identity_dependencies(
        monkeypatch,
        FakeUsers(User(id=1, email="user@example.com", password_hash="hashed")),
    )

    resp = client.post(
        "/auth/register",
        json={
            "email": "user@example.com",
            "password": "a" * 12,
            "first_name": "A",
            "last_name": "B",
        },
    )

    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Account already registered. Please login."}


def test_verify_user_not_found_maps_to_404(client, monkeypatch):
    monkeypatch.delenv("DEV_MODE", raising=False)
    user = User(
        id=7,
        email="user@example.com",
        first_name="A",
        last_name="B",
        role="general_member",
        password_hash="hashed",
    )
    _patch_identity_dependencies(monkeypatch, FakeUsers(user), FakeHasher(valid=True))
    client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "a" * 12},
    )
    _patch_identity_dependencies(monkeypatch, FakeUsers(user=None))

    resp = client.get("/auth/verify")

    assert resp.status_code == 404
    assert resp.get_json() == {"error": "User not found"}


def test_dev_verify_returns_synthetic_user_without_db(client, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "development")
    _patch_identity_dependencies(monkeypatch, FakeUsers(user=None))
    client.post("/auth/dev-login")

    resp = client.get("/auth/verify")

    assert resp.status_code == 200
    assert resp.get_json()["user"]["email"] == "dev@algolens.local"


def test_dev_login_invalid_user_id_falls_back_to_1(client, monkeypatch):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("DEV_USER_ID", "not-an-int")

    resp = client.post("/auth/dev-login")

    assert resp.status_code == 200
    assert resp.get_json()["user"]["id"] == 1

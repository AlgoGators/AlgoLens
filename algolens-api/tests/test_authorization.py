"""Authorization tests for member-only incubation endpoints."""

import pytest
from flask_jwt_extended import create_access_token

from app import app


class EmptyIncubationReader:
    called = False

    def list_incubating_strategies(self):
        self.called = True
        return []


def _set_jwt_cookie(client, role, identity="1"):
    claims = {} if role is None else {"role": role}
    with app.app_context():
        token = create_access_token(identity=identity, additional_claims=claims)
    client.set_cookie("access_token_cookie", token)


@pytest.fixture
def incubation_reader(monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    reader = EmptyIncubationReader()
    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (object(), reader),
    )
    return reader


@pytest.mark.parametrize(
    "role",
    [None, "subscriber_individual", "subscriber_professional", "unknown"],
)
def test_non_internal_roles_are_refused_incubation_access(
    client, current_users, incubation_reader, role
):
    current_users.set("1", role=role)
    _set_jwt_cookie(client, role)

    response = client.get("/portfolio/incubation")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Insufficient permissions"


@pytest.mark.parametrize("role", [None, "subscriber_individual", "unknown"])
def test_non_internal_roles_are_refused_lifecycle_history(
    client, current_users, incubation_reader, role
):
    current_users.set("1", role=role)
    _set_jwt_cookie(client, role)

    response = client.get("/portfolio/strategies/trend/lifecycle/history")

    assert response.status_code == 403
    assert response.get_json() == {"error": "Insufficient permissions"}
    assert incubation_reader.called is False


@pytest.mark.parametrize("role", ["admin", "general_member"])
def test_internal_roles_can_access_incubation(
    client, current_users, incubation_reader, role
):
    current_users.set("1", role=role)
    _set_jwt_cookie(client, role)

    response = client.get("/portfolio/incubation")

    assert response.status_code == 200
    assert response.get_json() == {"incubating_strategies": []}


def test_stale_admin_token_is_refused_after_current_role_is_demoted(
    client, current_users, incubation_reader
):
    current_users.set("1", role="subscriber_individual")
    _set_jwt_cookie(client, "admin")

    response = client.get("/portfolio/incubation")

    assert response.status_code == 403
    assert response.get_json() == {"error": "Insufficient permissions"}
    assert incubation_reader.called is False


def test_deleted_current_user_is_refused_even_with_admin_token(
    client, current_users, incubation_reader
):
    _set_jwt_cookie(client, "admin")

    response = client.get("/portfolio/incubation")

    assert response.status_code == 403
    assert response.get_json() == {"error": "Insufficient permissions"}
    assert incubation_reader.called is False


def test_current_admin_is_allowed_despite_stale_subscriber_claim(
    client, current_users, incubation_reader
):
    current_users.set("1", role="admin")
    _set_jwt_cookie(client, "subscriber_professional")

    response = client.get("/portfolio/incubation")

    assert response.status_code == 200
    assert response.get_json() == {"incubating_strategies": []}
    assert incubation_reader.called is True


@pytest.mark.parametrize(
    "row",
    [
        {"email": "null-role@algolens.local", "role": None},
        {"email": "missing-role@algolens.local"},
        {"email": "unknown-role@algolens.local", "role": "future_role"},
    ],
    ids=["null-role", "missing-role", "unknown-role"],
)
def test_invalid_current_role_is_refused(
    client, current_users, incubation_reader, row
):
    current_users.set_row("1", row)
    _set_jwt_cookie(client, "admin")

    response = client.get("/portfolio/incubation")

    assert response.status_code == 403
    assert response.get_json() == {"error": "Insufficient permissions"}
    assert incubation_reader.called is False


def test_current_user_lookup_failure_is_safe_500_without_running_handler(
    client, current_users, incubation_reader
):
    current_users.error = RuntimeError(
        "relation auth.users missing; password=do-not-disclose"
    )
    _set_jwt_cookie(client, "admin")

    response = client.get("/portfolio/incubation")

    assert response.status_code == 500
    assert response.get_json() == {"error": "Authorization check failed"}
    assert "password" not in response.get_data(as_text=True)
    assert "auth.users" not in response.get_data(as_text=True)
    assert incubation_reader.called is False


def test_controlled_dev_identity_uses_its_configured_current_role(
    client, incubation_reader, monkeypatch
):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("DEV_USER_ID", "41")
    monkeypatch.setenv("DEV_USER_ROLE", "admin")

    login = client.post("/auth/dev-login")
    response = client.get("/portfolio/incubation")

    assert login.status_code == 200
    assert response.status_code == 200
    assert incubation_reader.called is True


def test_dev_mode_does_not_bypass_lookup_for_a_different_subject(
    client, incubation_reader, monkeypatch
):
    monkeypatch.setenv("DEV_MODE", "1")
    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("DEV_USER_ID", "41")
    monkeypatch.setenv("DEV_USER_ROLE", "admin")
    _set_jwt_cookie(client, "admin", identity="99")

    response = client.get("/portfolio/incubation")

    assert response.status_code == 403
    assert response.get_json() == {"error": "Insufficient permissions"}
    assert incubation_reader.called is False

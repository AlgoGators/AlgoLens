"""Authorization tests for member-only incubation endpoints."""

import pytest
from flask_jwt_extended import create_access_token

from app import app


class EmptyIncubationReader:
    def list_incubating_strategies(self):
        return []


def _set_jwt_cookie(client, role):
    claims = {} if role is None else {"role": role}
    with app.app_context():
        token = create_access_token(identity="1", additional_claims=claims)
    client.set_cookie("access_token_cookie", token)


@pytest.fixture(autouse=True)
def stub_portfolio_dependencies(monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (object(), EmptyIncubationReader()),
    )


@pytest.mark.parametrize(
    "role",
    [None, "subscriber_individual", "subscriber_professional", "unknown"],
)
def test_non_internal_roles_are_refused_incubation_access(client, role):
    _set_jwt_cookie(client, role)

    response = client.get("/portfolio/incubation")

    assert response.status_code == 403
    assert response.get_json()["error"] == "Insufficient permissions"


@pytest.mark.parametrize("role", ["admin", "exec_board", "general_member"])
def test_internal_roles_can_access_incubation(client, role):
    _set_jwt_cookie(client, role)

    response = client.get("/portfolio/incubation")

    assert response.status_code == 200
    assert response.get_json() == {"incubating_strategies": []}


@pytest.mark.parametrize("role", ["admin", "exec_board"])
def test_exec_roles_fall_back_to_the_qt_screen(role):
    """Before migration 003 (and in its backfill) exec gets the desk."""
    from algolens.domain.identity.screens import QT, legacy_screens

    assert QT in legacy_screens(role)


@pytest.mark.parametrize("role", [None, "", "general_member", "team_lead", "investor", "viewer"])
def test_other_roles_do_not_fall_back_to_the_qt_screen(role):
    from algolens.domain.identity.screens import QT, legacy_screens

    assert QT not in legacy_screens(role)

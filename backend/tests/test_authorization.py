"""Authorization tests for internal-only endpoints.

Routes that write the trading book or read the fund's override reasoning must be
restricted to internal roles (admin, general_member). Subscriber roles are external
paying customers and must be default-denied.
"""

import pytest
from flask_jwt_extended import create_access_token
from app import app


@pytest.fixture
def client():
    """Flask test client with app context."""
    app.config["TESTING"] = True
    with app.app_context():
        yield app.test_client()


def _token_for_role(role):
    """Create a JWT token with the specified role."""
    with app.app_context():
        return create_access_token(identity="1", additional_claims={"role": role})


def test_subscriber_professional_is_refused_post_positions_403(client):
    """Subscriber roles must not write positions."""
    token = _token_for_role("subscriber_professional")
    response = client.post(
        "/portfolio/positions",
        json={
            "strategy_id": "trendfollowing",
            "symbol": "ES",
            "quantity": 10,
            "reason": "test",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json["error"] == "Insufficient permissions"


def test_subscriber_professional_is_refused_get_overrides_403(client):
    """Subscriber roles must not read the override audit trail."""
    token = _token_for_role("subscriber_professional")
    response = client.get(
        "/portfolio/overrides/trendfollowing",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json["error"] == "Insufficient permissions"


def test_subscriber_enterprise_is_refused_post_positions_403(client):
    """All subscriber variants are refused."""
    token = _token_for_role("subscriber_enterprise")
    response = client.post(
        "/portfolio/positions",
        json={
            "strategy_id": "trendfollowing",
            "symbol": "ES",
            "quantity": 10,
            "reason": "test",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_subscriber_individual_is_refused_post_positions_403(client):
    """All subscriber variants are refused."""
    token = _token_for_role("subscriber_individual")
    response = client.post(
        "/portfolio/positions",
        json={
            "strategy_id": "trendfollowing",
            "symbol": "ES",
            "quantity": 10,
            "reason": "test",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_absent_role_claim_is_refused_403(client):
    """Default-deny: an unrecognized or missing role is locked out."""
    with app.app_context():
        token = create_access_token(identity="1", additional_claims={})
    response = client.post(
        "/portfolio/positions",
        json={
            "strategy_id": "trendfollowing",
            "symbol": "ES",
            "quantity": 10,
            "reason": "test",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json["error"] == "Insufficient permissions"


def test_absent_role_claim_is_refused_on_get_overrides_403(client):
    """Default-deny applies to read endpoints too."""
    with app.app_context():
        token = create_access_token(identity="1", additional_claims={})
    response = client.get(
        "/portfolio/overrides/trendfollowing",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


def test_admin_role_is_not_refused_post_positions(client):
    """Internal roles (admin, general_member) bypass the authorization gate."""
    token = _token_for_role("admin")
    response = client.post(
        "/portfolio/positions",
        json={
            "strategy_id": "trendfollowing",
            "symbol": "ES",
            "quantity": 10,
            "reason": "test",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # The gate lets admin through. We don't assert the exact status code because
    # it may be 201 (success), 404 (strategy not found in test db), 409 (risk gate),
    # or 400 (validation error). The point is: NOT 403.
    assert response.status_code != 403


def test_general_member_role_is_not_refused_post_positions(client):
    """Internal roles (admin, general_member) bypass the authorization gate."""
    token = _token_for_role("general_member")
    response = client.post(
        "/portfolio/positions",
        json={
            "strategy_id": "trendfollowing",
            "symbol": "ES",
            "quantity": 10,
            "reason": "test",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # The gate lets general_member through.
    assert response.status_code != 403


def test_admin_is_not_refused_get_overrides(client):
    """Internal roles are not refused on read endpoints."""
    token = _token_for_role("admin")
    response = client.get(
        "/portfolio/overrides/trendfollowing",
        headers={"Authorization": f"Bearer {token}"},
    )
    # The gate lets admin through. It may be 404 (strategy not found) but not 403.
    assert response.status_code != 403

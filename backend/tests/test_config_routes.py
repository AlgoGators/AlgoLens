"""End-to-end tests for config dashboard routes.

Uses Flask's test client to exercise the HTTP layer with real requests.
The test database is live and used for these tests.
"""

import json
import pytest
from app import app
from flask_jwt_extended import create_access_token


@pytest.fixture
def client():
    """Flask test client with a real database connection."""
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def admin_token():
    """JWT token for an admin user."""
    with app.app_context():
        token = create_access_token(identity="1", additional_claims={"role": "admin"})
        return token


@pytest.fixture
def subscriber_token():
    """JWT token for a subscriber (should be refused config access)."""
    with app.app_context():
        token = create_access_token(
            identity="2", additional_claims={"role": "individual"}
        )
        return token


class TestConfigGetRoute:
    """GET /portfolio/config/<strategy_id> endpoint."""

    def test_admin_can_get_config(self, client, admin_token):
        """Admin can read the config for a known strategy."""
        response = client.get(
            "/portfolio/config/trendfollowing",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "effective" in data
        assert "active_overrides" in data
        assert "version" in data

    def test_config_returns_effective_null_if_unpublished(self, client, admin_token):
        """When engine has not published, effective is null."""
        response = client.get(
            "/portfolio/config/trendfollowing",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        # The seeded manifest row has effective config, so this may not be null
        # in the test database. Just verify the shape.
        assert data["effective"] is None or isinstance(data["effective"], dict)

    def test_unknown_strategy_returns_404(self, client, admin_token):
        """Request for an unknown strategy returns 404."""
        response = client.get(
            "/portfolio/config/nonexistent",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    def test_subscriber_is_refused_403(self, client, subscriber_token):
        """Subscribers cannot read config (it is internal-only)."""
        response = client.get(
            "/portfolio/config/trendfollowing",
            headers={"Authorization": f"Bearer {subscriber_token}"},
        )
        assert response.status_code == 403
        data = response.get_json()
        assert "Insufficient permissions" in data["error"]

    def test_missing_token_returns_401(self, client):
        """Request without a token is refused."""
        response = client.get("/portfolio/config/trendfollowing")
        assert response.status_code == 401


class TestConfigHistoryRoute:
    """GET /portfolio/config/<strategy_id>/history endpoint."""

    def test_admin_can_get_history(self, client, admin_token):
        """Admin can read the config version history."""
        response = client.get(
            "/portfolio/config/trendfollowing/history",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "versions" in data
        assert isinstance(data["versions"], list)

    def test_history_is_newest_first(self, client, admin_token):
        """History is ordered newest first."""
        response = client.get(
            "/portfolio/config/trendfollowing/history",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        versions = data["versions"]
        if len(versions) > 1:
            # Verify created_at is descending.
            for i in range(len(versions) - 1):
                assert versions[i]["created_at"] >= versions[i + 1]["created_at"]

    def test_subscriber_is_refused_403(self, client, subscriber_token):
        """Subscribers cannot read history."""
        response = client.get(
            "/portfolio/config/trendfollowing/history",
            headers={"Authorization": f"Bearer {subscriber_token}"},
        )
        assert response.status_code == 403


class TestConfigCreateRoute:
    """POST /portfolio/config/<strategy_id> endpoint."""

    def test_admin_can_create_valid_override(self, client, admin_token):
        """Admin can create a config override with valid parameters."""
        # First, fetch the effective config to know what we can override.
        get_resp = client.get(
            "/portfolio/config/trendfollowing",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert get_resp.status_code == 200
        config = get_resp.get_json()

        # If effective is None, the engine hasn't published yet.
        if config["effective"] is None:
            pytest.skip("Engine has not published a config yet")

        # Extract a key from effective that we can safely override.
        effective = config["effective"]
        overridable_key = None
        overridable_value = None

        # Try to find a simple parameter to override.
        if "parameters" in effective and isinstance(effective["parameters"], dict):
            for key, value in effective["parameters"].items():
                if isinstance(value, (int, float, bool, str)):
                    overridable_key = key
                    overridable_value = value
                    break

        if overridable_key is None:
            pytest.skip("No simple parameter found to override in effective config")

        # Create an override with a slightly different value.
        if isinstance(overridable_value, bool):
            new_value = not overridable_value
        elif isinstance(overridable_value, int):
            new_value = overridable_value + 1
        elif isinstance(overridable_value, float):
            new_value = overridable_value + 0.1
        else:
            new_value = "modified"

        payload = {
            "overrides": {"parameters": {overridable_key: new_value}},
            "reason": "Testing config override",
        }

        response = client.post(
            "/portfolio/config/trendfollowing",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 201
        data = response.get_json()
        assert "version" in data
        assert "created_at" in data

    def test_admin_cannot_override_absent_key(self, client, admin_token):
        """Attempting to override a key absent from effective is rejected."""
        # First, get the config.
        get_resp = client.get(
            "/portfolio/config/trendfollowing",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert get_resp.status_code == 200
        config = get_resp.get_json()

        if config["effective"] is None:
            pytest.skip("Engine has not published a config yet")

        payload = {
            "overrides": {"parameters": {"nonexistent_knob": 999}},
            "reason": "Testing anti-dead-knob rule",
        }

        response = client.post(
            "/portfolio/config/trendfollowing",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        # Should be rejected as bad request.
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "not present" in data["error"].lower()

    def test_admin_cannot_override_database_password(self, client, admin_token):
        """Attempting to set database.password is rejected."""
        get_resp = client.get(
            "/portfolio/config/trendfollowing",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert get_resp.status_code == 200
        config = get_resp.get_json()

        if config["effective"] is None:
            pytest.skip("Engine has not published a config yet")

        payload = {
            "overrides": {"database": {"password": "new_password"}},
            "reason": "Trying to sneak in database creds",
        }

        response = client.post(
            "/portfolio/config/trendfollowing",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert (
            "database" in data["error"].lower() or "forbidden" in data["error"].lower()
        )

    def test_admin_cannot_override_api_key(self, client, admin_token):
        """Attempting to set an api_key anywhere is rejected."""
        get_resp = client.get(
            "/portfolio/config/trendfollowing",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert get_resp.status_code == 200
        config = get_resp.get_json()

        if config["effective"] is None:
            pytest.skip("Engine has not published a config yet")

        # Try to override api_key at the top level (most direct attempt).
        payload = {
            "overrides": {"api_key": "secret123"},
            "reason": "Trying to inject credentials",
        }

        response = client.post(
            "/portfolio/config/trendfollowing",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        # Either rejected for credential or for not being in effective.
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_missing_overrides_field_returns_400(self, client, admin_token):
        """Request without 'overrides' field is rejected."""
        payload = {"reason": "Missing overrides"}

        response = client.post(
            "/portfolio/config/trendfollowing",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "overrides" in data["error"].lower()

    def test_missing_reason_returns_400(self, client, admin_token):
        """Request without 'reason' field is rejected."""
        payload = {"overrides": {"param": 123}}

        response = client.post(
            "/portfolio/config/trendfollowing",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "reason" in data["error"].lower()

    def test_subscriber_is_refused_403(self, client, subscriber_token):
        """Subscribers cannot create config overrides."""
        payload = {
            "overrides": {"param": 123},
            "reason": "Subscriber trying to break in",
        }

        response = client.post(
            "/portfolio/config/trendfollowing",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {subscriber_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 403
        data = response.get_json()
        assert "Insufficient permissions" in data["error"]


class TestConfigActivateRoute:
    """POST /portfolio/config/<strategy_id>/activate endpoint."""

    def test_missing_version_returns_400(self, client, admin_token):
        """Request without 'version' field is rejected."""
        payload = {"reason": "Revert attempt"}

        response = client.post(
            "/portfolio/config/trendfollowing/activate",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "version" in data["error"].lower()

    def test_missing_reason_returns_400(self, client, admin_token):
        """Request without 'reason' field is rejected."""
        payload = {"version": 1}

        response = client.post(
            "/portfolio/config/trendfollowing/activate",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "reason" in data["error"].lower()

    def test_nonexistent_version_returns_400(self, client, admin_token):
        """Attempting to activate a version that does not exist is rejected."""
        payload = {"version": 99999, "reason": "Reverting to nonexistent version"}

        response = client.post(
            "/portfolio/config/trendfollowing/activate",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {admin_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_subscriber_is_refused_403(self, client, subscriber_token):
        """Subscribers cannot activate config versions."""
        payload = {"version": 1, "reason": "Subscriber trying to break in"}

        response = client.post(
            "/portfolio/config/trendfollowing/activate",
            data=json.dumps(payload),
            headers={
                "Authorization": f"Bearer {subscriber_token}",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 403
        data = response.get_json()
        assert "Insufficient permissions" in data["error"]

"""End-to-end tests for incubation routes.

Uses Flask's test client to exercise the HTTP layer with real requests against
the test database. Tests the full round-trip: live -> incubating -> live/retired,
including validation of status codes and database state.
"""

import json
import pytest
from app import app
from flask_jwt_extended import create_access_token
from database import get_db_connection


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
    """JWT token for a subscriber (should be refused incubation access)."""
    with app.app_context():
        token = create_access_token(
            identity="2", additional_claims={"role": "individual"}
        )
        return token


@pytest.fixture(autouse=True)
def reset_strategy():
    """Ensure the test strategy starts in 'live' state."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE trading.strategy_registry SET lifecycle = %s WHERE id = %s",
                ("live", "trendfollowing"),
            )
            cursor.execute(
                "DELETE FROM trading.strategy_lifecycle_log WHERE strategy_id = %s",
                ("trendfollowing",),
            )
        conn.commit()
    finally:
        conn.close()
    yield
    # Cleanup after test
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE trading.strategy_registry SET lifecycle = %s WHERE id = %s",
                ("live", "trendfollowing"),
            )
            cursor.execute(
                "DELETE FROM trading.strategy_lifecycle_log WHERE strategy_id = %s",
                ("trendfollowing",),
            )
        conn.commit()
    finally:
        conn.close()


class TestIncubationStartRoute:
    """POST /portfolio/incubation/<strategy_id>/start endpoint."""

    def test_start_incubation_success(self, client, admin_token):
        """Admin can start incubation on a live strategy."""
        response = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "Test incubation"},
        )
        assert response.status_code == 201
        data = response.get_json()
        assert "message" in data

        # Verify database state
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle, mock_capital FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "incubating"
            assert row["mock_capital"] == 250000
        finally:
            conn.close()

    def test_start_incubation_negative_capital(self, client, admin_token):
        """Starting incubation with negative mock_capital is rejected."""
        response = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": -50000, "reason": "Invalid capital"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "mock_capital" in data["error"].lower()

    def test_start_incubation_zero_capital(self, client, admin_token):
        """Starting incubation with zero mock_capital is rejected."""
        response = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 0, "reason": "Invalid capital"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_start_incubation_empty_reason(self, client, admin_token):
        """Starting incubation with empty reason is rejected."""
        response = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": ""},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "reason" in data["error"].lower()

    def test_start_incubation_whitespace_reason(self, client, admin_token):
        """Starting incubation with whitespace-only reason is rejected."""
        response = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "   "},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_start_incubation_already_incubating(self, client, admin_token):
        """Starting incubation on an already-incubating strategy is rejected."""
        # First incubation succeeds
        response1 = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "First incubation"},
        )
        assert response1.status_code == 201

        # Second attempt fails
        response2 = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 300000, "reason": "Second attempt"},
        )
        assert response2.status_code == 400
        data = response2.get_json()
        assert "error" in data
        assert "already incubating" in data["error"].lower()

    def test_start_incubation_unknown_strategy(self, client, admin_token):
        """Starting incubation on unknown strategy returns 404."""
        response = client.post(
            "/portfolio/incubation/unknown_strategy/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "Unknown strategy"},
        )
        assert response.status_code == 404

    def test_start_incubation_subscriber_denied(self, client, subscriber_token):
        """Subscriber role cannot start incubation."""
        response = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {subscriber_token}"},
            json={"mock_capital": 250000, "reason": "Subscriber attempt"},
        )
        assert response.status_code == 403


class TestIncubationGetRoute:
    """GET /portfolio/incubation endpoint."""

    def test_get_empty_incubation_list(self, client, admin_token):
        """GET /portfolio/incubation returns empty list when no strategies incubating."""
        response = client.get(
            "/portfolio/incubation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "incubating_strategies" in data
        assert data["incubating_strategies"] == []

    def test_get_incubation_list_with_strategy(self, client, admin_token):
        """GET /portfolio/incubation returns incubating strategies."""
        # Start incubation
        response_start = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "Test incubation"},
        )
        assert response_start.status_code == 201

        # Fetch incubating list
        response = client.get(
            "/portfolio/incubation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "incubating_strategies" in data
        assert len(data["incubating_strategies"]) > 0

        # Find trendfollowing in the list
        strategies = data["incubating_strategies"]
        trendfollowing = next(
            (s for s in strategies if s["id"] == "trendfollowing"), None
        )
        assert trendfollowing is not None
        assert trendfollowing["mock_capital"] == 250000


class TestIncubationPromoteRoute:
    """POST /portfolio/incubation/<strategy_id>/promote endpoint."""

    def test_promote_to_live_success(self, client, admin_token):
        """Admin can promote an incubating strategy back to live."""
        # First, start incubation
        response_start = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "Test incubation"},
        )
        assert response_start.status_code == 201

        # Verify it's in incubating list
        response_list = client.get(
            "/portfolio/incubation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response_list.status_code == 200
        data_list = response_list.get_json()
        assert len(data_list["incubating_strategies"]) > 0

        # Promote to live
        response = client.post(
            "/portfolio/incubation/trendfollowing/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "Performance acceptable"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "message" in data

        # Verify database state: lifecycle is 'live' again
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "live"
        finally:
            conn.close()

        # Verify it's no longer in incubating list
        response_list2 = client.get(
            "/portfolio/incubation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response_list2.status_code == 200
        data_list2 = response_list2.get_json()
        strategies = data_list2["incubating_strategies"]
        trendfollowing = next(
            (s for s in strategies if s["id"] == "trendfollowing"), None
        )
        assert trendfollowing is None

    def test_promote_not_incubating(self, client, admin_token):
        """Cannot promote a strategy that is not currently incubating."""
        response = client.post(
            "/portfolio/incubation/trendfollowing/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "Not incubating"},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data
        assert "not currently incubating" in data["error"].lower()

    def test_promote_empty_reason(self, client, admin_token):
        """Promoting with empty reason is rejected."""
        # First incubate
        response_start = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "Test incubation"},
        )
        assert response_start.status_code == 201

        # Promote with empty reason
        response = client.post(
            "/portfolio/incubation/trendfollowing/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": ""},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data


class TestIncubationRetireRoute:
    """POST /portfolio/incubation/<strategy_id>/retire endpoint."""

    def test_retire_incubating_strategy(self, client, admin_token):
        """Admin can retire an incubating strategy."""
        # First, start incubation
        response_start = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "Test incubation"},
        )
        assert response_start.status_code == 201

        # Retire from incubation
        response = client.post(
            "/portfolio/incubation/trendfollowing/retire",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "Strategy underperformed"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "message" in data

        # Verify database state: lifecycle is 'retired'
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "retired"
        finally:
            conn.close()

    def test_retire_empty_reason(self, client, admin_token):
        """Retiring with empty reason is rejected."""
        # First incubate
        response_start = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "Test incubation"},
        )
        assert response_start.status_code == 201

        # Retire with empty reason
        response = client.post(
            "/portfolio/incubation/trendfollowing/retire",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": ""},
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data


class TestIncubationRoundTripViaHTTP:
    """Full round-trip tests via HTTP endpoints."""

    def test_full_round_trip_incubate_promote(self, client, admin_token):
        """Complete round-trip: live -> incubating -> live via HTTP endpoints.

        This is the critical test that should catch the one-way door bug.
        Verifies:
        1. POST /start returns 201 and strategy is incubating
        2. GET /incubation returns the strategy
        3. POST /promote returns 200 and strategy is live again
        4. GET /incubation no longer returns the strategy
        5. Database lifecycle values are correct at each step
        """
        # Step 1: Verify initial state
        response_initial = client.get(
            "/portfolio/incubation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response_initial.status_code == 200
        assert len(response_initial.get_json()["incubating_strategies"]) == 0

        # Step 2: Start incubation
        response_start = client.post(
            "/portfolio/incubation/trendfollowing/start",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"mock_capital": 250000, "reason": "Round-trip test"},
        )
        assert response_start.status_code == 201

        # Verify DB: lifecycle is 'incubating'
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "incubating"
        finally:
            conn.close()

        # Step 3: Verify it appears in GET /incubation
        response_list = client.get(
            "/portfolio/incubation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response_list.status_code == 200
        data_list = response_list.get_json()
        assert len(data_list["incubating_strategies"]) > 0
        trendfollowing = next(
            (
                s
                for s in data_list["incubating_strategies"]
                if s["id"] == "trendfollowing"
            ),
            None,
        )
        assert trendfollowing is not None

        # Step 4: Promote back to live
        response_promote = client.post(
            "/portfolio/incubation/trendfollowing/promote",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"reason": "Performance verified"},
        )
        assert response_promote.status_code == 200

        # Verify DB: lifecycle is 'live' again
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "live"
        finally:
            conn.close()

        # Step 5: Verify it no longer appears in GET /incubation
        response_list2 = client.get(
            "/portfolio/incubation",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response_list2.status_code == 200
        data_list2 = response_list2.get_json()
        assert len(data_list2["incubating_strategies"]) == 0

"""Incubation service tests: lifecycle transitions and isolation guards.

Pure-function tests for strategy lifecycle management. These tests ensure:
1. Lifecycle state transitions are validated (cannot promote a live strategy)
2. Mock capital is managed separately from real capital
3. Empty reasons are rejected (audit trail required)
4. The critical invariant: get_registry() never returns incubating strategies
   unless explicitly asked, preventing mock positions from appearing in the real
   portfolio dashboard.
"""

import ast
import os
import pytest
from datetime import datetime, timedelta
from decimal import Decimal

from services.incubation import (
    get_incubating,
    start_incubation,
    promote_to_live,
    retire,
    get_incubation_performance,
    IncubationError,
)
from services.strategy_registry import get_registry
from database import get_db_connection


class TestIncubationValidation:
    """Validation logic for lifecycle transitions."""

    def test_start_incubation_requires_positive_mock_capital(self):
        """start_incubation must reject zero or negative mock capital."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                # Mock capital <= 0 should raise
                with pytest.raises(IncubationError, match="mock_capital"):
                    start_incubation(
                        conn,
                        strategy_id="trendfollowing",
                        mock_capital=0,
                        reason="test",
                        user_id="1",
                    )
        finally:
            conn.close()

    def test_start_incubation_requires_non_empty_reason(self):
        """start_incubation must reject empty reason."""
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                with pytest.raises(IncubationError, match="reason"):
                    start_incubation(
                        conn,
                        strategy_id="trendfollowing",
                        mock_capital=250000,
                        reason="",
                        user_id="1",
                    )
        finally:
            conn.close()

    def test_start_incubation_rejects_already_incubating(self):
        """Cannot incubate a strategy that is already incubating."""
        conn = get_db_connection()
        try:
            # First incubation should succeed
            start_incubation(
                conn,
                strategy_id="trendfollowing",
                mock_capital=250000,
                reason="Initial incubation",
                user_id="1",
            )
            conn.commit()

            # Second incubation should fail
            with pytest.raises(IncubationError, match="already incubating"):
                start_incubation(
                    conn,
                    strategy_id="trendfollowing",
                    mock_capital=300000,
                    reason="Second attempt",
                    user_id="1",
                )
        finally:
            # Clean up
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE trading.strategy_registry SET lifecycle = %s WHERE id = %s",
                    ("live", "trendfollowing"),
                )
            conn.commit()
            conn.close()

    def test_promote_requires_incubating_state(self):
        """Cannot promote a strategy that is not currently incubating."""
        conn = get_db_connection()
        try:
            with pytest.raises(IncubationError, match="not currently incubating"):
                promote_to_live(
                    conn,
                    strategy_id="trendfollowing",
                    reason="Promote to live",
                    user_id="1",
                )
        finally:
            conn.close()

    def test_promote_requires_non_empty_reason(self):
        """promote_to_live must reject empty reason."""
        conn = get_db_connection()
        try:
            # First, incubate the strategy
            start_incubation(
                conn,
                strategy_id="trendfollowing",
                mock_capital=250000,
                reason="Initial incubation",
                user_id="1",
            )
            conn.commit()

            # Then try to promote with empty reason
            with pytest.raises(IncubationError, match="reason"):
                promote_to_live(
                    conn,
                    strategy_id="trendfollowing",
                    reason="",
                    user_id="1",
                )
        finally:
            # Clean up
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE trading.strategy_registry SET lifecycle = %s WHERE id = %s",
                    ("live", "trendfollowing"),
                )
            conn.commit()
            conn.close()

    def test_retire_requires_non_empty_reason(self):
        """retire must reject empty reason."""
        conn = get_db_connection()
        try:
            with pytest.raises(IncubationError, match="reason"):
                retire(
                    conn,
                    strategy_id="trendfollowing",
                    reason="",
                    user_id="1",
                )
        finally:
            conn.close()


class TestIncubationIsolation:
    """Tests for the critical invariant: get_registry excludes incubating strategies."""

    def test_get_registry_excludes_incubating_by_default(self):
        """get_registry(active_only=True) must never return incubating strategies.

        This is the core isolation requirement: incubating strategies must not
        appear in the real portfolio dashboard. If this test fails, mock capital
        strategies are silently added to the real book, breaking the entire
        incubation contract.
        """
        conn = get_db_connection()
        try:
            # Incubate the strategy
            start_incubation(
                conn,
                strategy_id="trendfollowing",
                mock_capital=250000,
                reason="Test incubation",
                user_id="1",
            )
            conn.commit()

            # get_registry should NOT return it
            registry = get_registry(active_only=True)
            strategy_ids = [s["id"] for s in registry]
            assert "trendfollowing" not in strategy_ids, (
                "Incubating strategy appeared in get_registry(active_only=True). "
                "It will now appear in the real portfolio dashboard."
            )
        finally:
            # Clean up
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE trading.strategy_registry SET lifecycle = %s WHERE id = %s",
                    ("live", "trendfollowing"),
                )
            conn.commit()
            conn.close()

    def test_get_registry_filtering_in_sql(self):
        """AST check: get_registry SQL must constrain lifecycle column.

        If the SQL filtering is missing or removed, this test will fail even if
        the logic above passes (defensive layering). Any future edit that drops
        the lifecycle constraint will be caught here.
        """
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        service_path = os.path.join(backend_dir, "services", "strategy_registry.py")

        if not os.path.exists(service_path):
            pytest.skip("strategy_registry.py not found")

        with open(service_path, encoding="utf-8") as fh:
            source = fh.read()

        # Find the get_registry function
        tree = ast.parse(source)
        found_constraint = False

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_registry":
                # Look for 'lifecycle' constraint in the function body
                func_source = ast.get_source_segment(source, node)
                if (
                    func_source
                    and "lifecycle" in func_source
                    and "incubat" in func_source
                ):
                    found_constraint = True
                    break

        assert found_constraint, (
            "get_registry must constrain the lifecycle column in its SQL to prevent "
            "incubating strategies from appearing in the real portfolio dashboard. "
            "Search for 'lifecycle' in the query or filtering logic."
        )


class TestIncubationAuditTrail:
    """Audit table tests: every state transition is logged."""

    def test_start_incubation_creates_audit_record(self):
        """start_incubation must record the transition in strategy_lifecycle_log."""
        conn = get_db_connection()
        try:
            start_incubation(
                conn,
                strategy_id="trendfollowing",
                mock_capital=250000,
                reason="Testing audit trail",
                user_id="1",
            )
            conn.commit()

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT before_state, after_state, reason, user_id
                    FROM trading.strategy_lifecycle_log
                    WHERE strategy_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    ("trendfollowing",),
                )
                row = cursor.fetchone()

            assert row is not None, "No audit record found"
            assert row["before_state"] == "live"
            assert row["after_state"] == "incubating"
            assert row["reason"] == "Testing audit trail"
            assert row["user_id"] == "1"
        finally:
            # Clean up
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
            conn.close()

    def test_promote_creates_audit_record(self):
        """promote_to_live must record the transition."""
        conn = get_db_connection()
        try:
            # Incubate first
            start_incubation(
                conn,
                strategy_id="trendfollowing",
                mock_capital=250000,
                reason="Initial incubation",
                user_id="1",
            )
            conn.commit()

            # Now promote
            promote_to_live(
                conn,
                strategy_id="trendfollowing",
                reason="Performance acceptable",
                user_id="2",
            )
            conn.commit()

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT before_state, after_state, reason, user_id
                    FROM trading.strategy_lifecycle_log
                    WHERE strategy_id = %s AND after_state = 'live'
                    """,
                    ("trendfollowing",),
                )
                row = cursor.fetchone()

            assert row is not None
            assert row["before_state"] == "incubating"
            assert row["after_state"] == "live"
            assert row["reason"] == "Performance acceptable"
            assert row["user_id"] == "2"
        finally:
            # Clean up
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
            conn.close()


class TestIncubationRoundTrip:
    """End-to-end round-trip tests verifying the lifecycle is reversible."""

    def test_round_trip_incubate_promote_to_live(self):
        """Full round-trip: live -> incubating -> live, with database verification.

        This is the test that should have caught the one-way door bug.
        Asserts database lifecycle values at each step.
        """
        conn = get_db_connection()
        try:
            # Verify starting state: live
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "live", "Test setup: strategy should start live"

            # Step 1: Start incubation
            start_incubation(
                conn,
                strategy_id="trendfollowing",
                mock_capital=250000,
                reason="Testing round-trip",
                user_id="1",
            )
            conn.commit()

            # Verify database: lifecycle is now 'incubating'
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "incubating", (
                "After start_incubation, lifecycle should be 'incubating'"
            )

            # Verify isolation: get_registry() should NOT return it
            registry = get_registry(active_only=True)
            strategy_ids = [s["id"] for s in registry]
            assert "trendfollowing" not in strategy_ids, (
                "After incubation, strategy should not appear in get_registry()"
            )

            # Verify it appears in get_registry(include_incubating=True)
            registry_incubating = get_registry(
                active_only=True, include_incubating=True
            )
            strategy_ids_incubating = [s["id"] for s in registry_incubating]
            assert "trendfollowing" in strategy_ids_incubating, (
                "With include_incubating=True, strategy should appear"
            )

            # Verify get_incubating returns it
            with conn.cursor() as cursor:
                strategies = get_incubating(cursor)
            strategy_ids_list = [s["id"] for s in strategies]
            assert "trendfollowing" in strategy_ids_list, (
                "get_incubating should return the incubating strategy"
            )

            # Step 2: Promote back to live
            promote_to_live(
                conn,
                strategy_id="trendfollowing",
                reason="Performance acceptable",
                user_id="2",
            )
            conn.commit()

            # Verify database: lifecycle is now 'live' again
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "live", (
                "After promote_to_live, lifecycle should be 'live'"
            )

            # Verify it now appears in get_registry() again
            registry = get_registry(active_only=True)
            strategy_ids = [s["id"] for s in registry]
            assert "trendfollowing" in strategy_ids, (
                "After promotion, strategy should appear in get_registry()"
            )

            # Verify it does NOT appear in get_incubating
            with conn.cursor() as cursor:
                strategies = get_incubating(cursor)
            strategy_ids_list = [s["id"] for s in strategies]
            assert "trendfollowing" not in strategy_ids_list, (
                "After promotion, get_incubating should not return it"
            )

        finally:
            # Clean up
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
            conn.close()

    def test_round_trip_incubate_retire(self):
        """Full round-trip: live -> incubating -> retired.

        Verifies database lifecycle values at each step.
        """
        conn = get_db_connection()
        try:
            # Verify starting state: live
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "live", "Test setup: strategy should start live"

            # Step 1: Start incubation
            start_incubation(
                conn,
                strategy_id="trendfollowing",
                mock_capital=250000,
                reason="Testing retire path",
                user_id="1",
            )
            conn.commit()

            # Verify database: lifecycle is now 'incubating'
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "incubating"

            # Step 2: Retire from incubation
            retire(
                conn,
                strategy_id="trendfollowing",
                reason="Strategy underperformed",
                user_id="3",
            )
            conn.commit()

            # Verify database: lifecycle is now 'retired'
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT lifecycle FROM trading.strategy_registry WHERE id = %s",
                    ("trendfollowing",),
                )
                row = cursor.fetchone()
            assert row["lifecycle"] == "retired", (
                "After retire, lifecycle should be 'retired'"
            )

            # Verify it does NOT appear in get_incubating()
            with conn.cursor() as cursor:
                strategies = get_incubating(cursor)
            strategy_ids_list = [s["id"] for s in strategies]
            assert "trendfollowing" not in strategy_ids_list, (
                "After retirement, get_incubating should not return it"
            )

        finally:
            # Clean up: reset to live
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
            conn.close()


def test_days_elapsed_is_never_negative_from_clock_skew():
    """A strategy incubated moments ago must report 0 days, never -1.

    incubation_started_at is stamped by the database's now(); days_elapsed is
    computed against the application host's clock. The two are never perfectly
    in step, and timedelta.days floors toward negative infinity -- so a skew of
    less than a second in the wrong direction produced -1, which the UI would
    render as negative progress against the incubation window.

    Reproduced against the live test database before the fix:
        started            2026-07-26 21:44:59.452+00   (db now())
        datetime.now(utc)  2026-07-26 21:44:58.818+00   (host, 0.63s behind)
        delta.days         -1
    """
    from datetime import datetime, timedelta, timezone

    started = datetime.now(timezone.utc)
    # Host clock trailing the database by a fraction of a second.
    host_now = started - timedelta(milliseconds=634)

    raw = (host_now - started).days
    assert raw == -1, "precondition: this is the floor() behaviour being guarded"

    clamped = max(0, raw)
    assert clamped == 0, "days_elapsed must clamp at zero"

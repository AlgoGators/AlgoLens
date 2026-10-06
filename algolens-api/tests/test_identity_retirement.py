from pathlib import Path

import pytest

from algolens.application.identity.use_cases import (
    CheckEmail,
    EmailNotAuthorized,
    InvalidCredentials,
    Login,
    RegisterUser,
    UserNotFound,
    VerifySession,
)
from algolens.infrastructure.config.dependencies import load_identity_authority_rows
from algolens.infrastructure.identity.repositories import PostgresUserRepository


class RejectingHasher:
    def verify(self, _password_hash, _password):
        raise AssertionError("a retired account must never reach password verification")

    def hash(self, _password):
        raise AssertionError("a retired account must never reach password hashing")


def _retired_lookup(query, params, *, fetch_one=False):
    assert fetch_one is True
    assert "auth.account_retirements" in query
    assert "NOT EXISTS" in query
    assert params in (
        ("domdd305@gmail.com", "domdd305@gmail.com"),
        (405,),
    )
    return None


def test_retired_account_cannot_login_or_restore_an_existing_session():
    users = PostgresUserRepository(execute_query_func=_retired_lookup)

    with pytest.raises(InvalidCredentials):
        Login(users, RejectingHasher()).execute("domdd305@gmail.com", "irrelevant")
    with pytest.raises(UserNotFound):
        VerifySession(users).execute(405)
    assert CheckEmail(users).execute("domdd305@gmail.com").exists is False
    with pytest.raises(EmailNotAuthorized):
        RegisterUser(users, RejectingHasher()).execute(
            "domdd305@gmail.com", "valid-length-password", "Dominick", "Dupuy"
        )


def test_retired_account_cannot_receive_runtime_capabilities():
    calls = []

    def execute(query, params, *, fetch_one=False):
        calls.append((query, params, fetch_one))
        assert "auth.account_retirements" in query
        return [{"user_id": 405}]

    assert load_identity_authority_rows(405, execute_query_func=execute) == ([], [])
    assert len(calls) == 1


def test_active_account_authority_lookup_still_reads_grants_and_mappings():
    def execute(query, params, *, fetch_one=False):
        assert params == (404,)
        if "auth.account_retirements" in query:
            return []
        if "qt_action_grants" in query:
            return [{"capability": "qt_approve", "active": True}]
        if "qt_approver_allowlist" in query:
            return [{"person_id": "dominick_dupuy", "active": True}]
        raise AssertionError(query)

    assert load_identity_authority_rows(404, execute_query_func=execute) == (
        [{"capability": "qt_approve", "active": True}],
        [{"person_id": "dominick_dupuy", "active": True}],
    )


def test_identity_migration_names_only_the_exact_normalized_verified_emails():
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "009_hemdutt_qt_approver.sql"
    ).read_text(encoding="utf-8")

    expected = {
        "john.riley@ufl.edu": "general_member",
        "raohemdutt@ufl.edu": "exec_board",
        "robbins.a@ufl.edu": "general_member",
        "dominickdupuy@ufl.edu": "exec_board",
    }
    for email, role in expected.items():
        assert f"lower(btrim(email)) = '{email}'" in migration
        assert role in migration
    assert "lower(btrim(email)) = 'domdd305@gmail.com'" in migration
    assert "auth.account_retirements" in migration
    assert "UPDATE auth.users" in migration
    assert "SET role = 'exec_board'" in migration
    assert "first_name" not in migration
    assert "last_name" not in migration

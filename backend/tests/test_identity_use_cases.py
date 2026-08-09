import pytest

from algolens.application.identity.use_cases import (
    AccountAlreadyRegistered,
    CheckEmail,
    InvalidCredentials,
    Login,
    RegisterUser,
)
from algolens.domain.identity.models import User


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


def test_login_rejects_invalid_password():
    users = FakeUsers(User(id=1, email="user@example.com", password_hash="hashed"))
    with pytest.raises(InvalidCredentials):
        Login(users, FakeHasher(valid=False)).execute("user@example.com", "wrong")


def test_check_email_preserves_registration_state():
    users = FakeUsers(User(id=1, email="user@example.com", password_hash=None))
    result = CheckEmail(users).execute("user@example.com")
    assert result.exists is True
    assert result.registered is False
    assert result.status_code == 200


def test_register_rejects_already_registered_user():
    users = FakeUsers(User(id=1, email="user@example.com", password_hash="hashed"))
    with pytest.raises(AccountAlreadyRegistered):
        RegisterUser(users, FakeHasher()).execute(
            "user@example.com", "a" * 12, "A", "B"
        )


def test_register_hashes_and_completes_registration():
    users = FakeUsers(User(id=1, email="user@example.com", password_hash=None))
    user = RegisterUser(users, FakeHasher()).execute(
        "user@example.com", "a" * 12, "A", "B"
    )
    assert user.password_hash == "hashed:" + "a" * 12
    assert users.completed == ("user@example.com", "hashed:" + "a" * 12, "A", "B")

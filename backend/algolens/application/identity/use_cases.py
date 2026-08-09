"""Identity use cases."""

from dataclasses import dataclass

from algolens.application.identity.ports import (
    DevAuthConfigPort,
    PasswordHasherPort,
    UserRepositoryPort,
)
from algolens.application.shared.errors import NotFoundError, ValidationError
from algolens.domain.identity.models import User, has_registered_password
from algolens.domain.identity.password_policy import validate_password


class InvalidCredentials(ValidationError):
    """Email/password pair is not valid."""


class PasswordPolicyViolation(ValidationError):
    """Password failed the server-side policy."""


class EmailNotAuthorized(ValidationError):
    """Email is not present in the pre-authorized users table."""


class AccountAlreadyRegistered(ValidationError):
    """The user already has a password set."""


class UserNotFound(NotFoundError):
    """Authenticated subject no longer has a user row."""


class DevLoginUnavailable(NotFoundError):
    """Dev login is disabled for this runtime."""


@dataclass(frozen=True)
class CheckEmailResult:
    exists: bool
    registered: bool
    message: str
    status_code: int


class Login:
    def __init__(self, users: UserRepositoryPort, hasher: PasswordHasherPort):
        self.users = users
        self.hasher = hasher

    def execute(self, email: str, password: str) -> User:
        user = self.users.find_by_email(email)
        if not user or not user.password_hash:
            raise InvalidCredentials()
        if not self.hasher.verify(user.password_hash, password):
            raise InvalidCredentials()
        return user


class VerifySession:
    def __init__(self, users: UserRepositoryPort):
        self.users = users

    def execute(self, user_id: str) -> User:
        user = self.users.find_by_id(user_id)
        if not user:
            raise UserNotFound()
        return user


class CheckEmail:
    def __init__(self, users: UserRepositoryPort):
        self.users = users

    def execute(self, email: str) -> CheckEmailResult:
        user = self.users.find_by_email(email)
        if not user:
            return CheckEmailResult(
                exists=False,
                registered=False,
                message="Email not found. Contact an administrator to be added.",
                status_code=404,
            )

        if has_registered_password(user):
            return CheckEmailResult(
                exists=True,
                registered=True,
                message="Account already registered. Please login.",
                status_code=200,
            )

        return CheckEmailResult(
            exists=True,
            registered=False,
            message="Email found. Please complete registration.",
            status_code=200,
        )


class RegisterUser:
    def __init__(self, users: UserRepositoryPort, hasher: PasswordHasherPort):
        self.users = users
        self.hasher = hasher

    def execute(
        self, email: str, password: str, first_name: str, last_name: str
    ) -> User:
        password_error = validate_password(password)
        if password_error:
            raise PasswordPolicyViolation(password_error)

        user = self.users.find_by_email(email)
        if not user:
            raise EmailNotAuthorized()
        if has_registered_password(user):
            raise AccountAlreadyRegistered()

        hashed_password = self.hasher.hash(password)
        return self.users.complete_registration(
            email, hashed_password, first_name, last_name
        )


class DevLogin:
    def __init__(self, config: DevAuthConfigPort):
        self.config = config

    def execute(self) -> User:
        if not self.config.is_enabled():
            raise DevLoginUnavailable()
        return User(
            id=self.config.user_id(),
            email=self.config.user_email(),
            first_name="Dev",
            last_name="User",
            role=self.config.user_role(),
        )


class Logout:
    def execute(self) -> None:
        return None

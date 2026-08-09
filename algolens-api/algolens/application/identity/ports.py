"""Identity application ports."""

from typing import Protocol

from algolens.domain.identity.models import User


class UserRepositoryPort(Protocol):
    def find_by_email(self, email: str) -> User | None:
        ...

    def find_by_id(self, user_id: str) -> User | None:
        ...

    def complete_registration(
        self, email: str, password_hash: str, first_name: str, last_name: str
    ) -> User:
        ...


class PasswordHasherPort(Protocol):
    def verify(self, password_hash: str, password: str) -> bool:
        ...

    def hash(self, password: str) -> str:
        ...


class DevAuthConfigPort(Protocol):
    def is_enabled(self) -> bool:
        ...

    def user_id(self) -> int:
        ...

    def user_email(self) -> str:
        ...

    def user_role(self) -> str:
        ...

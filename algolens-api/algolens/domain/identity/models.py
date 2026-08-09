"""Identity domain models."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class User:
    id: Any
    email: str
    first_name: str | None = None
    last_name: str | None = None
    role: str = "general_member"
    password_hash: str | None = None


def user_from_row(row: Mapping[str, Any]) -> User:
    return User(
        id=row["id"],
        email=row.get("email", ""),
        first_name=row.get("first_name"),
        last_name=row.get("last_name"),
        role=row.get("role", "general_member"),
        password_hash=row.get("password_hash"),
    )


def has_registered_password(user: User) -> bool:
    return user.password_hash is not None and user.password_hash != ""

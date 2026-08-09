"""Server-side password policy."""

MIN_PASSWORD_LENGTH = 12


def validate_password(password: object) -> str | None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long"
    return None

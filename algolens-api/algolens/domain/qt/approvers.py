"""Override approvers (contract section 6, ruling 11).

Either the VP or the President decides an override request. Their addresses
come from QT_APPROVERS="vp=<email>,president=<email>". The requester may never
decide their own request.
"""

APPROVER_ROLES = ("vp", "president")


def parse_approvers(raw: str) -> dict[str, str]:
    """{"vp": email, "president": email} from the env string.

    Unknown roles and malformed pairs are ignored; addresses are lower-cased
    so the comparison with a login is case-insensitive.
    """
    approvers: dict[str, str] = {}
    for part in (raw or "").split(","):
        role, sep, email = part.partition("=")
        role, email = role.strip().lower(), email.strip().lower()
        if sep and role in APPROVER_ROLES and email:
            approvers[role] = email
    return approvers


def approver_role_for(email: str, approvers: dict[str, str]) -> str | None:
    """The approver role held by `email`, or None.

    One person may hold both roles; the VP role is then reported, which only
    affects the label on the decision row.
    """
    email = (email or "").strip().lower()
    if not email:
        return None
    for role in APPROVER_ROLES:
        if approvers.get(role) == email:
            return role
    return None

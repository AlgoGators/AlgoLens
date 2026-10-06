"""Current, versioned human approval authority; labels never grant access."""
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError

CANONICAL_APPROVERS = frozenset({"xander_robbins", "hemdutt_rao", "dominick_dupuy"})


@dataclass(frozen=True)
class QtApprovedPerson:
    person_id: str
    user_id: int
    mapping_version: int
    grant_version: int


def resolve_approved_person(actor_id: int, tx) -> QtApprovedPerson:
    """Use actual rows captured by ordered authority locks, plus locked book access."""
    authority = tx.approval_authority(actor_id)
    account, grants, mappings = authority["account"], authority["grants"], authority["mappings"]
    capability = tx.capability()
    if (type(actor_id) is not int or actor_id <= 0 or account.get("id") != actor_id
            or account.get("role") not in {"admin", "general_member", "exec_board"}
            or capability.get("enabled") is not True
            or type(capability.get("version")) is not int or capability["version"] <= 0):
        raise QtWorkflowError("authorization_changed")
    active_grants = [row for row in grants if row.get("user_id") == actor_id
                     and row.get("capability") == "qt_approve" and row.get("active") is True]
    active_mappings = [row for row in mappings if row.get("user_id") == actor_id and row.get("active") is True]
    if len(active_grants) != 1:
        raise QtWorkflowError("authorization_changed")
    if (len(active_mappings) != 1 or active_mappings[0].get("person_id") not in CANONICAL_APPROVERS
            or type(active_mappings[0].get("mapping_version")) is not int or active_mappings[0]["mapping_version"] <= 0
            or type(active_grants[0].get("version")) is not int or active_grants[0]["version"] <= 0):
        raise QtWorkflowError("approval_identity_unmapped")
    return QtApprovedPerson(active_mappings[0]["person_id"], actor_id,
                            active_mappings[0]["mapping_version"], active_grants[0]["version"])


def two_person_quorum(approvals: Sequence[QtApprovedPerson | Mapping]) -> bool:
    rows = [asdict(row) if isinstance(row, QtApprovedPerson) else row for row in approvals]
    if len(rows) != 2:
        return False
    return (all(row.get("person_id") in CANONICAL_APPROVERS and type(row.get("user_id")) is int and row["user_id"] > 0
                and all(type(row.get(name)) is int and row[name] > 0 for name in ("mapping_version", "grant_version")) for row in rows)
            and len({row["person_id"] for row in rows}) == 2 and len({row["user_id"] for row in rows}) == 2)


def lock_current_authorities(cursor, user_ids):
    """Match QtTransaction's user/grant/mapping order, including retirement checks.

    Account FOR UPDATE also fences retirement's referencing FK insert. Active
    authority cannot retire without revoking the rows held here first.
    """
    result = {}
    for user_id in sorted(set(user_ids)):
        if type(user_id) is not int or user_id <= 0:
            raise ValueError('invalid_authority_id')
        cursor.execute('SELECT id, role FROM auth.users WHERE id=%s FOR UPDATE', (user_id,))
        account = cursor.fetchone()
        cursor.execute('SELECT user_id FROM auth.account_retirements WHERE user_id=%s', (user_id,))
        retired = cursor.fetchone() is not None
        cursor.execute('SELECT user_id, capability, active, version FROM trading.qt_action_grants '
                       'WHERE user_id=%s ORDER BY capability FOR UPDATE', (user_id,))
        grants = list(cursor.fetchall())
        cursor.execute('SELECT user_id, person_id, active, mapping_version FROM trading.qt_approver_allowlist '
                       'WHERE user_id=%s ORDER BY person_id FOR UPDATE', (user_id,))
        result[user_id] = {'account':dict(account or {}), 'retired':retired,
                           'grants':grants, 'mappings':list(cursor.fetchall())}
    return result

"""Who gets the daily report (Dom, 2026-10-21).

To: the QTs. Cc: the VP and the President, on every report. Nobody on the exclusion list is ever
addressed, however they got on the list. The rules are here so they are tested without a mail
server or a database.

The QTs are an explicit list (REPORT_TO), not everyone with the qt screen: that screen also covers
leadership and test accounts, and the QT group is a named set of people.
"""

from dataclasses import dataclass

from algolens.domain.qt.approvers import APPROVER_ROLES


class NoRecipientsError(ValueError):
    """Every address was excluded or none was configured: nothing may be sent."""


def normalize(address):
    return (address or "").strip().lower()


def parse_address_list(raw):
    """A comma or semicolon separated string -> tuple of lower-cased addresses."""
    parts = (raw or "").replace(";", ",").split(",")
    return tuple(a for a in (normalize(p) for p in parts) if a)


@dataclass(frozen=True)
class Recipients:
    to: tuple
    cc: tuple

    @property
    def everyone(self):
        return self.to + self.cc


def resolve_recipients(to_emails, approvers, excluded=(), extra_to=()):
    """The To and Cc lists, deduplicated, exclusions removed, order stable.

    approvers is {"vp": email, "president": email}. An approver who is also a QT is Cc'd, not
    listed twice. If there is no To address at all the approvers become the To line so the report still
    reaches someone; if nobody is left, NoRecipientsError.
    """
    blocked = {normalize(a) for a in excluded}
    cc = _unique(approvers.get(role) for role in APPROVER_ROLES)
    cc = tuple(a for a in cc if a not in blocked)
    to = tuple(a for a in _unique(list(to_emails) + list(extra_to))
               if a not in blocked and a not in cc)
    if not to and cc:
        to, cc = cc, ()
    if not to:
        raise NoRecipientsError("no recipients left after exclusions")
    return Recipients(to=to, cc=cc)


def _unique(addresses):
    seen, out = set(), []
    for a in addresses:
        a = normalize(a)
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return tuple(out)

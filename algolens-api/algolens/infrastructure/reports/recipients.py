"""Recipient settings from the environment.

REPORT_TO       comma-separated QT addresses (the To line).
QT_APPROVERS    "vp=<email>,president=<email>" (the Cc line); the same variable the desk uses.
REPORT_EXCLUDE  comma-separated addresses that must never be addressed. DEFAULT_EXCLUDED is
                always applied on top, so a missing variable cannot put them back on the list.
"""

import os

from algolens.application.reports.ports import RecipientSource
from algolens.domain.qt.approvers import parse_approvers
from algolens.domain.reports.recipients import parse_address_list

DEFAULT_EXCLUDED = ("dhebrank@msn.com",)  # Dom, 2026-10-21: never email this address


class EnvRecipients(RecipientSource):
    def __init__(self, env=None):
        self.env = os.environ if env is None else env

    def to_emails(self):
        return parse_address_list(self.env.get("REPORT_TO"))

    def approvers(self):
        return parse_approvers(self.env.get("QT_APPROVERS", ""))

    def excluded(self):
        return DEFAULT_EXCLUDED + parse_address_list(self.env.get("REPORT_EXCLUDE"))

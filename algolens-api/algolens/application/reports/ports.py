"""Ports the report worker depends on. Infrastructure implements them."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class QueuedReport:
    id: int
    report_type: str
    portfolio_id: str
    recipients: tuple  # extra To addresses the enqueuer asked for; the rules add the rest
    payload: dict
    attempts: int


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str
    # content-id -> PNG bytes, shown inline where the HTML says cid:<content-id>
    images: dict


class ReportQueue(ABC):
    @abstractmethod
    def claim_next(self):
        """The oldest queued (or retryable failed) report, now marked sending; or None."""

    @abstractmethod
    def mark_sent(self, report_id):
        ...

    @abstractmethod
    def mark_failed(self, report_id, error):
        """Record the error. The row is retried until it runs out of attempts."""


class ReportRenderer(ABC):
    @abstractmethod
    def render_daily(self, report):
        """A RenderedEmail for a DailyReport."""


class RecipientSource(ABC):
    @abstractmethod
    def to_emails(self):
        """The addresses on the To line (the QTs)."""


class Mailer(ABC):
    @abstractmethod
    def send(self, to, cc, email):
        """Deliver a RenderedEmail to the To and Cc addresses, or raise."""

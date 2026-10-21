"""Send the reports trade-ngin has queued."""

import logging
from dataclasses import dataclass

from algolens.domain.reports.daily import ReportPayloadError, parse_daily_report
from algolens.domain.reports.recipients import resolve_recipients

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendSummary:
    sent: int
    failed: int


class SendQueuedReports:
    """Drain the queue: render each report, mail it, record the outcome.

    One bad report never blocks the ones behind it: any failure is recorded on its own row and
    the loop moves on. A payload that cannot be parsed will fail every retry, which is the
    point: the error is on the row for whoever enqueued it.
    """

    def __init__(self, queue, renderer, mailer, recipients, approvers, excluded=(), limit=50):
        self.queue = queue
        self.renderer = renderer
        self.mailer = mailer
        self.recipients = recipients  # a RecipientSource
        self.approvers = approvers
        self.excluded = excluded
        self.limit = limit

    def __call__(self):
        sent = failed = 0
        for _ in range(self.limit):
            item = self.queue.claim_next()
            if item is None:
                break
            try:
                email = self._render(item)
                who = resolve_recipients(self.recipients.to_emails(), self.approvers,
                                         self.excluded, extra_to=item.recipients)
                self.mailer.send(who.to, who.cc, email)
            except Exception as exc:  # noqa: BLE001 - recorded on the row, then moved past
                logger.exception("report %s failed", item.id)
                self.queue.mark_failed(item.id, f"{type(exc).__name__}: {exc}")
                failed += 1
            else:
                self.queue.mark_sent(item.id)
                sent += 1
        return SendSummary(sent=sent, failed=failed)

    def _render(self, item):
        if item.report_type != "daily_trading":
            raise ReportPayloadError(f"unknown report_type {item.report_type!r}")
        return self.renderer.render_daily(parse_daily_report(item.payload))

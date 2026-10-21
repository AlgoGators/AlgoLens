"""Worker: send the reports trade-ngin has queued in reports.report_queue.

    python scripts/send_reports.py            # drain the queue once and exit (cron, a timer)
    python scripts/send_reports.py --loop 60  # keep polling every 60 seconds

Exits non-zero when any report failed, so a cron wrapper or a scheduler can alert on it.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algolens.application.reports.use_cases import SendQueuedReports  # noqa: E402
from algolens.infrastructure.reports.mailer import SmtpMailer  # noqa: E402
from algolens.infrastructure.reports.queue import PostgresReportQueue  # noqa: E402
from algolens.infrastructure.reports.recipients import EnvRecipients  # noqa: E402
from algolens.infrastructure.reports.renderer import HtmlReportRenderer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", type=int, metavar="SECONDS", help="poll forever at this interval")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    who = EnvRecipients()
    send = SendQueuedReports(PostgresReportQueue(), HtmlReportRenderer(), SmtpMailer(), who,
                             who.approvers(), who.excluded())
    failed_any = False
    while True:
        summary = send()
        logging.info("sent=%d failed=%d", summary.sent, summary.failed)
        failed_any = failed_any or summary.failed > 0
        if not args.loop:
            return 1 if failed_any else 0
        time.sleep(args.loop)


if __name__ == "__main__":
    sys.exit(main())

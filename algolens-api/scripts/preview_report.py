"""Render the daily report from sample data, to look at it without a database or a mail server.

    python scripts/preview_report.py                  # writes preview/report.html (+ report.eml)
    python scripts/preview_report.py --send me@x.com  # also sends it through the SMTP_* settings

The HTML uses data: URIs for the charts so it opens straight in a browser; the .eml is the real
multipart message the worker sends (charts inline by Content-ID).
"""

import argparse
import base64
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "tests"))

from report_fixture import sample_payload  # noqa: E402

from algolens.domain.reports.daily import parse_daily_report  # noqa: E402
from algolens.infrastructure.reports.mailer import SmtpMailer, build_message  # noqa: E402
from algolens.infrastructure.reports.renderer import HtmlReportRenderer  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(BACKEND_DIR / "preview"))
    ap.add_argument("--no-notice", action="store_true")
    ap.add_argument("--send", metavar="ADDRESS", help="send through SMTP_HOST/SMTP_USER/SMTP_PASSWORD")
    args = ap.parse_args()

    report = parse_daily_report(sample_payload(with_notice=not args.no_notice))
    email = HtmlReportRenderer().render_daily(report)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    html = email.html
    for cid, data in email.images.items():
        mime = "image/jpeg" if data[:3] == b"\xff\xd8\xff" else "image/png"
        uri = f"data:{mime};base64,{base64.b64encode(data).decode()}"
        html = html.replace(f"cid:{cid}", uri)
    (out / "report.html").write_text(html, encoding="utf-8")
    (out / "report.eml").write_bytes(
        bytes(build_message("reports@algolens.local", ["preview@example.com"], email)))
    print(f"wrote {out / 'report.html'} and {out / 'report.eml'}")

    if args.send:
        SmtpMailer(os.environ).send([args.send], email)
        print(f"sent to {args.send}")


if __name__ == "__main__":
    main()

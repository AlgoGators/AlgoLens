"""Investor reports and letters: PDFs an admin uploads and investors download."""

import hashlib
import re

MAX_REPORT_BYTES = 10 * 1024 * 1024  # 10 MB, also a CHECK in migration 003
REPORT_KINDS = ("monthly", "quarterly", "letter", "other")
PDF_CONTENT_TYPE = "application/pdf"
MAX_TITLE = 200
MAX_PERIOD = 40


class ReportRuleError(ValueError):
    """An upload or edit the rules refuse."""


def safe_filename(filename):
    """A download name that cannot break the Content-Disposition header."""
    base = re.split(r"[\\/]", filename or "")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .") or "report"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base[:120]


def validate_title(title):
    title = (title or "").strip()
    if not title:
        raise ReportRuleError("A title is required")
    if len(title) > MAX_TITLE:
        raise ReportRuleError(f"The title is longer than {MAX_TITLE} characters")
    return title


def validate_upload(title, kind, period_label, filename, data):
    """The row to store, or ReportRuleError."""
    title = validate_title(title)
    kind = (kind or "").strip()
    if kind not in REPORT_KINDS:
        raise ReportRuleError(f"kind must be one of {', '.join(REPORT_KINDS)}")
    period_label = (period_label or "").strip() or None
    if period_label and len(period_label) > MAX_PERIOD:
        raise ReportRuleError(f"The period is longer than {MAX_PERIOD} characters")
    if not data:
        raise ReportRuleError("The file is empty")
    if len(data) > MAX_REPORT_BYTES:
        raise ReportRuleError("The file is larger than 10 MB")
    # The browser's content type is not trusted: the bytes must be a PDF.
    if not data.startswith(b"%PDF-"):
        raise ReportRuleError("Only PDF files can be uploaded")
    return {
        "title": title,
        "kind": kind,
        "period_label": period_label,
        "filename": safe_filename(filename),
        "content_type": PDF_CONTENT_TYPE,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "content": data,
    }

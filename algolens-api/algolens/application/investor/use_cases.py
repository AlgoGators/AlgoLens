"""Investor screen use cases: the published allocation, and reports/letters."""

from typing import Protocol

from algolens.application.shared.errors import NotFoundError
from algolens.domain.investor.allocation import InstrumentInfo, build_allocation
from algolens.domain.investor.reports import ReportRuleError, validate_title, validate_upload

INVESTOR_BOOK = "qt"


class ReportNotFound(NotFoundError):
    """No report with that id (or, for investors, not published)."""


class InvestorRepositoryPort(Protocol):
    def latest_published_day(self, portfolio_id):
        """The newest date with live_run_metadata.published_at set, or None."""
        ...

    def book_rows(self, portfolio_id, day, book):
        """[{symbol, quantity, average_price}] netted per symbol."""
        ...

    def instruments(self, roots) -> dict[str, InstrumentInfo]:
        ...

    def list_reports(self, published_only: bool) -> list[dict]:
        ...

    def get_report(self, report_id, published_only: bool) -> dict | None:
        """The report with its content, or None."""
        ...

    def insert_report(self, row: dict, uploaded_by: str) -> dict:
        ...

    def update_report(self, report_id, changes: dict) -> dict | None:
        ...


class GetInvestorAllocation:
    """For every desk portfolio, the qt book of its latest published day."""

    def __init__(self, registry, repo: InvestorRepositoryPort):
        self.registry = registry
        self.repo = repo

    def execute(self):
        portfolios = []
        seen = set()
        for cfg in self.registry.list():
            portfolio_id = cfg.get("portfolio_id")
            if not cfg.get("desk_editable") or portfolio_id in seen:
                continue
            seen.add(portfolio_id)
            day = self.repo.latest_published_day(portfolio_id)
            positions, allocation, gross = [], [], 0.0
            if day is not None:
                rows = self.repo.book_rows(portfolio_id, day, INVESTOR_BOOK)
                roots = sorted({(r.get("symbol") or "").split(".", 1)[0] for r in rows})
                positions, allocation, gross = build_allocation(
                    rows, self.repo.instruments(roots)
                )
            portfolios.append(
                {
                    "portfolio_id": portfolio_id,
                    "name": cfg.get("name") or portfolio_id,
                    "portfolio_group": cfg.get("portfolio_group"),
                    "as_of": day.isoformat() if day is not None else None,
                    "gross_notional": gross,
                    "positions": positions,
                    "allocation": allocation,
                }
            )
        return portfolios


class ListReports:
    def __init__(self, repo: InvestorRepositoryPort):
        self.repo = repo

    def execute(self, published_only=True):
        return self.repo.list_reports(published_only)


class GetReportFile:
    def __init__(self, repo: InvestorRepositoryPort):
        self.repo = repo

    def execute(self, report_id, published_only=True):
        report = self.repo.get_report(report_id, published_only)
        if report is None:
            raise ReportNotFound("Report not found")
        return report


class UploadReport:
    def __init__(self, repo: InvestorRepositoryPort):
        self.repo = repo

    def execute(self, title, kind, period_label, filename, data, uploaded_by):
        row = validate_upload(title, kind, period_label, filename, data)
        return self.repo.insert_report(row, uploaded_by)


class UpdateReport:
    """Rename or (un)publish a report. Reports are never hard-deleted."""

    def __init__(self, repo: InvestorRepositoryPort):
        self.repo = repo

    def execute(self, report_id, payload):
        changes = {}
        if "title" in payload:
            changes["title"] = validate_title(payload["title"])
        if "published" in payload:
            if not isinstance(payload["published"], bool):
                raise ReportRuleError("published must be true or false")
            changes["published"] = payload["published"]
        if not changes:
            raise ReportRuleError("Nothing to change: send title and/or published")
        report = self.repo.update_report(report_id, changes)
        if report is None:
            raise ReportNotFound("Report not found")
        return report

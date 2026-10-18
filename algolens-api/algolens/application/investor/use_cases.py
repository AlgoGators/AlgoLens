"""Investor screen use cases: the published allocation, and reports/letters."""

from typing import Protocol

from algolens.application.shared.errors import NotFoundError, ValidationError
from algolens.domain.investor.allocation import InstrumentInfo, build_allocation
from algolens.domain.investor.links import LinkRuleError, book_choices, check_link, resolve_link
from algolens.domain.investor.reports import ReportRuleError, validate_title, validate_upload


class ReportNotFound(NotFoundError):
    """No report with that id (or, for investors, not published)."""


class InvestorNotFound(NotFoundError):
    """No user with that id to link a book to."""


class InvestorRepositoryPort(Protocol):
    def latest_published_day(self, portfolio_id):
        """The newest date with live_run_metadata.published_at set, or None."""
        ...

    def book_rows(self, portfolio_id, day, book):
        """[{symbol, quantity, average_price}] netted per symbol."""
        ...

    def instruments(self, roots) -> dict[str, InstrumentInfo]:
        ...

    def portfolio_link(self, user_id):
        """D-25: {portfolio_id, book} the investor follows; None when none is set or while
        migration 005 is not applied."""
        ...

    def portfolio_links(self):
        """[{user_id, portfolio_id, book, set_by, set_at}], or None while 005 is not applied."""
        ...

    def set_portfolio_link(self, user_id, portfolio_id, book, by):
        """Upsert and log; False when the user does not exist."""
        ...

    def equity_curve(self, portfolio_id, book, until):
        """[{date, equity}] of the book up to `until` (the published day shown)."""
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


class LinkNotStored(ValidationError):
    """The investor links are not in the database yet (AlgoLens migration 005)."""


class GetInvestorPortfolio:
    """D-25: the one portfolio and book the investor follows (decision 13: the QT book unless an
    admin set the model book), on its latest published day, with its record up to that day."""

    def __init__(self, registry, repo: InvestorRepositoryPort):
        self.registry = registry
        self.repo = repo

    def execute(self, user_id):
        choices = book_choices(self.registry.list())
        link = self.repo.portfolio_link(user_id)
        choice, is_default = resolve_link(choices, link)
        if choice is None:
            return []
        portfolio_id, book = choice["portfolio_id"], choice["book"]
        day = self.repo.latest_published_day(portfolio_id)
        positions, allocation, gross, curve = [], [], 0.0, []
        if day is not None:
            rows = self.repo.book_rows(portfolio_id, day, book)
            roots = sorted({(r.get("symbol") or "").split(".", 1)[0] for r in rows})
            positions, allocation, gross = build_allocation(rows, self.repo.instruments(roots))
            curve = [
                {"date": _iso(p["date"]), "equity": float(p["equity"])}
                for p in self.repo.equity_curve(portfolio_id, book, day)
            ]
        first, last = (curve[0]["equity"], curve[-1]["equity"]) if curve else (None, None)
        return [{
            "portfolio_id": portfolio_id,
            "name": choice["name"],
            "book": book,
            "follows": choice["follows"],
            "label": choice["label"],
            "default": is_default,
            "as_of": day.isoformat() if day is not None else None,
            "gross_notional": gross,
            "positions": positions,
            "allocation": allocation,
            "performance": {
                "curve": curve,
                "value": last,
                "return": (last / first - 1) if first and last is not None else None,
            },
        }]


class ListInvestorLinks:
    """D-25, the admin's view: who follows what, and what can be followed."""

    def __init__(self, registry, repo: InvestorRepositoryPort):
        self.registry = registry
        self.repo = repo

    def execute(self):
        links = self.repo.portfolio_links()
        return {
            "stored": links is not None,
            "choices": book_choices(self.registry.list()),
            "links": [
                {"user_id": r["user_id"], "portfolio_id": r["portfolio_id"], "book": r["book"],
                  "set_by": r.get("set_by"), "set_at": _iso(r.get("set_at"))}
                for r in (links or [])
            ],
        }


class SetInvestorLink:
    def __init__(self, registry, repo: InvestorRepositoryPort):
        self.registry = registry
        self.repo = repo

    def execute(self, user_id, portfolio_id, book, by):
        try:
            choice = check_link(book_choices(self.registry.list()), portfolio_id, book)
        except LinkRuleError as exc:
            raise ValidationError(str(exc)) from None
        if self.repo.portfolio_links() is None:
            raise LinkNotStored(
                "The investor links are not in the database yet (AlgoLens migration 005)")
        if not self.repo.set_portfolio_link(user_id, choice["portfolio_id"], choice["book"], by):
            raise InvestorNotFound(f"No user {user_id}")
        return choice


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


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

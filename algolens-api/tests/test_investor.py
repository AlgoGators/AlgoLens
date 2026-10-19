"""The investor screen: allocation maths, report rules and the /api routes."""

import io
from datetime import date, datetime, timezone

import pytest
from flask_jwt_extended import create_access_token, get_csrf_token

import algolens.adapters.http.api as api_http
from algolens.application.investor.use_cases import GetInvestorPortfolio, SetInvestorLink, UpdateReport
from algolens.domain.investor.allocation import (
    InstrumentInfo,
    build_allocation,
    parse_contract_size,
    symbol_root,
)
from algolens.domain.investor.reports import (
    MAX_REPORT_BYTES,
    ReportRuleError,
    safe_filename,
    validate_upload,
)
from app import app

PDF = b"%PDF-1.4\n%test\n%%EOF\n"


# --- domain -------------------------------------------------------------------


def test_symbol_root_and_contract_size():
    assert symbol_root("ES.v.0") == "ES" and symbol_root("ZC") == "ZC" and symbol_root(None) == ""
    assert parse_contract_size("1,000") == 1000
    assert parse_contract_size("$50") == 50
    assert parse_contract_size("n/a") is None
    assert parse_contract_size("0") is None
    assert parse_contract_size(None) is None


def test_build_allocation_weights_by_gross_notional():
    rows = [
        {"symbol": "ZC.v.0", "quantity": 2, "average_price": 400},
        {"symbol": "ES.v.0", "quantity": -1, "average_price": 5000},
        {"symbol": "ZS.v.0", "quantity": 0, "average_price": 1000},
        {"symbol": "XX.v.0", "quantity": 10, "average_price": 1},
    ]
    instruments = {
        "ZC": InstrumentInfo("Corn", "Agriculture", 50.0),
        "ES": InstrumentInfo("E-mini S&P", "Equity", 50.0),
    }

    positions, allocation, gross = build_allocation(rows, instruments)

    assert [p["symbol"] for p in positions] == ["ES.v.0", "ZC.v.0", "XX.v.0"]
    assert gross == pytest.approx(250000 + 40000 + 10)
    xx = positions[-1]
    assert xx["sector"] == "Other" and xx["notional"] == 10 and xx["name"] == "XX"
    assert positions[0]["side"] == "short" and positions[0]["notional"] == -250000
    assert sum(p["weight"] for p in positions) == pytest.approx(1)
    assert [a["sector"] for a in allocation] == ["Equity", "Agriculture", "Other"]
    assert allocation[0]["net_notional"] == -250000
    assert sum(a["weight"] for a in allocation) == pytest.approx(1)


def test_build_allocation_of_an_empty_book():
    assert build_allocation([], {}) == ([], [], 0)


def test_validate_upload():
    row = validate_upload(" Q3 letter ", "letter", " 2026 Q3 ", "C:\\tmp\\Q3 \"x\".pdf", PDF)
    assert row["title"] == "Q3 letter" and row["period_label"] == "2026 Q3"
    assert row["filename"] == "Q3 _x_.pdf"
    assert row["size_bytes"] == len(PDF) and len(row["sha256"]) == 64
    for args in (
        ("", "letter", None, "a.pdf", PDF),
        ("t", "memo", None, "a.pdf", PDF),
        ("t", "letter", None, "a.pdf", b""),
        ("t", "letter", None, "a.pdf", b"<html>"),
        ("t", "letter", None, "a.pdf", b"%PDF-" + b"0" * MAX_REPORT_BYTES),
        ("t", "letter", "x" * 41, "a.pdf", PDF),
    ):
        with pytest.raises(ReportRuleError):
            validate_upload(*args)


def test_safe_filename():
    assert safe_filename("report") == "report.pdf"
    assert safe_filename("../../etc/passwd") == "passwd.pdf"
    assert safe_filename("") == "report.pdf"


def test_update_report_rules():
    class Repo:
        def update_report(self, report_id, changes):
            return {"id": report_id, **changes}

    assert UpdateReport(Repo()).execute(1, {"published": False}) == {"id": 1, "published": False}
    for payload in ({}, {"published": "no"}, {"title": " "}):
        with pytest.raises(ReportRuleError):
            UpdateReport(Repo()).execute(1, payload)


# --- use case -----------------------------------------------------------------


class FakeRegistry:
    def list(self, active_only=True):
        return [
            {"portfolio_id": "CONSERVATIVE_PORTFOLIO", "name": "Trend", "desk_editable": False},
            {"portfolio_id": "QT_A", "name": "QT A", "portfolio_group": "qt_a", "desk_editable": True},
            {"portfolio_id": "QT_B", "name": "QT B", "portfolio_group": "qt_b", "desk_editable": True},
        ]


class FakeInvestorRepo:
    def __init__(self):
        self.published = {"QT_A": date(2026, 10, 9)}
        self.book_calls = []
        self.reports = {
            1: {"id": 1, "title": "Sept", "kind": "monthly", "period_label": "2026-09",
                "filename": "sept.pdf", "size_bytes": len(PDF), "uploaded_by": "a@x.com",
                "uploaded_at": datetime(2026, 10, 1, tzinfo=timezone.utc), "published": True,
                "content": PDF},
            2: {"id": 2, "title": "Draft", "kind": "letter", "period_label": None,
                "filename": "draft.pdf", "size_bytes": len(PDF), "uploaded_by": "a@x.com",
                "uploaded_at": datetime(2026, 10, 2, tzinfo=timezone.utc), "published": False,
                "content": PDF},
        }
        self.inserted = []

    def latest_published_day(self, portfolio_id):
        return self.published.get(portfolio_id)

    # D-25: who follows which book (None: migration 005 not applied).
    links = None

    def portfolio_link(self, user_id):
        if self.links is None:
            return None
        return self.links.get(str(user_id))

    def portfolio_links(self):
        if self.links is None:
            return None
        return [{"user_id": int(u), **v} for u, v in self.links.items()]

    def set_portfolio_link(self, user_id, portfolio_id, book, by):
        if str(user_id) == "404":
            return False
        self.links[str(user_id)] = {"portfolio_id": portfolio_id, "book": book}
        return True

    def equity_curve(self, portfolio_id, book, until):
        return [{"date": date(2026, 10, 8), "equity": 500000.0},
                {"date": until, "equity": 510000.0}]

    def book_rows(self, portfolio_id, day, book):
        self.book_calls.append((portfolio_id, day, book))
        return [{"symbol": "ZC.v.0", "quantity": 2, "average_price": 400}]

    def instruments(self, roots):
        return {"ZC": InstrumentInfo("Corn", "Agriculture", 50.0)}

    def list_reports(self, published_only):
        return [r for r in self.reports.values() if r["published"] or not published_only]

    def get_report(self, report_id, published_only):
        report = self.reports.get(int(report_id))
        if report is None or (published_only and not report["published"]):
            return None
        return report

    def insert_report(self, row, uploaded_by):
        self.inserted.append((row, uploaded_by))
        return {**row, "id": 3, "uploaded_by": uploaded_by,
                "uploaded_at": datetime(2026, 10, 11, tzinfo=timezone.utc), "published": True}

    def update_report(self, report_id, changes):
        report = self.reports.get(int(report_id))
        if report is None:
            return None
        report.update(changes)
        return report


def test_an_investor_with_no_link_follows_the_qt_book_by_default():
    # D-25, decision 13: one portfolio, the QT book unless an admin set the model book.
    repo = FakeInvestorRepo()
    [portfolio] = GetInvestorPortfolio(FakeRegistry(), repo).execute("9")

    assert (portfolio["portfolio_id"], portfolio["book"], portfolio["follows"]) == ("QT_A", "qt", "qt")
    assert portfolio["default"] is True
    assert repo.book_calls == [("QT_A", date(2026, 10, 9), "qt")]
    assert portfolio["as_of"] == "2026-10-09" and portfolio["positions"][0]["notional"] == 40000
    assert portfolio["performance"]["value"] == 510000.0
    assert round(portfolio["performance"]["return"], 4) == 0.02


def test_an_investor_sees_only_the_book_an_admin_set():
    repo = FakeInvestorRepo()
    repo.links = {"9": {"portfolio_id": "CONSERVATIVE_PORTFOLIO", "book": "system"}}
    repo.published["CONSERVATIVE_PORTFOLIO"] = date(2026, 10, 7)
    [portfolio] = GetInvestorPortfolio(FakeRegistry(), repo).execute("9")

    assert (portfolio["portfolio_id"], portfolio["book"], portfolio["follows"]) == (
        "CONSERVATIVE_PORTFOLIO", "system", "model")
    assert repo.book_calls == [("CONSERVATIVE_PORTFOLIO", date(2026, 10, 7), "system")]
    # Another investor, with no link, is not shown this one's book.
    other = GetInvestorPortfolio(FakeRegistry(), repo).execute("10")[0]
    assert other["portfolio_id"] == "QT_A"


def test_the_retired_twin_is_never_offered_and_a_desk_portfolio_offers_both_books():
    from algolens.domain.investor.links import book_choices
    registry = FakeRegistry().list() + [
        {"portfolio_id": "QT_CONSERVATIVE_MODEL_PORTFOLIO", "name": "Twin", "desk_editable": False}]
    assert [(c["portfolio_id"], c["book"]) for c in book_choices(registry)] == [
        ("CONSERVATIVE_PORTFOLIO", "system"), ("QT_A", "qt"), ("QT_A", "system"),
        ("QT_B", "qt"), ("QT_B", "system")]


def test_a_link_to_a_retired_portfolio_falls_back_to_the_default():
    repo = FakeInvestorRepo()
    repo.links = {"9": {"portfolio_id": "GONE", "book": "qt"}}
    [portfolio] = GetInvestorPortfolio(FakeRegistry(), repo).execute("9")
    assert portfolio["portfolio_id"] == "QT_A" and portfolio["default"] is True


def test_only_a_qt_book_or_a_model_book_can_be_set():
    from algolens.application.shared.errors import ValidationError

    repo = FakeInvestorRepo()
    repo.links = {}
    with pytest.raises(ValidationError, match="not a book an investor can follow"):
        SetInvestorLink(FakeRegistry(), repo).execute(9, "CONSERVATIVE_PORTFOLIO", "qt", "a@x.com")
    # A desk portfolio's own model rows are its Model side (D-68).
    assert SetInvestorLink(FakeRegistry(), repo).execute(
        9, "QT_A", "system", "a@x.com")["label"] == "QT A - Model book"
    assert SetInvestorLink(FakeRegistry(), repo).execute(9, "QT_B", "qt", "a@x.com")["label"] == "QT B - QT book"
    assert repo.links == {"9": {"portfolio_id": "QT_B", "book": "qt"}}


# --- routes -------------------------------------------------------------------


@pytest.fixture
def investor_repo(monkeypatch):
    repo = FakeInvestorRepo()
    monkeypatch.setattr(api_http, "create_investor_dependencies", lambda: (FakeRegistry(), repo))
    return repo


def _login(client, screens, screen_access, role="general_member", email="inv@x.com"):
    screen_access.screens["9"] = screens
    with app.app_context():
        token = create_access_token(identity="9", additional_claims={"role": role, "email": email})
        csrf = get_csrf_token(token)
    client.set_cookie("access_token_cookie", token)
    return {"X-CSRF-TOKEN": csrf}


@pytest.mark.parametrize(
    "path",
    ["/api/investor/allocation", "/api/investor/reports", "/api/investor/reports/1/download"],
)
def test_investor_routes_need_the_investor_screen(client, screen_access, investor_repo, path):
    _login(client, ["member", "qt"], screen_access, role="team_lead")
    assert client.get(path).status_code == 403
    _login(client, ["investor"], screen_access)
    assert client.get(path).status_code == 200


def test_investors_are_refused_member_and_desk_reads(client, screen_access, investor_repo):
    _login(client, ["investor"], screen_access)
    assert client.get("/portfolio/portfolios").status_code == 403
    assert client.get("/portfolio/strategies").status_code == 403
    assert client.get("/portfolio/incubation").status_code == 403


def test_investor_allocation_route(client, screen_access, investor_repo):
    _login(client, ["investor"], screen_access)
    body = client.get("/api/investor/allocation").get_json()
    assert body["portfolios"][0]["allocation"][0]["sector"] == "Agriculture"


def test_investors_see_published_reports_only(client, screen_access, investor_repo):
    _login(client, ["investor"], screen_access)
    reports = client.get("/api/investor/reports").get_json()["reports"]
    assert [r["id"] for r in reports] == [1]
    assert "content" not in reports[0]
    assert client.get("/api/investor/reports/2/download").status_code == 404

    download = client.get("/api/investor/reports/1/download")
    assert download.status_code == 200
    assert download.data == PDF
    assert download.headers["Content-Type"] == "application/pdf"
    assert download.headers["Content-Disposition"] == 'attachment; filename="sept.pdf"'


def test_admin_report_upload_and_unpublish(client, screen_access, investor_repo):
    headers = _login(client, [], screen_access, role="exec_board", email="exec@x.com")

    uploaded = client.post(
        "/api/admin/reports",
        data={"title": "Q3", "kind": "quarterly", "period_label": "2026 Q3",
              "file": (io.BytesIO(PDF), "q3.pdf")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert uploaded.status_code == 201
    assert uploaded.get_json()["title"] == "Q3"
    assert investor_repo.inserted[0][1] == "exec@x.com"

    not_pdf = client.post(
        "/api/admin/reports",
        data={"title": "x", "kind": "other", "file": (io.BytesIO(b"<html>"), "x.pdf")},
        content_type="multipart/form-data",
        headers=headers,
    )
    assert not_pdf.status_code == 400

    no_file = client.post("/api/admin/reports", data={"title": "x", "kind": "other"},
                          content_type="multipart/form-data", headers=headers)
    assert no_file.status_code == 400

    hidden = client.patch("/api/admin/reports/1", json={"published": False}, headers=headers)
    assert hidden.status_code == 200 and hidden.get_json()["published"] is False
    assert client.patch("/api/admin/reports/99", json={"published": False}, headers=headers).status_code == 404

    everything = client.get("/api/admin/reports").get_json()["reports"]
    assert {r["id"] for r in everything} == {1, 2}
    assert client.get("/api/admin/reports/2/download").status_code == 200


def test_report_admin_routes_refuse_non_admins(client, screen_access, investor_repo):
    headers = _login(client, ["investor", "member", "qt"], screen_access)
    assert client.get("/api/admin/reports").status_code == 403
    assert client.patch("/api/admin/reports/1", json={"published": False}, headers=headers).status_code == 403
    assert client.get("/api/admin/reports/2/download").status_code == 403


def test_admin_sets_which_book_an_investor_follows(client, screen_access, investor_repo):
    investor_repo.links = {}
    admin = _login(client, ["member"], screen_access, role="exec_board", email="admin@x.com")
    listed = client.get("/api/admin/investor-links").get_json()
    assert listed["stored"] is True and len(listed["choices"]) == 5
    done = client.put("/api/admin/investors/9/portfolio",
                      json={"portfolio_id": "CONSERVATIVE_PORTFOLIO", "book": "system"}, headers=admin)
    assert done.status_code == 200 and done.get_json()["follows"] == "model"
    bad = client.put("/api/admin/investors/9/portfolio",
                     json={"portfolio_id": "CONSERVATIVE_PORTFOLIO", "book": "qt"}, headers=admin)
    assert bad.status_code == 400
    missing = client.put("/api/admin/investors/404/portfolio",
                         json={"portfolio_id": "QT_A", "book": "qt"}, headers=admin)
    assert missing.status_code == 404

    _login(client, ["investor"], screen_access)
    [portfolio] = client.get("/api/investor/allocation").get_json()["portfolios"]
    assert portfolio["portfolio_id"] == "CONSERVATIVE_PORTFOLIO" and portfolio["follows"] == "model"


def test_setting_a_link_needs_migration_005(client, screen_access, investor_repo):
    investor_repo.links = None
    admin = _login(client, ["member"], screen_access, role="exec_board", email="admin@x.com")
    response = client.put("/api/admin/investors/9/portfolio",
                          json={"portfolio_id": "QT_A", "book": "qt"}, headers=admin)
    assert response.status_code == 409
    _login(client, ["investor"], screen_access)
    assert client.get("/api/investor/allocation").get_json()["portfolios"][0]["portfolio_id"] == "QT_A"


def test_only_an_admin_sees_or_sets_the_links(client, screen_access, investor_repo):
    investor_repo.links = {}
    member = _login(client, ["member", "qt"], screen_access, role="team_lead")
    assert client.get("/api/admin/investor-links").status_code == 403
    assert client.put("/api/admin/investors/9/portfolio",
                      json={"portfolio_id": "QT_A", "book": "qt"}, headers=member).status_code == 403

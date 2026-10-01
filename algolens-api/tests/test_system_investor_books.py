"""Published system-book reads require current identity, grant, and publication."""

from datetime import date, datetime, timezone
from decimal import Decimal

from tests.test_incubation_routes import _set_jwt_cookie


class Service:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error
        self.calls = []

    def read(self, user_id, portfolio_id, source_day=None):
        self.calls.append((user_id, portfolio_id, source_day))
        if self.error:
            raise self.error
        return self.value


def published_view():
    return {
        "schema_version": "system-investor-book/v1",
        "portfolio_id": "INVESTOR_A",
        "source_day": "2026-10-01",
        "model_stream": "system",
        "publication": {
            "publication_id": "10000000-0000-4000-8000-000000000001",
            "content_digest": "a" * 64,
            "published_at": "2026-10-01T20:00:00Z",
        },
        "positions": [],
        "results": [],
        "equity": [],
    }


def install(monkeypatch, service):
    import algolens.adapters.http.investor_books as http
    monkeypatch.setattr(http, "_service", lambda: service)


def test_investor_book_requires_login(client, monkeypatch):
    service = Service(published_view())
    install(monkeypatch, service)
    assert client.get("/portfolio/investor/books/INVESTOR_A").status_code == 401
    assert service.calls == []


def test_non_investor_and_deleted_identity_are_non_disclosing(client, monkeypatch):
    service = Service(published_view())
    install(monkeypatch, service)
    _set_jwt_cookie(client, role="admin", identity="7")
    assert client.get("/portfolio/investor/books/INVESTOR_A").status_code == 404
    _set_jwt_cookie(client, role="subscriber_individual", identity="7")
    client.current_users.remove("7")
    assert client.get("/portfolio/investor/books/INVESTOR_A").status_code == 404
    assert service.calls == []


def test_investor_reads_only_the_requested_published_day(client, monkeypatch):
    service = Service(published_view())
    install(monkeypatch, service)
    _set_jwt_cookie(client, role="subscriber_individual", identity="7")
    response = client.get("/portfolio/investor/books/INVESTOR_A?date=2026-10-01")
    assert response.status_code == 200
    assert response.json == published_view()
    assert service.calls == [("7", "INVESTOR_A", "2026-10-01")]
    assert response.headers["Cache-Control"] == "private, no-store"


def test_ungranted_or_unpublished_book_is_the_same_not_found(client, monkeypatch):
    service = Service(None)
    install(monkeypatch, service)
    _set_jwt_cookie(client, role="subscriber_professional", identity="8")
    response = client.get("/portfolio/investor/books/OTHER?date=2026-10-01")
    assert response.status_code == 404
    assert response.json == {"error": "Not found"}


def test_invalid_date_is_rejected_before_storage(client, monkeypatch):
    service = Service(None)
    install(monkeypatch, service)
    _set_jwt_cookie(client, role="subscriber_individual", identity="7")
    response = client.get("/portfolio/investor/books/INVESTOR_A?date=10/01/2026")
    assert response.status_code == 400
    assert response.json == {"error": "Invalid date", "code": "invalid_date"}
    assert service.calls == []


def test_storage_failure_does_not_disclose_driver_details(client, monkeypatch):
    service = Service(error=RuntimeError("private database details"))
    install(monkeypatch, service)
    _set_jwt_cookie(client, role="subscriber_individual", identity="7")
    response = client.get("/portfolio/investor/books/INVESTOR_A")
    assert response.status_code == 503
    assert "private database details" not in response.get_data(as_text=True)


class Cursor:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []
        self.current = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params):
        self.executed.append((" ".join(sql.split()), params))
        self.current = self.responses.pop(0)

    def fetchone(self):
        return self.current

    def fetchall(self):
        return self.current


class Connection:
    def __init__(self, cursor):
        self.value = cursor
        self.closed = False

    def cursor(self, **_):
        return self.value

    def close(self):
        self.closed = True


def test_repository_requires_grant_and_published_system_rows():
    from algolens.infrastructure.portfolio.investor_books import (
        PostgresInvestorBookRepository,
    )

    publication = {
        "publication_id": "10000000-0000-4000-8000-000000000001",
        "portfolio_id": "INVESTOR_A",
        "source_day": date(2026, 10, 1),
        "strategy_id": "LIVE_EQUITY_ALPHA_BETA",
        "model_stream": "system",
        "content_digest": "a" * 64,
        "published_at": datetime(2026, 10, 1, 20, tzinfo=timezone.utc),
    }
    cursor = Cursor([
        publication,
        [{"strategy_name": "alpha", "symbol": "AAPL", "quantity": Decimal("2.5"),
          "average_price": Decimal("100"), "daily_realized_pnl": Decimal("1"),
          "daily_unrealized_pnl": Decimal("2")}],
        [{"strategy_id": publication["strategy_id"], "current_portfolio_value": Decimal("1003"),
          "total_cumulative_return": Decimal("0.3"), "total_annualized_return": Decimal("4"),
          "daily_return": Decimal("0.1"), "volatility": Decimal("8"),
          "sharpe_ratio": Decimal("0.5"), "sortino_ratio": Decimal("0.7"),
          "max_drawdown": Decimal("-1")}],
        [{"timestamp": datetime(2026, 10, 1, 20, tzinfo=timezone.utc),
          "equity": Decimal("1003")}],
    ])
    connection = Connection(cursor)
    repository = PostgresInvestorBookRepository(lambda: connection)
    value = repository.read("7", "INVESTOR_A", "2026-10-01")

    assert value["publication"] == publication
    assert connection.closed
    publication_sql, publication_params = cursor.executed[0]
    assert "trading.investor_book_access" in publication_sql
    assert "trading.investor_book_publications" in publication_sql
    assert "auth.users" in publication_sql
    assert publication_params == ("7", "INVESTOR_A", date(2026, 10, 1))
    for sql, params in cursor.executed[1:]:
        assert "portfolio_type = 'system'" in sql
        assert params[:3] == ("INVESTOR_A", publication["strategy_id"], date(2026, 10, 1))


def test_service_serializes_exact_financial_values_without_qt_fields():
    from algolens.application.portfolio.investor_books import InvestorBookService

    raw = {
        "publication": {
            "publication_id": "10000000-0000-4000-8000-000000000001",
            "portfolio_id": "INVESTOR_A",
            "source_day": date(2026, 10, 1),
            "strategy_id": "LIVE_EQUITY_ALPHA_BETA",
            "model_stream": "system",
            "content_digest": "a" * 64,
            "published_at": datetime(2026, 10, 1, 20, tzinfo=timezone.utc),
        },
        "positions": [{"strategy_name": "alpha", "symbol": "AAPL",
                       "quantity": Decimal("2.50000000"), "average_price": Decimal("100.125"),
                       "daily_realized_pnl": Decimal("1"), "daily_unrealized_pnl": Decimal("2")}],
        "results": [],
        "equity": [],
    }

    class Repository:
        def read(self, *_):
            return raw

    value = InvestorBookService(Repository()).read("7", "INVESTOR_A", "2026-10-01")
    assert value["model_stream"] == "system"
    assert value["positions"][0]["quantity_exact"] == "2.50000000"
    assert value["positions"][0]["average_price_exact"] == "100.125"
    assert "portfolio_type" not in value["positions"][0]


def test_service_refuses_qt_publication_even_if_repository_returns_one():
    from algolens.application.portfolio.investor_books import InvestorBookService

    class Repository:
        def read(self, *_):
            return {"publication": {"model_stream": "qt"}, "positions": [],
                    "results": [], "equity": []}

    assert InvestorBookService(Repository()).read("7", "INVESTOR_A") is None

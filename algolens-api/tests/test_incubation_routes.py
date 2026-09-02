"""HTTP tests for incubation routes with repository dependencies stubbed."""

from datetime import datetime, timezone

from flask_jwt_extended import create_access_token, get_csrf_token

from app import app


def _set_jwt_cookie(client, role="admin"):
    """Authenticate the test client and return its CSRF token.

    JWT_COOKIE_CSRF_PROTECT is on: state-changing requests must echo the
    csrf_access_token companion cookie in an X-CSRF-TOKEN header. GETs are
    safe methods and ignore the return value.
    """
    claims = {} if role is None else {"role": role}
    with app.app_context():
        token = create_access_token(identity="1", additional_claims=claims)
        csrf = get_csrf_token(token)
    client.set_cookie("access_token_cookie", token)
    return csrf


class FakeReader:
    def list_incubating_strategies(self):
        return [
            {
                "id": "trendfollowing",
                "strategy_type": "LIVE_TREND_FOLLOWING",
                "portfolio_id": "MOCK_PORTFOLIO",
                "name": "Trend Following",
                "description": "Mock-capital trial",
                "mock_capital": 250000,
                "incubation_started_at": datetime(2026, 7, 1, tzinfo=timezone.utc),
            }
        ]

    def fetch_incubation_performance(self, strategy_id):
        assert strategy_id == "trendfollowing"
        from algolens.application.portfolio.ports import IncubationPerformanceRows

        return IncubationPerformanceRows(
            positions=[
                {
                    "date": datetime(2026, 7, 2, tzinfo=timezone.utc),
                    "symbol": "ES",
                    "quantity": 1,
                    "entry_price": 100,
                }
            ],
            equity_curve=[
                {
                    "date": datetime(2026, 7, 2, tzinfo=timezone.utc),
                    "equity": 251000,
                }
            ],
        )


def test_get_incubation_strategies_returns_serialized_payload(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (object(), FakeReader()),
    )
    _set_jwt_cookie(client, role="admin")

    response = client.get("/portfolio/incubation")

    assert response.status_code == 200
    data = response.get_json()
    assert data["incubating_strategies"][0]["id"] == "trendfollowing"
    assert data["incubating_strategies"][0]["mock_capital"] == 250000.0
    assert data["incubating_strategies"][0]["window_days"] == 120


def test_get_incubation_performance_returns_serialized_payload(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (object(), FakeReader()),
    )
    _set_jwt_cookie(client, role="general_member")

    response = client.get("/portfolio/incubation/trendfollowing/performance")

    assert response.status_code == 200
    data = response.get_json()
    assert data["positions"] == [
        {
            "date": "2026-07-02T00:00:00+00:00",
            "symbol": "ES",
            "quantity": 1.0,
            "entry_price": 100.0,
        }
    ]
    assert data["equity_curve"] == [
        {"date": "2026-07-02T00:00:00+00:00", "equity": 251000.0}
    ]


def test_storage_failure_is_a_500_with_a_fixed_message(client, monkeypatch):
    # The driver message names columns and SQL. It used to reach the client
    # verbatim as a 400. A storage fault is a server error with a fixed body.
    import algolens.adapters.http.portfolio as portfolio_http
    from algolens.application.portfolio.ports import IncubationStorageError

    class FailingReader(FakeReader):
        def start_incubation(self, *args, **kwargs):
            raise IncubationStorageError("Database error")

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (object(), FailingReader()),
    )
    csrf = _set_jwt_cookie(client, role="admin")
    response = client.post(
        "/portfolio/incubation/trendfollowing/start",
        json={"mock_capital": 1000, "reason": "trial"},
        headers={"X-CSRF-TOKEN": csrf},
    )
    assert response.status_code == 500
    body = response.get_json()
    assert body["error"] == "Incubation change could not be saved"
    assert "column" not in body["error"] and "relation" not in body["error"]

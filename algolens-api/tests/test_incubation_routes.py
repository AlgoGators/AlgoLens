"""HTTP tests for incubation routes with repository dependencies stubbed."""

from datetime import datetime, timezone

from flask_jwt_extended import create_access_token

from app import app


def _set_jwt_cookie(client, role="admin"):
    claims = {} if role is None else {"role": role}
    with app.app_context():
        token = create_access_token(identity="1", additional_claims=claims)
    client.set_cookie("access_token_cookie", token)


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

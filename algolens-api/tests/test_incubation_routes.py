"""HTTP tests for incubation routes with repository dependencies stubbed."""

from datetime import datetime, timezone

from flask_jwt_extended import create_access_token, get_csrf_token

from app import app


def _set_jwt_cookie(client, role="admin", identity="1", current_role=None):
    """Authenticate the test client and return its CSRF token.

    JWT_COOKIE_CSRF_PROTECT is on: state-changing requests must echo the
    csrf_access_token companion cookie in an X-CSRF-TOKEN header. GETs are
    safe methods and ignore the return value.
    """
    claims = {} if role is None else {"role": role}
    with app.app_context():
        token = create_access_token(identity=identity, additional_claims=claims)
        csrf = get_csrf_token(token)
    client.current_users.set(
        identity, role=role if current_role is None else current_role
    )
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


def test_open_positions_refusal_is_a_stable_conflict(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http
    from algolens.application.portfolio.ports import IncubationError

    class OpenPositions(IncubationError):
        code = "open_positions"

    class RefusingReader(FakeReader):
        def retire_strategy(self, *args, **kwargs):
            raise OpenPositions("internal holding details must not escape")

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (object(), RefusingReader()),
    )
    csrf = _set_jwt_cookie(client, role="admin")

    response = client.post(
        "/portfolio/incubation/trendfollowing/retire",
        json={"reason": "review"},
        headers={"X-CSRF-TOKEN": csrf},
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": "open_positions"}
    assert "holding" not in response.get_data(as_text=True)


def test_unavailable_position_evidence_is_a_stable_conflict(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http
    from algolens.application.portfolio.ports import IncubationError

    class PositionsUnavailable(IncubationError):
        code = "positions_unavailable"

    class RefusingReader(FakeReader):
        def start_incubation(self, *args, **kwargs):
            raise PositionsUnavailable("relation trading.positions does not exist")

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (object(), RefusingReader()),
    )
    csrf = _set_jwt_cookie(client, role="general_member")

    response = client.post(
        "/portfolio/incubation/trendfollowing/start",
        json={"mock_capital": 1000, "reason": "restart"},
        headers={"X-CSRF-TOKEN": csrf},
    )

    assert response.status_code == 409
    assert response.get_json() == {"error": "positions_unavailable"}
    assert "relation" not in response.get_data(as_text=True)


class HistoryRegistry:
    def __init__(self, strategy=None):
        self.strategy = strategy

    def get_any(self, strategy_id):
        assert strategy_id == "trendfollowing"
        return self.strategy


class HistoryReader(FakeReader):
    def list_lifecycle_history(self, strategy_id, limit=100):
        assert strategy_id == "trendfollowing"
        assert limit == 100
        return [
            {
                "id": 9,
                "strategy_id": strategy_id,
                "before_state": "live",
                "after_state": "retired",
                "reason": "review complete",
                "user_id": "1",
                "created_at": datetime(2026, 9, 22, tzinfo=timezone.utc),
            }
        ]


def test_current_internal_role_can_read_retired_lifecycle_history(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (
            HistoryRegistry({"id": "trendfollowing", "lifecycle": "retired"}),
            HistoryReader(),
        ),
    )
    _set_jwt_cookie(client, role="general_member")

    response = client.get(
        "/portfolio/strategies/trendfollowing/lifecycle/history"
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "history": [
            {
                "id": 9,
                "strategy_id": "trendfollowing",
                "before_state": "live",
                "after_state": "retired",
                "reason": "review complete",
                "user_id": "1",
                "created_at": "2026-09-22T00:00:00+00:00",
            }
        ]
    }


def test_lifecycle_history_unknown_strategy_is_404(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (HistoryRegistry(None), HistoryReader()),
    )
    _set_jwt_cookie(client, role="admin")

    response = client.get(
        "/portfolio/strategies/trendfollowing/lifecycle/history"
    )

    assert response.status_code == 404
    assert response.get_json() == {"error": "Strategy not found"}


def test_lifecycle_history_storage_error_is_fixed_500(client, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    class BrokenHistoryReader(HistoryReader):
        def list_lifecycle_history(self, *args, **kwargs):
            raise RuntimeError("password=secret relation trading.strategy_lifecycle_log")

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (
            HistoryRegistry({"id": "trendfollowing", "lifecycle": "retired"}),
            BrokenHistoryReader(),
        ),
    )
    _set_jwt_cookie(client, role="admin")

    response = client.get(
        "/portfolio/strategies/trendfollowing/lifecycle/history"
    )

    assert response.status_code == 500
    assert response.get_json() == {"error": "Failed to read lifecycle history"}
    assert "password" not in response.get_data(as_text=True)

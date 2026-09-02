"""HTTP tests for the qt position edit routes, dependencies stubbed.

Covers the wiring the use-case tests cannot: role gating, status codes, and
that a risk breach round-trips as 409-then-201 rather than blocking outright.
"""

from flask_jwt_extended import create_access_token, get_csrf_token

from app import app


def _set_jwt_cookie(client, role="admin", identity="1"):
    """Authenticate the test client and return its CSRF token.

    JWT_COOKIE_CSRF_PROTECT is on, so state-changing requests must echo the
    csrf_access_token companion cookie in an X-CSRF-TOKEN header. GETs are
    safe methods and do not need it.
    """
    claims = {} if role is None else {"role": role}
    with app.app_context():
        token = create_access_token(identity=identity, additional_claims=claims)
        csrf = get_csrf_token(token)
    client.set_cookie("access_token_cookie", token)
    return csrf


_STRATEGY = {
    "id": "trendfollowing",
    "strategy_type": "LIVE_TREND_FOLLOWING",
    "portfolio_id": "BASE_PORTFOLIO",
}


class FakeRegistry:
    def __init__(self, strategy=_STRATEGY):
        self._strategy = strategy

    def get(self, strategy_id):
        return self._strategy


class FakeReader:
    def __init__(self, envelope=None):
        self.envelope = envelope
        self.written = None

    def fetch_risk_envelope(self, strategy_type, portfolio_id):
        return self.envelope

    def fetch_qt_book(self, strategy_type, portfolio_id):
        return []

    def write_qt_position(self, **kwargs):
        self.written = kwargs
        return {
            "position": {"symbol": kwargs["normalized"]["symbol"], "quantity": 3},
            "override_id": 99,
        }

    def fetch_overrides(self, strategy_type, limit=100):
        return [{"id": 99, "symbol": "ES", "reason": "hedging the roll"}]


def _patch(monkeypatch, registry, reader):
    import algolens.adapters.http.portfolio as portfolio_http

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (registry, reader),
    )


_BODY = {
    "strategy_id": "trendfollowing",
    "symbol": "ES",
    "quantity": 3,
    "reason": "hedging the roll",
}


def test_subscriber_roles_cannot_write_the_book(client, monkeypatch):
    """Subscribers are external paying customers, not desk operators."""
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client, role="subscriber_professional")

    response = client.post("/portfolio/positions", json=_BODY, headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 403
    assert reader.written is None


def test_absent_role_is_refused(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    csrf = _set_jwt_cookie(client, role=None)

    assert client.post("/portfolio/positions", json=_BODY, headers={"X-CSRF-TOKEN": csrf}).status_code == 403


def test_a_clean_edit_is_created(client, monkeypatch):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client, role="admin", identity="7")

    response = client.post("/portfolio/positions", json=_BODY, headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 201
    body = response.get_json()
    assert body["override_id"] == 99
    assert body["risk_check"]["evaluated"] is False
    assert reader.written["user_id"] == "7"


def test_invalid_payload_is_a_bad_request(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    csrf = _set_jwt_cookie(client)

    response = client.post("/portfolio/positions", json={"symbol": "ES"}, headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 400
    assert "strategy_id" in response.get_json()["error"]


def test_unknown_strategy_is_not_found(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(strategy=None), FakeReader())
    csrf = _set_jwt_cookie(client)

    assert client.post("/portfolio/positions", json=_BODY, headers={"X-CSRF-TOKEN": csrf}).status_code == 404


def test_a_breach_returns_409_then_succeeds_when_acknowledged(client, monkeypatch):
    """The gate is advisory: it forces an explicit acknowledgement, not a block."""
    reader = FakeReader(envelope={"max_symbol_notional": {"ES": 1.0}})
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client)

    priced = {**_BODY, "average_price": 500.0}
    first = client.post("/portfolio/positions", json=priced, headers={"X-CSRF-TOKEN": csrf})

    assert first.status_code == 409
    assert first.get_json()["resubmit_with"] == "acknowledge_risk"
    assert first.get_json()["risk_check"]["breaches"]
    assert reader.written is None

    second = client.post("/portfolio/positions", json={**priced, "acknowledge_risk": True}, headers={"X-CSRF-TOKEN": csrf})

    assert second.status_code == 201
    assert reader.written["overrode_risk"] is True


def test_caller_cannot_choose_the_stream_it_writes(client, monkeypatch):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client)

    response = client.post("/portfolio/positions", json={**_BODY, "portfolio_type": "system"}, headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 400
    assert reader.written is None


def test_override_history_is_readable_by_internal_roles(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    _set_jwt_cookie(client, role="general_member")

    response = client.get("/portfolio/overrides/trendfollowing")

    assert response.status_code == 200
    assert response.get_json()["overrides"][0]["id"] == 99


def test_override_history_is_not_readable_by_subscribers(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    _set_jwt_cookie(client, role="subscriber_individual")

    assert client.get("/portfolio/overrides/trendfollowing").status_code == 403

"""HTTP tests for the qt position edit routes, dependencies stubbed.

Covers the wiring the use-case tests cannot: role gating, status codes, and
that a risk breach round-trips as 409-then-201 rather than blocking outright.
"""

import json
from decimal import Decimal

import pytest
from flask_jwt_extended import create_access_token, get_csrf_token

from app import app


def _set_jwt_cookie(client, role="admin", identity="1", current_role=None):
    """Authenticate the test client and return its CSRF token.

    JWT_COOKIE_CSRF_PROTECT is on, so state-changing requests must echo the
    csrf_access_token companion cookie in an X-CSRF-TOKEN header. GETs are
    safe methods and do not need it.
    """
    claims = {} if role is None else {"role": role}
    with app.app_context():
        token = create_access_token(identity=identity, additional_claims=claims)
        csrf = get_csrf_token(token)
    client.current_users.set(identity, role=role if current_role is None else current_role)
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

    def books_for_strategy(self, strategy_id):
        return [self._strategy["portfolio_id"]] if self._strategy else []


class FakeReader:
    def __init__(self, envelope=None):
        self.envelope = envelope
        self.written = None
        self.override_scope = None

    def fetch_risk_envelope(self, strategy_type, portfolio_id):
        return self.envelope

    def fetch_qt_book(self, strategy_type, portfolio_id):
        return []

    def write_qt_position(self, **kwargs):
        risk_check = kwargs.pop("risk_check")
        verdict = risk_check(self.envelope, [], None)
        kwargs["verdict"] = verdict
        kwargs["overrode_risk"] = not verdict["passed"]
        self.written = kwargs
        return {
            "position": {"symbol": kwargs["normalized"]["symbol"], "quantity": 3},
            "override_id": 99,
            "risk_check": verdict,
        }

    def fetch_overrides(self, strategy_type, portfolio_id, limit=100):
        self.override_scope = (strategy_type, portfolio_id, limit)
        return [{"id": 99, "symbol": "ES", "reason": "hedging the roll"}]


class FakeInstrumentCatalog:
    def __init__(self, asset_type="FUTURE"):
        self.asset_type = asset_type

    def resolve_asset_type(self, symbol):
        return self.asset_type


def _patch(monkeypatch, registry, reader, asset_type="FUTURE"):
    import algolens.adapters.http.portfolio as portfolio_http
    import algolens.adapters.http.qt_workflow as qt_http
    from types import SimpleNamespace
    from tests.test_qt_legacy_cutover import Cursor
    from algolens.infrastructure.portfolio.qt_publication_proof import require_legacy_qt_disabled

    # These cases deliberately exercise the legacy path with explicit disabled
    # capability; current session authorization is still the real route check.
    disabled = lambda book, actor: require_legacy_qt_disabled(Cursor({'enabled': False, 'version': 1}), book)
    monkeypatch.setattr(qt_http, '_read_service', lambda: SimpleNamespace(ensure_legacy_disabled=disabled))

    monkeypatch.setattr(
        portfolio_http,
        "create_portfolio_dependencies",
        lambda: (registry, reader),
    )
    monkeypatch.setattr(
        portfolio_http,
        "create_instrument_catalog",
        lambda: FakeInstrumentCatalog(asset_type),
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


@pytest.mark.parametrize("raw_quantity", [
    "92233720368.12345678", "92233720368.12345677",
])
def test_raw_fractional_json_token_reaches_write_exactly(client, monkeypatch, raw_quantity):
    reader = FakeReader()
    # This transport fixture is explicitly equity so fractions are valid.
    _patch(monkeypatch, FakeRegistry(), reader, asset_type="EQUITY")
    csrf = _set_jwt_cookie(client)
    raw = ('{"strategy_id":"trendfollowing","symbol":"ES",'
           '"quantity":' + raw_quantity + ',"average_price":5280.12345678,'
           '"reason":"exact input"}')

    response = client.post("/portfolio/positions", data=raw,
                           content_type="application/json", headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 201
    assert reader.written["normalized"]["quantity"] == Decimal(raw_quantity)
    assert reader.written["normalized"]["average_price"] == Decimal("5280.12345678")
    assert isinstance(reader.written["normalized"]["quantity"], Decimal)


def test_canonical_string_request_reaches_write_exactly(client, monkeypatch):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader, asset_type="EQUITY")
    csrf = _set_jwt_cookie(client)

    response = client.post("/portfolio/positions", json={**_BODY,
        "quantity": "92233720368.12345678", "average_price": "5280.12345678",
    }, headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 201
    assert reader.written["normalized"]["quantity"] == Decimal("92233720368.12345678")
    assert reader.written["normalized"]["average_price"] == Decimal("5280.12345678")


@pytest.mark.parametrize("price_token,expected", [
    ("92233720368.54775807", Decimal("92233720368.54775807")),
    ('"92233720368.54775807"', Decimal("92233720368.54775807")),
    ("0", Decimal("0")),
    ('"0"', Decimal("0")),
])
def test_raw_json_and_string_average_price_boundaries_reach_write_exactly(
    client, monkeypatch, price_token, expected
):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client)
    raw = ('{"strategy_id":"trendfollowing","symbol":"ES",'
           '"quantity":1,"average_price":' + price_token + ',"reason":"price boundary"}')

    response = client.post("/portfolio/positions", data=raw,
                           content_type="application/json", headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 201
    assert reader.written["normalized"]["average_price"] == expected
    assert isinstance(reader.written["normalized"]["average_price"], Decimal)


@pytest.mark.parametrize("price_token,code", [
    ("92233720368.54775808", "price_not_representable"),
    ('"92233720368.54775808"', "price_not_representable"),
    ("1.000000001", "price_not_representable"),
    ('"1.000000001"', "price_not_representable"),
    ("-0.00000001", "price_negative"),
    ('"-0.00000001"', "price_negative"),
])
def test_raw_json_and_string_average_price_invalid_values_do_not_write(
    client, monkeypatch, price_token, code
):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client)
    raw = ('{"strategy_id":"trendfollowing","symbol":"ES",'
           '"quantity":1,"average_price":' + price_token + ',"reason":"price boundary"}')

    response = client.post("/portfolio/positions", data=raw,
                           content_type="application/json", headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 400
    assert response.get_json()["code"] == code
    assert reader.written is None


@pytest.mark.parametrize("raw_quantity", [
    "92233720368.54775808", "-92233720368.54775809", "1.000000001",
])
def test_unrepresentable_raw_fractional_tokens_never_write(client, monkeypatch, raw_quantity):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client)
    raw = ('{"strategy_id":"trendfollowing","symbol":"ES",'
           '"quantity":' + raw_quantity + ',"reason":"reject"}')

    response = client.post("/portfolio/positions", data=raw,
                           content_type="application/json", headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 400
    assert reader.written is None


def test_invalid_payload_is_a_bad_request(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    csrf = _set_jwt_cookie(client)

    response = client.post("/portfolio/positions", json={"symbol": "ES"}, headers={"X-CSRF-TOKEN": csrf})

    assert response.status_code == 400
    assert "strategy_id" in response.get_json()["error"]


@pytest.mark.parametrize("field", ["quantity", "average_price"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")],
                         ids=["nan", "positive-infinity", "negative-infinity"])
def test_non_finite_position_numbers_cannot_reach_a_write(client, monkeypatch, field, value):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client)
    response = client.post(
        "/portfolio/positions", data=json.dumps({**_BODY, field: value}),
        content_type="application/json", headers={"X-CSRF-TOKEN": csrf},
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == (
        "quantity_not_finite" if field == "quantity" else "price_not_finite"
    )
    assert reader.written is None


@pytest.mark.parametrize("field,code", [
    ("quantity", "quantity_not_representable"),
    ("average_price", "price_not_representable"),
])
def test_large_finite_integer_token_cannot_reach_a_write(client, monkeypatch, field, code):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    csrf = _set_jwt_cookie(client)
    response = client.post("/portfolio/positions", data=json.dumps({**_BODY, field: 10 ** 400}),
                           content_type="application/json", headers={"X-CSRF-TOKEN": csrf})
    assert response.status_code == 400
    assert response.get_json()["code"] == code
    assert reader.written is None


def test_unknown_strategy_is_not_found(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(strategy=None), FakeReader())
    csrf = _set_jwt_cookie(client)

    assert client.post("/portfolio/positions", json=_BODY, headers={"X-CSRF-TOKEN": csrf}).status_code == 404


def test_a_breach_returns_409_then_succeeds_when_acknowledged(client, monkeypatch):
    """The gate is advisory: it forces an explicit acknowledgement, not a block."""
    reader = FakeReader(envelope={"max_symbol_position_contracts": {"ES": 1}})
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
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    _set_jwt_cookie(client, role="general_member")

    response = client.get("/portfolio/overrides/trendfollowing?portfolio_id=BASE_PORTFOLIO")

    assert response.status_code == 200
    assert response.get_json()["overrides"][0]["id"] == 99
    assert reader.override_scope == ("LIVE_TREND_FOLLOWING", "BASE_PORTFOLIO", 100)


def test_override_history_requires_a_portfolio_id(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    _set_jwt_cookie(client, role="general_member")

    response = client.get("/portfolio/overrides/trendfollowing")

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Field 'portfolio_id' is required",
        "code": "missing_portfolio_id",
    }


def test_missing_override_book_precedes_unknown_strategy_lookup(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(strategy=None), FakeReader())
    _set_jwt_cookie(client, role="general_member")

    response = client.get("/portfolio/overrides/missing-strategy")

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "Field 'portfolio_id' is required",
        "code": "missing_portfolio_id",
    }


def test_override_history_rejects_a_non_member_book(client, monkeypatch):
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    _set_jwt_cookie(client, role="general_member")

    response = client.get("/portfolio/overrides/trendfollowing?portfolio_id=OTHER_BOOK")

    assert response.status_code == 400
    assert response.get_json()["code"] == "not_a_member_of_book"
    assert reader.override_scope is None


def test_override_history_is_not_readable_by_subscribers(client, monkeypatch):
    _patch(monkeypatch, FakeRegistry(), FakeReader())
    _set_jwt_cookie(client, role="subscriber_individual")

    assert client.get(
        "/portfolio/overrides/trendfollowing?portfolio_id=BASE_PORTFOLIO"
    ).status_code == 403

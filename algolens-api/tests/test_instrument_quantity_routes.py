"""The real edit route must compose the server catalog and return safe errors."""

from decimal import Decimal

import pytest

from tests.test_position_edit_routes import FakeReader, FakeRegistry, _patch, _set_jwt_cookie
from tests.test_instrument_quantity_guard import Catalog


def setup_route(client, monkeypatch, catalog):
    import algolens.adapters.http.portfolio as http
    reader = FakeReader()
    _patch(monkeypatch, FakeRegistry(), reader)
    monkeypatch.setattr(http, "create_instrument_catalog", lambda: catalog, raising=False)
    return reader, {"X-CSRF-TOKEN": _set_jwt_cookie(client)}


@pytest.mark.parametrize("acknowledged", [False, True])
def test_http_futures_fraction_refused_without_write_or_override(client, monkeypatch, acknowledged):
    reader, headers = setup_route(client, monkeypatch, Catalog("FUTURE"))
    response = client.post("/portfolio/positions", headers=headers, json={
        "strategy_id": "trendfollowing", "symbol": "ES.v.0", "quantity": "2.5",
        "reason": "manual decision", "acknowledge_risk": acknowledged,
        "asset_type": "EQUITY",
    })
    assert response.status_code == 400
    assert response.json["code"] == "quantity_futures_whole_required"
    assert "whole contracts" in response.json["error"]
    assert "risk_check" not in response.json
    assert reader.written is None


def test_http_equity_fraction_uses_server_catalog_and_exact_value(client, monkeypatch):
    catalog = Catalog("EQUITY")
    reader, headers = setup_route(client, monkeypatch, catalog)
    response = client.post("/portfolio/positions", headers=headers, json={
        "strategy_id": "trendfollowing", "symbol": "BRK.B", "quantity": "2.50000001",
        "reason": "manual decision",
    })
    assert response.status_code == 201
    assert reader.written["normalized"]["quantity"] == Decimal("2.50000001")
    assert catalog.symbols == ["BRK.B"]


def test_http_catalog_failure_is_clear_and_does_not_disclose_driver_details(client, monkeypatch):
    reader, headers = setup_route(client, monkeypatch, Catalog(error=RuntimeError("secret SQL host")))
    response = client.post("/portfolio/positions", headers=headers, json={
        "strategy_id": "trendfollowing", "symbol": "ES", "quantity": "3",
        "reason": "manual decision", "acknowledge_risk": True,
    })
    assert response.status_code == 400
    assert response.json["code"] == "instrument_type_unavailable"
    assert "Instrument type" in response.json["error"]
    assert "secret" not in response.get_data(as_text=True)
    assert reader.written is None

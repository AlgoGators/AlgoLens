"""A database NUMERIC scale must never silently change QT's exact input."""

import pytest

from algolens.domain.portfolio.position_edit import PositionValidationError
from tests.integration.test_instrument_quantity_postgres import (
    db, _edit, _full_state, _state, _wire_route_to_postgres,
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def numeric6_db(db):
    # Reproduce the column types required by trade-ngin migration 015, rather
    # than the unbounded NUMERIC used by the general exact-transport fixture.
    connection = db()
    try:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE trading.positions "
                    "ALTER COLUMN quantity TYPE NUMERIC(20,6), "
                    "ALTER COLUMN average_price TYPE NUMERIC(20,6)"
                )
    finally:
        connection.close()
    return db


@pytest.mark.parametrize("existing", [False, True], ids=["insert", "update"])
@pytest.mark.parametrize("quantity,price,code", [
    ("2.12345678", "100", "quantity_storage_not_exact"),
    ("-0.00000001", "100", "quantity_storage_not_exact"),
    ("2.5", "100.12345678", "price_storage_not_exact"),
])
def test_database_rounding_refuses_the_entire_position_and_audit_transaction(
    numeric6_db, existing, quantity, price, code
):
    if existing:
        _edit(numeric6_db, "SPY", "2.5", price="100")
    before = _full_state(numeric6_db)

    with pytest.raises(PositionValidationError) as error:
        _edit(numeric6_db, "SPY", quantity, price=price)

    assert error.value.code == code
    assert _full_state(numeric6_db) == before


@pytest.mark.parametrize("existing", [False, True], ids=["insert", "update"])
def test_quantity_and_price_representable_at_storage_scale_still_save(
    numeric6_db, existing
):
    from decimal import Decimal

    if existing:
        _edit(numeric6_db, "SPY", "2.5", price="100")
    result = _edit(numeric6_db, "SPY", "-2.123456", price="100.123456")

    assert result["position"]["quantity_exact"] == "-2.123456"
    assert result["position"]["average_price_exact"] == "100.123456"
    positions, audits = _state(numeric6_db)
    assert ("SPY", "qt", Decimal("-2.123456"), Decimal("100.123456")) in positions
    assert audits[-1][2]["quantity_exact"] == "-2.123456"
    assert audits[-1][2]["average_price_exact"] == "100.123456"


def test_http_reports_storage_precision_refusal_without_saving(
    numeric6_db, client, monkeypatch
):
    from tests.test_position_edit_routes import _set_jwt_cookie

    _wire_route_to_postgres(numeric6_db, monkeypatch)
    before = _full_state(numeric6_db)
    response = client.post(
        "/portfolio/positions", headers={"X-CSRF-TOKEN": _set_jwt_cookie(client)},
        json={"strategy_id": "itest_quantity", "symbol": "SPY",
              "quantity": "2.12345678", "average_price": "100",
              "reason": "must not silently round", "acknowledge_risk": True},
    )

    assert response.status_code == 400
    assert response.json["code"] == "quantity_storage_not_exact"
    assert "nothing was saved" in response.json["error"].lower()
    assert _full_state(numeric6_db) == before

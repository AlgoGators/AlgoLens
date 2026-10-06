"""Instrument rules must be enforced by the actual QT write use case."""

from decimal import Decimal

import pytest

from algolens.application.portfolio.use_cases import UpsertQtPosition
from algolens.domain.portfolio.position_edit import PositionValidationError


class Registry:
    def get(self, strategy_id):
        return {"id": "qt", "strategy_type": "QT", "portfolio_id": "BOOK"}

    def books_for_strategy(self, strategy_id):
        return ["BOOK"]


class Reader:
    def __init__(self):
        self.writes = []

    def write_qt_position(self, **kwargs):
        verdict = kwargs["risk_check"](None, [], None)
        position = dict(kwargs["normalized"])
        self.writes.append(position)
        return {"position": position, "risk_check": verdict}


class Catalog:
    def __init__(self, kind="FUTURE", error=None):
        self.kind = kind
        self.error = error
        self.symbols = []

    def resolve_asset_type(self, symbol):
        self.symbols.append(symbol)
        if self.error:
            raise self.error
        return self.kind


def operation(catalog):
    reader = Reader()
    use_case = UpsertQtPosition(Registry(), reader, instrument_catalog=catalog)
    return use_case, reader


def payload(quantity="2.5", **changes):
    return {"strategy_id": "qt", "strategy_name": "DESK", "symbol": "ES.v.0",
            "quantity": quantity, "reason": "reviewed decision", **changes}


@pytest.mark.parametrize("quantity", ["2.5", "-2.5", "0.00000001"])
@pytest.mark.parametrize("acknowledge", [False, True])
def test_fractional_futures_never_reach_write_even_when_risk_acknowledged(quantity, acknowledge):
    use_case, reader = operation(Catalog())
    with pytest.raises(PositionValidationError) as error:
        use_case.execute(payload(quantity), "7", acknowledge_risk=acknowledge)
    assert error.value.code == "quantity_futures_whole_required"
    assert reader.writes == []


@pytest.mark.parametrize("quantity", ["3", "-3", "0", Decimal("3.00000000")])
def test_whole_futures_preserve_exact_quantity(quantity):
    use_case, reader = operation(Catalog())
    result = use_case.execute(payload(quantity), "7")
    assert result["position"]["quantity"] == Decimal(quantity)
    assert len(reader.writes) == 1


def test_equity_fraction_keeps_exact_dotted_identity_and_quantity():
    catalog = Catalog("EQUITY")
    use_case, reader = operation(catalog)
    result = use_case.execute(payload("2.50000001", symbol="BRK.B"), "7")
    assert result["position"]["quantity"] == Decimal("2.50000001")
    assert result["position"]["symbol"] == "BRK.B"
    assert catalog.symbols == ["BRK.B"]
    assert reader.writes[0]["quantity"] == Decimal("2.50000001")


def test_client_claimed_equity_cannot_bypass_futures_rule():
    use_case, reader = operation(Catalog("FUTURE"))
    with pytest.raises(PositionValidationError) as error:
        use_case.execute(payload(asset_type="EQUITY", instrument_type="EQUITY"), "7")
    assert error.value.code == "quantity_futures_whole_required"
    assert reader.writes == []


@pytest.mark.parametrize("catalog,code", [
    (None, "instrument_type_unavailable"),
    (Catalog(None), "instrument_type_unavailable"),
    (Catalog("OPTION"), "instrument_type_unsupported"),
    (Catalog(error=RuntimeError("private database detail")), "instrument_type_unavailable"),
    (Catalog(error=PositionValidationError("instrument_type_ambiguous", "private row detail")),
     "instrument_type_ambiguous"),
])
def test_missing_unsupported_or_failed_catalog_never_writes(catalog, code):
    use_case, reader = operation(catalog)
    with pytest.raises(PositionValidationError) as error:
        use_case.execute(payload("3"), "7", acknowledge_risk=True)
    assert error.value.code == code
    assert reader.writes == []


def test_equity_overprecision_still_rejected_before_catalog_lookup():
    catalog = Catalog("EQUITY")
    use_case, reader = operation(catalog)
    with pytest.raises(PositionValidationError) as error:
        use_case.execute(payload("2.500000001", symbol="BRK.B"), "7")
    assert error.value.code == "quantity_not_representable"
    assert catalog.symbols == []
    assert reader.writes == []

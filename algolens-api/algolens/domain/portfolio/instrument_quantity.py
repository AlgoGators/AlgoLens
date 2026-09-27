"""Quantity rules for a server-resolved instrument; never round a QT choice."""

from decimal import Decimal

from algolens.domain.portfolio.position_edit import PositionValidationError


def validate_instrument_quantity(quantity: Decimal, asset_type: str | None) -> None:
    """The caller first applies the existing exact Decimal8 input boundary."""
    if asset_type is None:
        raise PositionValidationError(
            "instrument_type_unavailable", "Instrument type could not be verified"
        )
    if asset_type not in ("FUTURE", "EQUITY"):
        raise PositionValidationError(
            "instrument_type_unsupported", "Instrument type is not supported for QT edits"
        )
    if asset_type == "FUTURE" and quantity != quantity.to_integral_value():
        raise PositionValidationError(
            "quantity_futures_whole_required", "Futures positions require whole contracts"
        )

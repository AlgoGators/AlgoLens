"""Bounded, exact conversion at the position Decimal8 transport boundary."""

from decimal import Decimal
from math import isfinite

from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8


_SCALE = 100_000_000
_MIN_SCALED = -(1 << 63)
_MAX_SCALED = (1 << 63) - 1
_MAX_INPUT_DIGITS = 128


def canonical_position_decimal8(value):
    """Return canonical Decimal8 text, refusing loss, overflow and huge inputs.

    Strings on the API are canonical. Numeric JSON tokens arrive here as Decimal
    via the route-local decoder. Direct legacy callers may still pass int/float.
    The latter can only retain the digits already present in their float repr.
    """
    if isinstance(value, str):
        return parse_fixed_decimal8(value)
    if type(value) is bool:
        raise TypeError("invalid_position_number")
    if type(value) is float:
        if not isfinite(value):
            raise ValueError("not_finite")
        value = Decimal(str(value))
    elif type(value) is int:
        if value.bit_length() > 128:
            raise ValueError("invalid_fixed_decimal8")
        value = Decimal(value)
    elif not isinstance(value, Decimal):
        raise TypeError("invalid_position_number")

    if not value.is_finite():
        raise ValueError("not_finite")
    sign, digits, exponent = value.as_tuple()
    if len(digits) > _MAX_INPUT_DIGITS:
        raise ValueError("invalid_fixed_decimal8")
    if all(digit == 0 for digit in digits):
        return parse_fixed_decimal8("0")

    shift = exponent + 8
    if shift >= 0:
        if len(digits) + shift > 19:
            raise ValueError("invalid_fixed_decimal8")
        scaled = int("".join(map(str, digits))) * 10**shift
    else:
        cutoff = len(digits) + shift
        if cutoff <= 0 or any(digit != 0 for digit in digits[cutoff:]):
            raise ValueError("invalid_fixed_decimal8")
        scaled = int("".join(map(str, digits[:cutoff])))
    if sign:
        scaled = -scaled
    if not _MIN_SCALED <= scaled <= _MAX_SCALED:
        raise ValueError("invalid_fixed_decimal8")

    whole, fraction = divmod(abs(scaled), _SCALE)
    canonical = f"{whole}"
    if fraction:
        canonical += "." + f"{fraction:08d}".rstrip("0")
    if scaled < 0:
        canonical = "-" + canonical
    return parse_fixed_decimal8(canonical)


def position_decimal8(value):
    """Return a Decimal suitable for an exact PostgreSQL NUMERIC binding."""
    return Decimal(canonical_position_decimal8(value))

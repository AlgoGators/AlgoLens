"""Validate canonical signed int64 fixed-point Decimal8 text."""

import re


_CANONICAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{0,7}[1-9])?")
_SCALE = 100_000_000
_MIN_SCALED = -(1 << 63)
_MAX_SCALED = (1 << 63) - 1


def parse_fixed_decimal8(value: object) -> str:
    if type(value) is not str or len(value) > 21:
        raise ValueError("invalid_fixed_decimal8")
    if value == "-0" or _CANONICAL.fullmatch(value) is None:
        raise ValueError("invalid_fixed_decimal8")

    negative = value.startswith("-")
    unsigned = value[1:] if negative else value
    integer, separator, fraction = unsigned.partition(".")
    scaled = int(integer) * _SCALE
    if separator:
        scaled += int(fraction.ljust(8, "0"))
    if negative:
        scaled = -scaled
    if not _MIN_SCALED <= scaled <= _MAX_SCALED:
        raise ValueError("invalid_fixed_decimal8")
    return value

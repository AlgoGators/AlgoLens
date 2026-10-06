"""Correlations between the instruments a book holds.

The Strategy Builder shipped an empty "Correlation data unavailable" panel on
the grounds that the API exposed no per-symbol price history. It does have the
history -- ``futures_data.ohlcv_1d``, the same table every market price on the
site already comes from. What it lacked was anything to read it with.

Everything here is a pure function over price series so the maths can be tested
without a database, which is where the last round of bugs was hiding.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

#: Below this many overlapping returns a correlation is noise wearing two
#: decimal places. Ten is already generous; it is a floor, not a target.
MIN_OBSERVATIONS = 10


@dataclass(frozen=True)
class CorrelationMatrix:
    """Pairwise correlations, and how much data each one rests on.

    ``observations`` is the number of overlapping returns behind the *thinnest*
    pair, so a caller can say how firm the whole matrix is rather than implying
    every cell is equally well measured.
    """

    symbols: tuple[str, ...]
    matrix: tuple[tuple[float | None, ...], ...]
    observations: int


def log_returns(closes: Sequence[float]) -> list[float]:
    """Period log returns. A non-positive price ends the usable series.

    Log rather than simple returns because they are what the correlation of a
    price series conventionally means, and because they are symmetric: the
    return that halves a price is the negative of the one that doubles it.
    """
    returns: list[float] = []
    for previous, current in zip(closes, closes[1:]):
        if previous is None or current is None or previous <= 0 or current <= 0:
            return returns
        returns.append(math.log(current / previous))
    return returns


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Correlation of two equal-length series, or None when undefined.

    Undefined means one of two things, and both are reported as unknown rather
    than as zero: too few points to measure, or a series that never moves, for
    which "how does it co-move" has no answer.
    """
    n = min(len(xs), len(ys))
    if n < MIN_OBSERVATIONS:
        return None

    xs, ys = xs[:n], ys[:n]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None

    value = covariance / math.sqrt(var_x * var_y)
    # Floating point can push a self-correlation a hair past 1.0, which then
    # renders as "1.00" beside a cell that says "1.00" and is a different
    # number. Clamp to the interval the quantity actually lives in.
    return max(-1.0, min(1.0, value))


def build_matrix(
    closes_by_symbol: Mapping[str, Sequence[tuple[object, float]]],
) -> CorrelationMatrix:
    """Correlate every pair of symbols over the dates they share.

    Each series arrives as (date, close) in ascending date order. Pairs are
    aligned on date before differencing: a symbol that did not trade on a day
    the other did must not have that gap silently closed up, which would pair
    each return with the wrong one and correlate two shifted series.
    """
    symbols = tuple(sorted(closes_by_symbol))
    if not symbols:
        return CorrelationMatrix(symbols=(), matrix=(), observations=0)

    by_date: dict[str, dict[object, float]] = {
        symbol: {date: close for date, close in series}
        for symbol, series in closes_by_symbol.items()
    }

    rows: list[tuple[float | None, ...]] = []
    thinnest = None
    for row_symbol in symbols:
        row: list[float | None] = []
        for column_symbol in symbols:
            shared = sorted(
                set(by_date[row_symbol]) & set(by_date[column_symbol])
            )
            row_returns = log_returns([by_date[row_symbol][d] for d in shared])
            column_returns = log_returns([by_date[column_symbol][d] for d in shared])
            overlap = min(len(row_returns), len(column_returns))
            if thinnest is None or overlap < thinnest:
                thinnest = overlap
            row.append(pearson(row_returns, column_returns))
        rows.append(tuple(row))

    return CorrelationMatrix(
        symbols=symbols,
        matrix=tuple(rows),
        observations=thinnest or 0,
    )

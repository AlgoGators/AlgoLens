"""The investor screen's positions and allocation.

Investors see the qt book of the latest PUBLISHED day only: the book that was
e-mailed out. Never an unpublished day, never the system or qt_proposal books.
Notional is quantity x price x contract size; weights are shares of gross
(absolute) notional, so a short counts by its size.
"""

from dataclasses import dataclass

OTHER_SECTOR = "Other"


def symbol_root(symbol):
    """'ES.v.0' -> 'ES' (the contract_metadata "Databento Symbol")."""
    return (symbol or "").split(".", 1)[0]


def _number(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number else default  # NaN -> default


@dataclass(frozen=True)
class InstrumentInfo:
    name: str | None
    sector: str | None
    contract_size: float | None


def build_allocation(rows, instruments):
    """(positions, allocation) from one book day's netted rows.

    rows: [{symbol, quantity, average_price}]; zero quantities are dropped.
    instruments: {root: InstrumentInfo}. A root without metadata counts with
    contract size 1 under "Other".
    """
    positions = []
    for row in rows:
        quantity = _number(row.get("quantity"), 0.0)
        if quantity == 0:
            continue
        price = _number(row.get("average_price"), 0.0)
        root = symbol_root(row.get("symbol"))
        info = instruments.get(root) or InstrumentInfo(None, None, None)
        size = info.contract_size if info.contract_size else 1.0
        notional = quantity * price * size
        positions.append(
            {
                "symbol": row.get("symbol"),
                "root": root,
                "name": info.name or root,
                "sector": info.sector or OTHER_SECTOR,
                "quantity": quantity,
                "price": price,
                "notional": notional,
                "side": "long" if quantity > 0 else "short",
            }
        )

    gross = sum(abs(p["notional"]) for p in positions)
    for position in positions:
        position["weight"] = abs(position["notional"]) / gross if gross else 0.0
    positions.sort(key=lambda p: (-abs(p["notional"]), p["symbol"] or ""))

    by_sector = {}
    for position in positions:
        bucket = by_sector.setdefault(
            position["sector"],
            {"sector": position["sector"], "gross_notional": 0.0, "net_notional": 0.0, "count": 0},
        )
        bucket["gross_notional"] += abs(position["notional"])
        bucket["net_notional"] += position["notional"]
        bucket["count"] += 1
    allocation = sorted(by_sector.values(), key=lambda b: (-b["gross_notional"], b["sector"]))
    for bucket in allocation:
        bucket["weight"] = bucket["gross_notional"] / gross if gross else 0.0

    return positions, allocation, gross


def parse_contract_size(value):
    """contract_metadata."Contract Size" is TEXT ('50', '1,000', '$50'): a
    positive number or None."""
    if value is None:
        return None
    cleaned = str(value).replace(",", "").replace("$", "").strip()
    number = _number(cleaned)
    return number if number and number > 0 else None

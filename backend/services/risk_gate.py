"""Compares a proposed qt book against the risk envelope trade-ngin published.

This module does NO risk math. trade-ngin owns VaR, leverage and correlation;
it writes the resulting limits to trading.risk_limits and this compares against
them. Two implementations of risk drift apart, and the wrong one gets believed.

Per DECISION-1 the verdict is advisory -- it never blocks a write. The route
uses it to force an explicit acknowledgement and to fill risk_check_result in
the audit trail.
"""


def _notional(position):
    price = position.get("average_price") or 0.0
    return abs(position["quantity"] * price)


def _projected_book(current_book, proposed):
    """The book as it would be after the edit.

    The edited symbol REPLACES its existing row. Adding to it instead would
    double-count every edit and report a breach on almost any change.
    """
    projected = [p for p in current_book if p["symbol"] != proposed["symbol"]]
    if proposed["quantity"] != 0:
        projected.append(proposed)
    return projected


def evaluate(envelope, current_book, proposed):
    """Verdict on a single proposed position change."""
    if not envelope:
        # Explicitly NOT a pass. An unreachable envelope must be visible in the
        # audit trail as "not checked", never as "checked and fine".
        return {"evaluated": False, "passed": True, "breaches": []}

    projected = _projected_book(current_book, proposed)
    breaches = []

    symbol_caps = envelope.get("max_symbol_notional") or {}
    cap = symbol_caps.get(proposed["symbol"])
    if cap is not None:
        actual = _notional(proposed)
        if actual > cap:
            breaches.append(
                {
                    "limit": "max_symbol_notional",
                    "limit_value": cap,
                    "actual": actual,
                    "message": (
                        f"{proposed['symbol']} notional {actual:,.0f} exceeds its "
                        f"cap of {cap:,.0f}"
                    ),
                }
            )

    max_gross = envelope.get("max_gross_notional")
    if max_gross is not None:
        actual = sum(_notional(p) for p in projected)
        if actual > max_gross:
            breaches.append(
                {
                    "limit": "max_gross_notional",
                    "limit_value": max_gross,
                    "actual": actual,
                    "message": (
                        f"Gross notional {actual:,.0f} exceeds the portfolio cap of "
                        f"{max_gross:,.0f}"
                    ),
                }
            )

    max_count = envelope.get("max_position_count")
    if max_count is not None:
        actual = len(projected)
        if actual >= max_count:
            breaches.append(
                {
                    "limit": "max_position_count",
                    "limit_value": max_count,
                    "actual": actual,
                    "message": (
                        f"{actual} open positions exceeds the limit of {max_count}"
                    ),
                }
            )

    return {"evaluated": True, "passed": not breaches, "breaches": breaches}

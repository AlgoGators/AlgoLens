"""Portfolio registry rules: one entry per book, keyed by portfolio id.

A registry row names a portfolio (``portfolio_id``), the group it is shown in
(``portfolio_group``, e.g. ``qt_conservative`` for the desk book and its
untouched model twin) and whether the QT desk may edit it (``desk_editable``).
The strategy type is a description only (AlgoLens#102), except that it tells a
futures book from an equity book (desk editing is futures only, ruling 13).
"""

from collections.abc import Iterable, Mapping
from typing import Any

FUTURES = "futures"
EQUITY = "equity"


def asset_class_for(strategy_type: str | None) -> str:
    """The asset class a registry entry trades, from its strategy type."""
    return EQUITY if "EQUITY" in (strategy_type or "").upper() else FUTURES


def desk_edit_allowed(entry: Mapping[str, Any]) -> bool:
    """Whether the desk may edit this portfolio's proposal book.

    Only portfolios flagged desk_editable, and only futures books (ruling 13:
    no equity desk editing in the first release).
    """
    return bool(entry.get("desk_editable")) and (
        asset_class_for(entry.get("strategy_type")) == FUTURES
    )


def portfolio_entries(registry: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One entry per portfolio id, the first in registry order winning."""
    seen: set[str] = set()
    entries = []
    for row in registry:
        portfolio_id = row.get("portfolio_id")
        if not portfolio_id or portfolio_id in seen:
            continue
        seen.add(portfolio_id)
        entries.append(
            {
                "portfolio_id": portfolio_id,
                "id": row.get("id"),
                "name": row.get("name") or portfolio_id,
                "description": row.get("description") or "",
                "strategy_type": row.get("strategy_type"),
                "asset_class": asset_class_for(row.get("strategy_type")),
                "portfolio_group": row.get("portfolio_group"),
                "desk_editable": desk_edit_allowed(row),
                "initial_equity": row.get("initial_equity"),
                "managers": row.get("managers") or [],
            }
        )
    return entries


def group_portfolios(registry: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Portfolios grouped by portfolio_group, in registry order.

    A portfolio with no group is a group of its own, keyed by its id. Within a
    group the desk-editable book comes first, so the switcher lands on the
    book the desk works on.
    """
    groups: dict[str, dict[str, Any]] = {}
    for entry in portfolio_entries(registry):
        key = entry["portfolio_group"] or entry["portfolio_id"]
        group = groups.setdefault(
            key,
            {"group": key, "grouped": entry["portfolio_group"] is not None, "portfolios": []},
        )
        group["portfolios"].append(entry)
    for group in groups.values():
        group["portfolios"].sort(key=lambda e: not e["desk_editable"])
    return list(groups.values())

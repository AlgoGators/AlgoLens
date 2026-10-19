"""Which portfolio and book an investor follows (HD D-25, decision 13).

An investor follows one book: a desk-editable portfolio's QT book (its final, published "qt"
rows, the desk's edits) or a model book (a portfolio's "system" rows, the engine with no desk
edits; a desk-editable portfolio's own model rows too, as its Model side, D-68). An admin sets it
per investor; with none set the investor follows the QT book (decision 13: QT by default), the
first desk-editable portfolio's. The retired model twin is never offered (D-1).
"""

from collections.abc import Mapping, Sequence
from typing import Any

from algolens.domain.portfolio.registry import RETIRED_TWIN

QT_BOOK, MODEL_BOOK = "qt", "system"


class LinkRuleError(ValueError):
    """A link the registry does not offer."""


def book_choices(registry: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Every (portfolio, book) an investor may follow, from the live registry: a desk-editable
    portfolio's QT book and its model book, any other portfolio's model book (not the twin)."""
    choices, seen = [], set()
    for cfg in registry:
        pid = cfg.get("portfolio_id")
        if not pid or pid in seen or pid == RETIRED_TWIN:
            continue
        seen.add(pid)
        name = cfg.get("name") or pid
        books = (QT_BOOK, MODEL_BOOK) if cfg.get("desk_editable") else (MODEL_BOOK,)
        for book in books:
            choices.append({
                "portfolio_id": pid,
                "book": book,
                "follows": "qt" if book == QT_BOOK else "model",
                "label": f"{name} - {'QT book' if book == QT_BOOK else 'Model book'}",
                "name": name,
            })
    return choices


def default_choice(choices: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Decision 13: an investor with no link follows the QT book."""
    return next((dict(c) for c in choices if c["book"] == QT_BOOK), None)


def resolve_link(choices, link: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, bool]:
    """(the choice the investor follows, whether it is the default). A link the registry no longer
    offers (the portfolio retired) falls back to the default."""
    if link:
        match = next((c for c in choices if c["portfolio_id"] == link.get("portfolio_id")
                      and c["book"] == link.get("book")), None)
        if match is not None:
            return dict(match), False
    return default_choice(choices), True


def check_link(choices, portfolio_id: Any, book: Any) -> dict[str, Any]:
    match = next((c for c in choices
                  if c["portfolio_id"] == portfolio_id and c["book"] == book), None)
    if match is None:
        raise LinkRuleError(
            f"{portfolio_id} / {book} is not a book an investor can follow "
            "(a desk portfolio's QT book, or a model book)"
        )
    return dict(match)

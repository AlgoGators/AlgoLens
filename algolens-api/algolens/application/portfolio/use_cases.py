"""Portfolio use cases."""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from algolens.domain.portfolio.portfolio_assignment import (
    AssignmentValidationError,
    build_assignment_audit,
    build_membership_audit,
    evaluate_assignment,
    evaluate_membership_add,
    evaluate_membership_remove,
    match_book,
    merge_books,
    normalize_portfolio_id,
    validate_book,
)
from algolens.application.portfolio.ports import (
    IncubationError,
    IncubationPerformanceRows,
    MembershipAcknowledgementRequired,
    PortfolioDetailRows,
    PortfolioReaderPort,
    PortfolioReassignmentAcknowledgementRequired,
    RiskAcknowledgementRequired,
    StrategyRegistryPort,
)
from algolens.application.shared.errors import NotFoundError
from algolens.domain.portfolio.calculations import (
    build_historical_data,
    compute_return_stats,
    compute_sharpe,
    float_or_default,
    resolve_initial_equity,
    transform_executions,
    transform_finalized,
    transform_positions,
)
from algolens.domain.portfolio.incubation import compute_incubation_window
from algolens.domain.portfolio.position_edit import (
    resolve_target_book,
    with_known_price,
    evaluate_risk,
    validate_position_payload,
)

logger = logging.getLogger(__name__)


class StrategyDataNotFound(NotFoundError):
    """A known strategy has no live portfolio data yet.

    ``portfolio_id`` is set when the miss is scoped to one book, which is the
    normal state for a strategy just added to a book: the pairing exists, the
    engine has simply not produced rows for it yet. Distinguishing the two lets
    the reader be told which it is instead of a flat "not found".
    """

    def __init__(self, strategy_id, portfolio_id=None):
        super().__init__(strategy_id)
        self.strategy_id = strategy_id
        self.portfolio_id = portfolio_id


class StrategyNotFound(NotFoundError):
    """No active strategy exists for the requested public id."""


def build_strategy_detail(
    cfg: Mapping[str, Any], rows: PortfolioDetailRows
) -> dict[str, Any] | None:
    if not rows.latest:
        return None

    latest = rows.latest
    initial_equity = resolve_initial_equity(rows.equity_curve, cfg["initial_equity"])
    current_value = float(latest["current_portfolio_value"])
    total_return = current_value - initial_equity
    return_percent = (total_return / initial_equity * 100) if initial_equity > 0 else 0

    historical_data = build_historical_data(rows.equity_curve)
    equity_by_stream = {
        stream: build_historical_data(stream_rows)
        for stream, stream_rows in rows.equity_by_stream.items()
    }
    transformed_positions = transform_positions(rows.positions, current_value)
    stats = compute_return_stats(historical_data)
    transformed_executions = transform_executions(rows.executions)
    transformed_finalized = transform_finalized(rows.yesterday_positions, rows.positions)

    volatility = float(latest["volatility"])
    annualized_return = float(latest["total_annualized_return"])
    sharpe = compute_sharpe(annualized_return, volatility)

    return {
        "id": cfg["id"],
        "name": cfg["name"],
        "description": cfg["description"],
        "invested": initial_equity,
        "currentValue": current_value,
        "return": total_return,
        "returnPercent": return_percent,
        "positions": transformed_positions,
        "historicalData": historical_data,
        "equityByStream": equity_by_stream,
        "bestDay": stats["best_day"],
        "worstDay": stats["worst_day"],
        "executions": transformed_executions,
        "finalizedPositions": transformed_finalized,
        "managers": cfg["managers"],
        "lastUpdate": latest["date"].isoformat(),
        "metrics": {
            "volatility": volatility,
            "sharpeRatio": sharpe,
            "maxDrawdown": stats["max_drawdown"],
            "winRate": stats["win_rate"],
            "totalTrades": len(transformed_executions),
            "avgWin": stats["avg_win"],
            "avgLoss": stats["avg_loss"],
            "profitFactor": stats["profit_factor"],
            "dailyReturn": float_or_default(latest["daily_return"]),
            "cumulativeReturn": return_percent,
            "annualizedReturn": annualized_return,
            # The engine stopped writing trading.live_results.gross_leverage and
            # now puts that number in portfolio_leverage; the column it
            # abandoned is still there, holding whatever it held on the day it
            # was abandoned. Reading it directly reported a dead value as a
            # current one. See the note on LIVE_RESULTS in schema_contract.py.
            "grossLeverage": float_or_default(
                latest["gross_leverage"]
                if latest.get("gross_leverage") is not None
                else latest["portfolio_leverage"]
            ),
            "netLeverage": float_or_default(latest["net_leverage"]),
            "portfolioLeverage": float_or_default(latest["portfolio_leverage"]),
            "marginPosted": float_or_default(latest["margin_posted"]),
            "equityToMarginRatio": float_or_default(latest["equity_to_margin_ratio"]),
            "marginCushion": float_or_default(latest["margin_cushion"]),
            "totalNotional": float_or_default(latest["gross_notional"]),
            "unrealizedPnL": float_or_default(latest["total_unrealized_pnl"]),
            "realizedPnL": float_or_default(latest["total_realized_pnl"]),
            "totalCommissions": float_or_default(latest["total_transaction_costs"]),
            "netPnL": total_return,
            "cashAvailable": float_or_default(latest["cash_available"]),
            "currentPortfolioValue": current_value,
        },
    }


def build_strategy_summary(
    cfg: Mapping[str, Any], latest: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    if not latest:
        # The engine keys live_results on (strategy_type, portfolio_id), so a
        # strategy that has just moved book -- or a book the engine has not
        # published for yet -- has no row. It is still a real strategy holding
        # real positions.
        #
        # This used to return None and the caller dropped it from the list
        # entirely, which silently removed its value from the fund headline: the
        # fund appeared to shrink by that strategy's worth, with nothing on
        # screen saying why. Report it instead, with its numbers marked unknown.
        return {
            "id": cfg["id"],
            "name": cfg["name"],
            "dataAvailable": False,
            "currentValue": None,
            "returnPercent": None,
            "volatility": None,
            "sharpeRatio": None,
            "annualizedReturn": None,
        }

    base_equity = cfg["initial_equity"]
    current_value = float(latest["current_portfolio_value"])
    return_percent = ((current_value - base_equity) / base_equity * 100) if base_equity > 0 else 0
    volatility = float(latest["volatility"])
    annualized_return = float(latest["total_annualized_return"])
    sharpe = compute_sharpe(annualized_return, volatility)

    return {
        "id": cfg["id"],
        "name": cfg["name"],
        "dataAvailable": True,
        "currentValue": current_value,
        "returnPercent": return_percent,
        "volatility": volatility,
        "sharpeRatio": sharpe,
        "annualizedReturn": annualized_return,
    }


def build_incubating_strategy(row: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    window = compute_incubation_window(row.get("incubation_started_at"), now)
    return {
        "id": row["id"],
        "strategy_type": row["strategy_type"],
        "portfolio_id": row["portfolio_id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "mock_capital": float(row["mock_capital"])
        if row.get("mock_capital") is not None
        else None,
        "incubation_started_at": row.get("incubation_started_at"),
        "days_elapsed": window.days_elapsed,
        "window_days": window.window_days,
        "progress": window.progress,
    }


def build_incubation_performance(
    rows: IncubationPerformanceRows,
) -> dict[str, list[Mapping[str, Any]]]:
    return {
        "positions": list(rows.positions),
        "equity_curve": list(rows.equity_curve),
    }


def _require_reason(reason: str) -> str:
    if not reason or not reason.strip():
        raise IncubationError("reason must be non-empty")
    return reason.strip()


def _require_mock_capital(mock_capital: float) -> float:
    if mock_capital <= 0:
        raise IncubationError("mock_capital must be positive")
    return mock_capital


class GetStrategyDetail:
    def __init__(self, registry: StrategyRegistryPort, reader: PortfolioReaderPort):
        self.registry = registry
        self.reader = reader

    def execute(
        self, strategy_id: str, portfolio_id: Any = None
    ) -> dict[str, Any]:
        cfg = self.registry.get(strategy_id)
        if cfg is None:
            raise StrategyNotFound(strategy_id)

        # Every book this strategy is in. Read before the rows, because which
        # book is being asked for decides which rows to fetch.
        books = []
        lister = getattr(self.registry, "books_for_strategy", None)
        if lister:
            try:
                books = lister(strategy_id)
            except Exception as exc:
                logger.error(
                    "[STRATEGY] Membership read failed for %s: %s",
                    strategy_id, exc, exc_info=True,
                )
        books = list(books) or [cfg["portfolio_id"]]

        # Which book to show. The primary unless the caller names another one
        # the strategy is actually in. Positions, risk limits and the traded
        # universe are all keyed on (strategy, book), so this is the whole
        # difference between reading one ledger and reading another.
        target = cfg["portfolio_id"]
        if portfolio_id is not None:
            requested = normalize_portfolio_id(portfolio_id)
            found = match_book(requested, books)
            if found is None:
                raise AssignmentValidationError(
                    "not_a_member_of_book",
                    f"{strategy_id} does not belong to {requested}",
                )
            target = found

        rows = self.reader.fetch_detail_rows(cfg["strategy_type"], target)
        detail = build_strategy_detail(cfg, rows)
        if detail is None:
            # A strategy freshly added to a book has no engine output for that
            # pairing yet. That is not the same as the strategy having no data
            # at all, and the reader must not be shown a bare failure for what
            # is a normal, temporary state.
            raise StrategyDataNotFound(strategy_id, target)

        # Which book these positions are, and every book this strategy is in.
        # The view has always shown one book's positions; it just never said so,
        # which is how an edit could be aimed at a universe that was not on
        # screen. The client needs both to name the book it is writing to and to
        # tell the reader they are looking at one of several.
        detail["portfolio_id"] = target
        detail["books"] = books
        return detail


class ListStrategies:
    def __init__(self, registry: StrategyRegistryPort, reader: PortfolioReaderPort):
        self.registry = registry
        self.reader = reader

    def execute(self) -> list[dict[str, Any]]:
        strategies = []
        for cfg in self.registry.list(active_only=True):
            try:
                latest = self.reader.fetch_summary_row(
                    cfg["strategy_type"], cfg["portfolio_id"]
                )
                summary = build_strategy_summary(cfg, latest)
            except Exception as exc:
                logger.error(
                    "[STRATEGIES] Failed to summarize %s: %s",
                    cfg["id"],
                    str(exc),
                    exc_info=True,
                )
                # Still report it. Dropping a strategy because its numbers could
                # not be read removes its value from the fund total without
                # saying so, which is worse than showing it with no numbers.
                summary = build_strategy_summary(cfg, None)
            if summary:
                strategies.append(summary)
        return strategies


class ListIncubatingStrategies:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(self, now: datetime) -> list[dict[str, Any]]:
        return [
            build_incubating_strategy(row, now)
            for row in self.reader.list_incubating_strategies()
        ]


class GetIncubationPerformance:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(self, strategy_id: str) -> dict[str, list[Mapping[str, Any]]]:
        rows = self.reader.fetch_incubation_performance(strategy_id)
        return build_incubation_performance(rows)


class StartIncubation:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(
        self,
        strategy_id: str,
        mock_capital: float,
        reason: str,
        user_id: str,
    ) -> None:
        self.reader.start_incubation(
            strategy_id=strategy_id,
            mock_capital=_require_mock_capital(mock_capital),
            reason=_require_reason(reason),
            user_id=user_id,
        )


class PromoteToLive:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(self, strategy_id: str, reason: str, user_id: str) -> None:
        self.reader.promote_to_live(
            strategy_id=strategy_id,
            reason=_require_reason(reason),
            user_id=user_id,
        )


class RetireStrategy:
    def __init__(self, reader: PortfolioReaderPort):
        self.reader = reader

    def execute(self, strategy_id: str, reason: str, user_id: str) -> None:
        self.reader.retire_strategy(
            strategy_id=strategy_id,
            reason=_require_reason(reason),
            user_id=user_id,
        )


class UpsertQtPosition:
    """Create or amend one position in the qt stream, with an audit row.

    Orchestration only: validation and the risk verdict are domain logic, the
    write is the repository's. This decides the one thing that is neither --
    that a breach requires an explicit acknowledgement rather than blocking.
    """

    def __init__(self, registry: StrategyRegistryPort, reader: PortfolioReaderPort):
        self.registry = registry
        self.reader = reader

    def execute(
        self,
        payload: Mapping[str, Any],
        user_id: str,
        acknowledge_risk: bool = False,
    ) -> dict[str, Any]:
        normalized = validate_position_payload(payload)

        strategy = self.registry.get(normalized["strategy_id"])
        if strategy is None:
            raise StrategyNotFound(normalized["strategy_id"])

        strategy_type = strategy["strategy_type"]
        # Which book, decided explicitly. Reading strategy["portfolio_id"] here
        # meant every edit went to the primary book regardless of which book the
        # caller meant -- see AmbiguousBook.
        books = []
        lister = getattr(self.registry, "books_for_strategy", None)
        if lister:
            try:
                books = lister(strategy["id"])
            except Exception as exc:
                logger.error(
                    "[POSITIONS] Membership read failed for %s: %s",
                    strategy["id"], exc, exc_info=True,
                )
        portfolio_id = resolve_target_book(
            strategy["id"],
            normalized.get("portfolio_id"),
            books,
            strategy["portfolio_id"],
        )

        envelope = self.reader.fetch_risk_envelope(strategy_type, portfolio_id)
        book = self.reader.fetch_qt_book(strategy_type, portfolio_id)

        # The verdict describes the book at gate-evaluation time, not at commit
        # time. That is acceptable because the gate is advisory by design: a
        # breach never blocks, it only requires acknowledgement.
        verdict = evaluate_risk(envelope, book, with_known_price(book, normalized))

        if not verdict["passed"] and not acknowledge_risk:
            raise RiskAcknowledgementRequired(verdict)

        result = self.reader.write_qt_position(
            strategy_type=strategy_type,
            portfolio_id=portfolio_id,
            normalized=normalized,
            user_id=user_id,
            verdict=verdict,
            overrode_risk=not verdict["passed"],
        )
        return {**result, "risk_check": verdict}


class ListPositionOverrides:
    """The audit trail for one strategy, most recent first."""

    def __init__(self, registry: StrategyRegistryPort, reader: PortfolioReaderPort):
        self.registry = registry
        self.reader = reader

    def execute(self, strategy_id: str, limit: int = 100) -> list[dict[str, Any]]:
        # get_any, not get: the audit trail of a retired strategy is exactly the
        # kind of thing someone comes back to read. Hiding it with the strategy
        # would make retirement a way to lose the record of what was done.
        getter = getattr(self.registry, "get_any", None)
        strategy = getter(strategy_id) if getter else self.registry.get(strategy_id)
        if strategy is None:
            raise StrategyNotFound(strategy_id)
        return list(self.reader.fetch_overrides(strategy["strategy_type"], limit))


class ListPortfolios:
    """Group the live strategies by the portfolio they belong to.

    portfolio_id has always scoped every read in this app; this is the first
    thing that surfaces the grouping rather than assuming one portfolio.
    """

    def __init__(self, registry: StrategyRegistryPort, reader: PortfolioReaderPort):
        self.registry = registry
        self.reader = reader

    def _books_by_strategy(self) -> dict[str, list[str]]:
        """Which books each strategy belongs to.

        Falls back to nothing when memberships are unavailable; the caller then
        uses the primary column, so a partially migrated database still lists
        every strategy exactly once rather than none at all.
        """
        try:
            rows = self.registry.list_memberships()
        except Exception as exc:
            logger.error("[PORTFOLIOS] Membership read failed: %s", exc, exc_info=True)
            return {}
        by_strategy: dict[str, list[str]] = {}
        for row in rows:
            by_strategy.setdefault(row["strategy_id"], []).append(row["portfolio_id"])
        return by_strategy

    def execute(self) -> list[dict[str, Any]]:
        # Grouped by membership, not by the single primary column. A strategy can
        # belong to several books, and listing it only under its primary made
        # this view and the Books tab give different answers about the same data.
        by_strategy = self._books_by_strategy()
        buckets: dict[str, dict[str, Any]] = {}

        # active_only=False: an incubating strategy still occupies its book, and
        # omitting it made this view disagree with the Books tab about what a
        # book contains. It is listed and marked; its mock capital is kept out
        # of the total, because mock capital is not fund capital.
        for cfg in self.registry.list(active_only=False):
            lifecycle = (cfg.get("lifecycle") or "live").strip().lower()
            if lifecycle == "retired":
                continue
            books = by_strategy.get(cfg["id"]) or [cfg["portfolio_id"]]
            for portfolio_id in books:
                bucket = buckets.setdefault(
                    portfolio_id,
                    {"portfolio_id": portfolio_id, "strategies": [], "total_value": 0.0},
                )
                # None, not 0.0. The engine keys live_results on
                # (strategy_type, portfolio_id), so a pairing it has not
                # published for -- a strategy just added to a second book, for
                # instance -- has no row. Reporting 0 there would read as "this
                # strategy is worth nothing" rather than "nothing published yet".
                #
                # This is also what keeps the book totals honest under multi-book
                # membership: a strategy contributes to a book only the capital
                # the engine actually reports for that pairing, so nothing is
                # counted twice.
                value = None
                # An incubating strategy trades mock capital. Its live_results
                # row is history from before it was pulled, so reporting it
                # here would put retired-from-live money in a live book total.
                try:
                    latest = None if lifecycle == "incubating" else self.reader.fetch_summary_row(
                        cfg["strategy_type"], portfolio_id
                    )
                    if latest and latest.get("current_portfolio_value") is not None:
                        value = float(latest["current_portfolio_value"])
                except Exception as exc:
                    # A book is still worth listing when one strategy's numbers
                    # are unreadable -- it just contributes nothing to the total.
                    logger.error(
                        "[PORTFOLIOS] Failed to read %s in %s: %s",
                        cfg["id"], portfolio_id, str(exc), exc_info=True,
                    )
                bucket["strategies"].append(
                    {
                        "id": cfg["id"],
                        "name": cfg["name"],
                        "strategy_type": cfg["strategy_type"],
                        "lifecycle": lifecycle,
                        "current_value": value,
                        "mock_capital": (
                            float(cfg["mock_capital"])
                            if lifecycle == "incubating" and cfg.get("mock_capital") is not None
                            else None
                        ),
                        "is_primary": portfolio_id == cfg["portfolio_id"],
                    }
                )
                if value is not None:
                    bucket["total_value"] += value

        return sorted(buckets.values(), key=lambda b: b["portfolio_id"])


class PreviewPortfolioAssignment:
    """What moving this strategy would cost, without moving it."""

    def __init__(self, registry: StrategyRegistryPort):
        self.registry = registry

    def _lookup(self, strategy_id: str) -> dict[str, Any] | None:
        # get() only sees active live strategies; assignment must also see
        # incubating ones (free to move) and retired ones (refused).
        getter = getattr(self.registry, "get_any", None)
        return getter(strategy_id) if getter else self.registry.get(strategy_id)

    def execute(self, strategy_id: str, portfolio_id: Any) -> dict[str, Any]:
        target = normalize_portfolio_id(portfolio_id)
        return evaluate_assignment(self._lookup(strategy_id), target)


class ReassignStrategyPortfolio:
    """Move a strategy to another portfolio, with the cost acknowledged and recorded."""

    def __init__(self, registry: StrategyRegistryPort):
        self.registry = registry

    def _lookup(self, strategy_id: str) -> dict[str, Any] | None:
        # get() only sees active live strategies; assignment must also see
        # incubating ones (free to move) and retired ones (refused).
        getter = getattr(self.registry, "get_any", None)
        return getter(strategy_id) if getter else self.registry.get(strategy_id)

    def execute(
        self,
        strategy_id: str,
        portfolio_id: Any,
        user_id: str,
        reason: Any = None,
        acknowledge: bool = False,
    ) -> dict[str, Any]:
        target = normalize_portfolio_id(portfolio_id)
        current = self._lookup(strategy_id)
        verdict = evaluate_assignment(current, target)

        if not verdict["changed"]:
            return {"changed": False, "portfolio_id": target, "verdict": verdict}

        if verdict["requires_acknowledgement"] and not acknowledge:
            raise PortfolioReassignmentAcknowledgementRequired(verdict)

        audit = build_assignment_audit(
            current,
            verdict,
            user_id=user_id,
            reason=(str(reason).strip() if reason is not None else ""),
            acknowledged=acknowledge,
        )
        self.registry.reassign_portfolio(strategy_id, target, audit)
        return {"changed": True, "portfolio_id": target, "verdict": verdict}


class ListAssignmentHistory:
    def __init__(self, registry: StrategyRegistryPort):
        self.registry = registry

    def execute(self, strategy_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.registry.list_assignment_history(strategy_id, limit)


class ListBooks:
    """Every book, with what is currently in it.

    Unions declared books with those merely in use, so a book defined and not
    yet filled appears alongside one that predates the feature.
    """

    def __init__(self, registry: StrategyRegistryPort, reader: PortfolioReaderPort):
        self.registry = registry
        self.reader = reader

    def execute(self) -> list[dict[str, Any]]:
        declared = self.registry.list_declared_books()
        in_use = list(self.registry.list_portfolio_ids_in_use())
        in_use += [row["portfolio_id"] for row in self.registry.list_memberships()]
        books = merge_books(declared, in_use)

        # Group by membership, not by the single primary column: a strategy can
        # be in several books and must appear under each of them.
        memberships = self.registry.list_memberships()
        by_strategy: dict[str, list[str]] = {}
        for row in memberships:
            by_strategy.setdefault(row["strategy_id"], []).append(row["portfolio_id"])

        occupancy = {b["portfolio_id"]: [] for b in books}
        for cfg in self.registry.list(active_only=False):
            entry = {
                "id": cfg["id"],
                "name": cfg["name"],
                "strategy_type": cfg["strategy_type"],
                "lifecycle": cfg.get("lifecycle") or "live",
            }
            # Fall back to the primary column if memberships have not been
            # seeded yet, so a book never looks empty when it is not.
            for portfolio_id in by_strategy.get(cfg["id"], [cfg["portfolio_id"]]):
                occupancy.setdefault(portfolio_id, []).append(
                    {**entry, "is_primary": portfolio_id == cfg["portfolio_id"]}
                )

        for book in books:
            book["strategies"] = occupancy.get(book["portfolio_id"], [])
            book["strategy_count"] = len(book["strategies"])
        return books


class CreateBook:
    def __init__(self, registry: StrategyRegistryPort):
        self.registry = registry

    def execute(self, payload: Any, user_id: str) -> dict[str, Any]:
        return self.registry.create_book(validate_book(payload), user_id)


class DeleteBook:
    """Remove a book declaration. The repository refuses if it is occupied."""

    def __init__(self, registry: StrategyRegistryPort):
        self.registry = registry

    def execute(self, portfolio_id: str) -> dict[str, Any]:
        return self.registry.delete_book(normalize_portfolio_id(portfolio_id))


class ChangeBookMembership:
    """Add a strategy to a book, or take it out of one.

    Adding and removing are deliberately asymmetric. Adding takes nothing away
    from the books the strategy is already in, so it is free. Removing makes
    that book's history discontinuous, so it must be acknowledged -- and a
    strategy can never be removed from its last book, because every read in this
    app is scoped by (strategy, portfolio) and it would become unreachable.
    """

    def __init__(self, registry: StrategyRegistryPort):
        self.registry = registry

    def _lookup(self, strategy_id: str) -> dict[str, Any] | None:
        getter = getattr(self.registry, "get_any", None)
        return getter(strategy_id) if getter else self.registry.get(strategy_id)

    def execute(
        self,
        strategy_id: str,
        portfolio_id: Any,
        action: str,
        user_id: str,
        reason: Any = None,
        acknowledge: bool = False,
    ) -> dict[str, Any]:
        target = normalize_portfolio_id(portfolio_id)
        strategy = self._lookup(strategy_id)
        current_books = self.registry.books_for_strategy(strategy_id)
        # Write with the spelling the database holds, when it holds one, so a
        # removal deletes the row that exists rather than a row that does not.
        stored = match_book(target, current_books)
        if stored is not None:
            target = stored

        if action == "add":
            verdict = evaluate_membership_add(strategy, target, current_books)
        elif action == "remove":
            verdict = evaluate_membership_remove(strategy, target, current_books)
        else:
            raise AssignmentValidationError(
                "unknown_action", "Action must be 'add' or 'remove'"
            )

        if not verdict["changed"]:
            return {"changed": False, "portfolio_id": target, "verdict": verdict}

        if verdict["requires_acknowledgement"] and not acknowledge:
            raise MembershipAcknowledgementRequired(verdict)

        audit = build_membership_audit(
            strategy,
            target,
            action,
            user_id=user_id,
            reason=(str(reason).strip() if reason is not None else ""),
            acknowledged=acknowledge,
        )
        new_primary = None
        if action == "add":
            self.registry.add_membership(strategy_id, target, audit)
        else:
            outcome = self.registry.remove_membership(strategy_id, target, audit)
            if isinstance(outcome, dict):
                new_primary = outcome.get("primary_portfolio_id")
        return {
            "changed": True,
            "portfolio_id": target,
            "verdict": verdict,
            # Set only when the removed book was the primary and the registry
            # moved it. None otherwise, and absent for reassignments.
            "primary_portfolio_id": new_primary,
        }

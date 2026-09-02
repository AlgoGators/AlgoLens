"""Portfolio application ports."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from algolens.application.shared.errors import ValidationError


class IncubationError(ValidationError):
    """Raised when an incubation operation violates lifecycle constraints."""


class StrategyNameUnresolved(Exception):
    """Cannot determine the engine's strategy_name from existing rows.

    strategy_name is part of the positions primary key and the engine chooses
    its value, so it has to be read from rows the engine already wrote rather
    than guessed. Guessing writes QT's edit to a different key than the
    engine's row: the write appears to succeed and the engine never sees it.
    """


class RiskAcknowledgementRequired(Exception):
    """The edit breaches a published risk limit and was not acknowledged.

    Per DECISION-1 the gate is advisory -- a breach never blocks the write, it
    only requires the caller to come back having explicitly acknowledged it.
    Carries the verdict so the adapter can return it to the caller.
    """

    def __init__(self, verdict):
        super().__init__("This position breaches a risk limit")
        self.verdict = verdict


@dataclass(frozen=True)
class PortfolioDetailRows:
    latest: Mapping[str, Any] | None
    equity_curve: Sequence[Mapping[str, Any]]
    equity_by_stream: Mapping[str, Sequence[Mapping[str, Any]]]
    positions: Sequence[Mapping[str, Any]]
    executions: Sequence[Mapping[str, Any]]
    yesterday_positions: Sequence[Mapping[str, Any]]


@dataclass(frozen=True)
class IncubationPerformanceRows:
    positions: Sequence[Mapping[str, Any]]
    equity_curve: Sequence[Mapping[str, Any]]


class PortfolioReassignmentAcknowledgementRequired(Exception):
    """Moving a live strategy breaks both portfolios' histories.

    Same shape as RiskAcknowledgementRequired: the caller is told what it costs
    and must come back with an explicit acknowledgement. Maps to HTTP 409.
    """

    def __init__(self, verdict):
        super().__init__("This reassignment breaks portfolio history continuity")
        self.verdict = verdict


class MembershipAcknowledgementRequired(Exception):
    """Removing a strategy from a book breaks that book's history.

    Only removal raises this. Adding a strategy to another book takes nothing
    away from the books it is already in, so it needs no acknowledgement.
    """

    def __init__(self, verdict):
        super().__init__("Removing this strategy breaks the book's history continuity")
        self.verdict = verdict


class StrategyRegistryPort(Protocol):
    def list(self, active_only: bool = True) -> list[dict[str, Any]]:
        ...

    def get(self, strategy_id: str) -> dict[str, Any] | None:
        ...

    def reassign_portfolio(
        self, strategy_id: str, portfolio_id: str, audit: "dict[str, Any]"
    ) -> "dict[str, Any]":
        ...

    def list_assignment_history(
        self, strategy_id: str, limit: int = 100
    ) -> Sequence[dict[str, Any]]:
        # Sequence, not list: `list` is a method name on this Protocol, so it no
        # longer refers to the builtin inside this class body.
        ...


class PortfolioReaderPort(Protocol):
    def fetch_summary_row(
        self, strategy_type: str, portfolio_id: str
    ) -> Mapping[str, Any] | None:
        ...

    def fetch_detail_rows(self, strategy_type: str, portfolio_id: str) -> PortfolioDetailRows:
        ...

    def list_incubating_strategies(self) -> Sequence[Mapping[str, Any]]:
        ...

    def fetch_incubation_performance(
        self, strategy_id: str
    ) -> IncubationPerformanceRows:
        ...

    def start_incubation(
        self,
        strategy_id: str,
        mock_capital: float,
        reason: str,
        user_id: str,
    ) -> None:
        ...

    def promote_to_live(self, strategy_id: str, reason: str, user_id: str) -> None:
        ...

    def retire_strategy(self, strategy_id: str, reason: str, user_id: str) -> None:
        ...

    # -- qt stream writes (F2) ------------------------------------------------

    def fetch_risk_envelope(
        self, strategy_type: str, portfolio_id: str
    ) -> Mapping[str, Any] | None:
        """The envelope trade-ngin published for this book, or None.

        None when the table does not exist yet or holds no row -- the gate
        reports that as "not evaluated" rather than as a pass.
        """
        ...

    def fetch_qt_book(
        self, strategy_type: str, portfolio_id: str
    ) -> Sequence[Mapping[str, Any]]:
        ...

    def write_qt_position(
        self,
        strategy_type: str,
        portfolio_id: str,
        normalized: Mapping[str, Any],
        user_id: str,
        verdict: Mapping[str, Any],
        overrode_risk: bool,
    ) -> Mapping[str, Any]:
        """Upsert one qt position and its audit row, atomically."""
        ...

    def fetch_overrides(
        self, strategy_type: str, limit: int = 100
    ) -> Sequence[Mapping[str, Any]]:
        ...


class BookNotEmpty(Exception):
    """A book still holds strategies and cannot be deleted. Maps to HTTP 409.

    Carries the count so the adapter can build its own message. Rendering
    str(exc) straight into a response is how raw database text reached clients
    from the incubation routes; the shape is avoided here rather than repeated.
    """

    def __init__(self, portfolio_id, occupied):
        super().__init__(f"{portfolio_id} still holds {occupied} strategies")
        self.portfolio_id = portfolio_id
        self.occupied = occupied


class StrategyNotInRegistry(IncubationError):
    """No such strategy. Maps to HTTP 404.

    Typed rather than detected by searching the message for "not found": a
    reason string containing those words would otherwise change the status code
    of an unrelated failure.
    """


class IncubationStorageError(IncubationError):
    """The database refused an incubation write.

    Distinct from IncubationError so the HTTP layer can answer 500 with a fixed
    message. The parent is rendered with str(exc), which is right for the
    domain messages it carries and wrong for a psycopg2 error: those name
    columns and SQL, and were reaching clients as a 400.
    """

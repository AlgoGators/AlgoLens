"""Portfolio application ports."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from algolens.application.shared.errors import ValidationError


class IncubationError(ValidationError):
    """Raised when an incubation operation violates lifecycle constraints."""


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


class StrategyRegistryPort(Protocol):
    def list(self, active_only: bool = True) -> list[dict[str, Any]]:
        ...

    def get(self, strategy_id: str) -> dict[str, Any] | None:
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

"""Portfolio domain models."""

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class StrategyConfig:
    id: str
    strategy_type: str
    portfolio_id: str
    name: str
    description: str
    initial_equity: float
    managers: list[str]
    is_active: bool = True
    sort_order: int = 0


def strategy_config_from_mapping(row: Mapping[str, Any]) -> StrategyConfig:
    return StrategyConfig(
        id=row["id"],
        strategy_type=row["strategy_type"],
        portfolio_id=row["portfolio_id"],
        name=row["name"],
        description=row.get("description") or "",
        initial_equity=float(row.get("initial_equity") or 500000.0),
        managers=list(row.get("managers") or ["AlgoLens System"]),
        is_active=bool(row.get("is_active", True)),
        sort_order=int(row.get("sort_order") or 0),
    )


def strategy_config_to_dict(config: StrategyConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "strategy_type": config.strategy_type,
        "portfolio_id": config.portfolio_id,
        "name": config.name,
        "description": config.description,
        "initial_equity": config.initial_equity,
        "managers": config.managers,
        "is_active": config.is_active,
        "sort_order": config.sort_order,
    }

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

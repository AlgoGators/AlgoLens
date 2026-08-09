"""Portfolio HTTP serializers."""


def _isoformat(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _float_or_none(value):
    return float(value) if value is not None else None


def serialize_strategy_detail(strategy):
    return strategy


def serialize_strategy_list(strategies):
    return {"strategies": strategies}


def serialize_incubating_strategy(strategy):
    return {
        "id": strategy["id"],
        "strategy_type": strategy["strategy_type"],
        "portfolio_id": strategy["portfolio_id"],
        "name": strategy["name"],
        "description": strategy.get("description") or "",
        "mock_capital": _float_or_none(strategy.get("mock_capital")),
        "incubation_started_at": _isoformat(strategy.get("incubation_started_at")),
        "days_elapsed": strategy["days_elapsed"],
        "window_days": strategy["window_days"],
        "progress": strategy["progress"],
    }


def serialize_incubating_strategy_list(strategies):
    return {
        "incubating_strategies": [
            serialize_incubating_strategy(strategy) for strategy in strategies
        ]
    }


def serialize_incubation_performance(performance):
    return {
        "positions": [
            {
                "date": _isoformat(position.get("date")),
                "symbol": position.get("symbol"),
                "quantity": _float_or_none(position.get("quantity")),
                "entry_price": _float_or_none(position.get("entry_price")),
            }
            for position in performance["positions"]
        ],
        "equity_curve": [
            {
                "date": _isoformat(point.get("date")),
                "equity": _float_or_none(point.get("equity")),
            }
            for point in performance["equity_curve"]
        ],
    }

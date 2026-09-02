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


def serialize_portfolio(portfolio):
    return {
        "portfolio_id": portfolio["portfolio_id"],
        "total_value": _float_or_none(portfolio["total_value"]),
        "strategy_count": len(portfolio["strategies"]),
        "strategies": [
            {
                "id": s["id"],
                "name": s["name"],
                "strategy_type": s["strategy_type"],
                "lifecycle": s["lifecycle"],
                "current_value": _float_or_none(s["current_value"]),
            }
            for s in portfolio["strategies"]
        ],
    }


def serialize_portfolio_list(portfolios):
    return {"portfolios": [serialize_portfolio(p) for p in portfolios]}


def serialize_assignment_result(result):
    return {
        "changed": result["changed"],
        "portfolio_id": result["portfolio_id"],
        "assignment_check": result["verdict"],
    }


def serialize_assignment_history(rows):
    return {
        "assignments": [
            {
                "id": row["id"],
                "strategy_id": row["strategy_id"],
                "user_id": row["user_id"],
                "from_portfolio_id": row["from_portfolio_id"],
                "to_portfolio_id": row["to_portfolio_id"],
                "lifecycle_at_move": row["lifecycle_at_move"],
                "reason": row["reason"],
                "consequences": row["consequences"],
                "acknowledged": row["acknowledged"],
                "created_at": _isoformat(row["created_at"]),
            }
            for row in rows
        ]
    }

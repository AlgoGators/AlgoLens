"""Portfolio HTTP routes."""

import time

from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import jwt_required

from algolens.adapters.serializers.portfolio import (
    serialize_strategy_detail,
    serialize_strategy_list,
)
from algolens.application.portfolio.use_cases import (
    GetStrategyDetail,
    ListStrategies,
    StrategyDataNotFound,
    StrategyNotFound,
)
from algolens.infrastructure.config.dependencies import create_portfolio_dependencies

portfolio_bp = Blueprint("portfolio", __name__)


def _portfolio_dependencies():
    return create_portfolio_dependencies()


@portfolio_bp.route("/strategy/<strategy_id>", methods=["GET"])
@jwt_required()
def get_strategy(strategy_id):
    start = time.perf_counter()
    try:
        current_app.logger.info("Fetching strategy: %s", strategy_id)
        registry, reader = _portfolio_dependencies()
        strategy = GetStrategyDetail(registry, reader).execute(strategy_id)
        elapsed_ms = (time.perf_counter() - start) * 1000
        current_app.logger.info(
            "[PORTFOLIO_TIMING] detail strategy_id=%s elapsed_ms=%.0f",
            strategy_id,
            elapsed_ms,
        )
        return jsonify(serialize_strategy_detail(strategy)), 200
    except StrategyNotFound:
        return jsonify({"error": "Strategy not found"}), 404
    except StrategyDataNotFound:
        return jsonify({"error": "No data found for strategy"}), 404
    except Exception as exc:
        current_app.logger.error(
            "Error fetching strategy %s: %s", strategy_id, str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to fetch strategy"}), 500


@portfolio_bp.route("/strategies", methods=["GET"])
@jwt_required()
def get_all_strategies():
    start = time.perf_counter()
    current_app.logger.info("[STRATEGIES] === /strategies endpoint called ===")

    try:
        registry, reader = _portfolio_dependencies()
        strategies = ListStrategies(registry, reader).execute()
        elapsed_ms = (time.perf_counter() - start) * 1000
        current_app.logger.info("[STRATEGIES] Returning %s strategies", len(strategies))
        current_app.logger.info(
            "[PORTFOLIO_TIMING] strategies count=%s elapsed_ms=%.0f",
            len(strategies),
            elapsed_ms,
        )
        return jsonify(serialize_strategy_list(strategies)), 200
    except Exception as exc:
        current_app.logger.error(
            "[STRATEGIES] Error fetching strategies: %s", str(exc), exc_info=True
        )
        return jsonify({"error": "Failed to fetch strategies"}), 500

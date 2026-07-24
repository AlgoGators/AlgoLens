"""Portfolio routes.

Thin HTTP layer: resolve the requested strategy against the data-driven registry
(services.strategy_registry) and delegate all DB access and metric math to
services.portfolio_service. No strategy is hardcoded here anymore.
"""

from flask import Blueprint, jsonify, current_app
from flask_jwt_extended import jwt_required

from services.strategy_registry import get_registry, get_strategy_config
from services.portfolio_service import get_strategy_detail, get_strategy_summary

portfolio_bp = Blueprint("portfolio", __name__)


@portfolio_bp.route("/strategy/<strategy_id>", methods=["GET"])
@jwt_required()
def get_strategy(strategy_id):
    """Fetch full data for one strategy, identified by its public registry id."""
    try:
        current_app.logger.info(f"Fetching strategy: {strategy_id}")

        cfg = get_strategy_config(strategy_id)
        if cfg is None:
            return jsonify({"error": "Strategy not found"}), 404

        strategy = get_strategy_detail(cfg)
        if strategy is None:
            # Known strategy, but no live_results rows yet.
            return jsonify({"error": "No data found for strategy"}), 404

        return jsonify(strategy), 200

    except Exception as e:
        current_app.logger.error(
            f"Error fetching strategy {strategy_id}: {str(e)}", exc_info=True
        )
        return jsonify({"error": "Failed to fetch strategy"}), 500


@portfolio_bp.route("/strategies", methods=["GET"])
@jwt_required()
def get_all_strategies():
    """Get summaries for every active strategy in the registry."""
    current_app.logger.info("[STRATEGIES] === /strategies endpoint called ===")

    try:
        strategies = []
        for cfg in get_registry(active_only=True):
            try:
                summary = get_strategy_summary(cfg)
            except Exception as e:
                # One strategy failing shouldn't blank the whole dashboard.
                current_app.logger.error(
                    f"[STRATEGIES] Failed to summarize {cfg['id']}: {str(e)}",
                    exc_info=True,
                )
                continue
            if summary:
                strategies.append(summary)

        current_app.logger.info(f"[STRATEGIES] Returning {len(strategies)} strategies")
        return jsonify({"strategies": strategies}), 200

    except Exception as e:
        current_app.logger.error(
            f"[STRATEGIES] Error fetching strategies: {str(e)}", exc_info=True
        )
        return jsonify({"error": "Failed to fetch strategies"}), 500

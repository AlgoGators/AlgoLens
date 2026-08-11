"""Compatibility facade for the portfolio application/infrastructure layers."""

import logging

from algolens.application.portfolio.use_cases import (
    build_strategy_detail,
    build_strategy_summary,
)
from algolens.domain.portfolio.calculations import (
    build_historical_data as _build_historical_data,
    compute_return_stats as _compute_return_stats,
    float_or_default as _f,
    resolve_initial_equity as _resolve_initial_equity,
    transform_executions as _transform_executions,
    transform_finalized as _transform_finalized,
    transform_positions as _transform_positions,
)
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository

logger = logging.getLogger(__name__)


def _repository():
    return PostgresPortfolioRepository()


def _fetch_latest_live_results(cursor, strategy_type, portfolio_id):
    return _repository()._fetch_latest_live_results(cursor, strategy_type, portfolio_id)


def _fetch_summary_row(cursor, strategy_type, portfolio_id):
    return _repository()._fetch_summary_row(cursor, strategy_type, portfolio_id)


def _fetch_equity_curve(cursor, strategy_type, portfolio_id):
    return _repository()._fetch_equity_curve(cursor, strategy_type, portfolio_id)


def _fetch_current_positions(cursor, strategy_type, portfolio_id):
    return _repository()._fetch_current_positions(cursor, strategy_type, portfolio_id)


def _fetch_recent_executions(cursor, strategy_type, portfolio_id):
    return _repository()._fetch_recent_executions(cursor, strategy_type, portfolio_id)


def _fetch_yesterday_positions(cursor, strategy_type, portfolio_id):
    return _repository()._fetch_yesterday_positions(cursor, strategy_type, portfolio_id)


def get_strategy_detail(cfg):
    rows = _repository().fetch_detail_rows(cfg["strategy_type"], cfg["portfolio_id"])
    detail = build_strategy_detail(cfg, rows)
    if detail is None:
        logger.warning("[PORTFOLIO] No live_results for %s", cfg["strategy_type"])
    return detail


def get_strategy_summary(cfg):
    latest = _repository().fetch_summary_row(cfg["strategy_type"], cfg["portfolio_id"])
    summary = build_strategy_summary(cfg, latest)
    if summary is None:
        logger.warning("[PORTFOLIO] No summary live_results for %s", cfg["strategy_type"])
    return summary

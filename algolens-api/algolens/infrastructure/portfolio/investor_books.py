"""Fail-closed PostgreSQL reads for automatically published system books."""

from datetime import date

from psycopg2.extras import RealDictCursor

from algolens.infrastructure.db.postgres import get_db_connection


def _day(value):
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError("invalid_date") from None
    if parsed.isoformat() != value:
        raise ValueError("invalid_date")
    return parsed


class PostgresInvestorBookRepository:
    def __init__(self, connection_factory=None):
        self.connection_factory = connection_factory or get_db_connection

    def read(self, user_id, portfolio_id, source_day=None):
        source_day = _day(source_day)
        conn = self.connection_factory()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                day_clause = "AND p.source_day = %s" if source_day is not None else ""
                params = (user_id, portfolio_id)
                if source_day is not None:
                    params += (source_day,)
                cursor.execute(
                    f"""
                    SELECT p.publication_id, p.portfolio_id, p.source_day,
                           p.strategy_id, p.model_stream, p.content_digest,
                           p.published_at
                    FROM trading.investor_book_publications p
                    JOIN trading.investor_books b
                      ON b.book_id = p.book_id AND b.portfolio_id = p.portfolio_id
                    JOIN trading.investor_book_access a
                      ON a.portfolio_id = p.portfolio_id
                    JOIN auth.users u ON u.id = a.user_id
                    WHERE a.user_id = %s AND p.portfolio_id = %s
                      {day_clause}
                      AND a.is_active AND b.is_active
                      AND p.model_stream = 'system'
                      AND (u.role = 'investor' OR u.role LIKE 'subscriber_%%')
                    ORDER BY p.source_day DESC
                    LIMIT 1
                    """,
                    params,
                )
                publication = cursor.fetchone()
                if publication is None:
                    return None
                scope = (
                    publication["portfolio_id"],
                    publication["strategy_id"],
                    publication["source_day"],
                )
                cursor.execute(
                    """
                    SELECT strategy_name, symbol, quantity, average_price,
                           daily_realized_pnl, daily_unrealized_pnl
                    FROM trading.positions
                    WHERE portfolio_id = %s AND strategy_id = %s AND date = %s
                      AND portfolio_type = 'system'
                    ORDER BY strategy_name, symbol
                    """,
                    scope,
                )
                positions = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT strategy_id, current_portfolio_value,
                           total_cumulative_return, total_annualized_return,
                           daily_return, volatility, sharpe_ratio, sortino_ratio,
                           max_drawdown
                    FROM trading.live_results
                    WHERE portfolio_id = %s AND strategy_id = %s AND date = %s
                      AND portfolio_type = 'system'
                    ORDER BY strategy_id
                    """,
                    scope,
                )
                results = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT timestamp, equity
                    FROM trading.equity_curve
                    WHERE portfolio_id = %s AND strategy_id = %s
                      AND (timestamp AT TIME ZONE 'UTC')::date = %s
                      AND portfolio_type = 'system'
                    ORDER BY timestamp
                    """,
                    scope,
                )
                equity = cursor.fetchall()
                return {
                    "publication": publication,
                    "positions": positions,
                    "results": results,
                    "equity": equity,
                }
        finally:
            conn.close()

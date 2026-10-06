"""The public portfolio starts with an empty history on its launch date."""

from datetime import date, datetime, timezone

from algolens.infrastructure.config.dependencies import create_portfolio_dependencies
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository


LAUNCH_DATE = date(2026, 10, 1)
LAUNCH_INSTANT = datetime(2026, 10, 1, tzinfo=timezone.utc)


class RecordingCursor:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        self.calls.append((" ".join(sql.split()), tuple(params)))

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class RecordingConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor

    def cursor(self):
        return self.cursor_obj

    def close(self):
        pass


def _repository(cursor=None):
    cursor = cursor or RecordingCursor()
    return (
        PostgresPortfolioRepository(
            connection_factory=lambda: RecordingConnection(cursor),
            launch_date=LAUNCH_DATE,
        ),
        cursor,
    )


def test_runtime_composition_sets_tomorrows_fixed_launch_boundary():
    _, reader = create_portfolio_dependencies(connection_factory=lambda: None)

    assert reader.launch_date == LAUNCH_DATE


def test_result_and_equity_queries_exclude_prelaunch_history(monkeypatch):
    repository, cursor = _repository()
    monkeypatch.setattr(repository, "_has_portfolio_type", lambda *_: True)

    repository._fetch_latest_live_results(cursor, "TREND", "BOOK")
    repository._fetch_summary_row(cursor, "TREND", "BOOK")
    repository._fetch_equity_curve(
        cursor,
        "TREND",
        "BOOK",
        "qt",
        has_portfolio_type=True,
    )

    result_calls = [call for call in cursor.calls if "trading.live_results" in call[0]]
    assert len(result_calls) == 2
    for sql, params in result_calls:
        assert "AND date >= %s" in sql
        assert params[-1] == LAUNCH_DATE

    equity_sql, equity_params = next(
        call for call in cursor.calls if "trading.equity_curve" in call[0]
    )
    assert "AND timestamp >= %s" in equity_sql
    assert equity_params[-1] == LAUNCH_INSTANT


def test_current_and_previous_position_queries_cannot_select_prelaunch_snapshots():
    repository, cursor = _repository()

    repository._fetch_current_positions(
        cursor, "TREND", "BOOK", "system", has_portfolio_type=True
    )
    repository._fetch_yesterday_positions(
        cursor, "TREND", "BOOK", "qt", has_portfolio_type=True
    )

    current_sql, current_params = cursor.calls[0]
    assert current_sql.count("AND date >= %s") == 2
    assert current_params.count(LAUNCH_DATE) == 2

    previous_sql, previous_params = cursor.calls[1]
    assert previous_sql.count("AND date >= %s") == 3
    assert previous_params.count(LAUNCH_DATE) == 3


def test_detail_snapshot_metadata_and_held_symbols_obey_the_same_boundary(monkeypatch):
    repository, cursor = _repository()
    monkeypatch.setattr(repository, "_has_portfolio_type", lambda *_: True)

    repository.fetch_detail_rows("TREND", "BOOK", "system")
    repository.held_symbols(["BOOK"], portfolio_type="system")

    snapshot_calls = [
        call
        for call in cursor.calls
        if call[0].startswith("SELECT date, strategy_name FROM trading.positions")
    ]
    # The selected position stream and the reporting stream are both system,
    # so the repository performs one scoped metadata read rather than reading
    # the same stream twice.
    assert len(snapshot_calls) == 1
    for sql, params in snapshot_calls:
        assert sql.count("AND date >= %s") == 2
        assert params.count(LAUNCH_DATE) == 2

    held_sql, held_params = next(
        call
        for call in cursor.calls
        if call[0].startswith("SELECT DISTINCT symbol FROM trading.positions")
    )
    assert held_sql.count("AND date >= %s") == 2
    assert held_params.count(LAUNCH_DATE) == 2

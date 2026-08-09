from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry


class FakeCursor:
    def __init__(self, *, has_lifecycle, rows):
        self.has_lifecycle = has_lifecycle
        self.rows = rows
        self.calls = []
        self.result = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if "information_schema.columns" in sql:
            self.result = {"exists": 1} if self.has_lifecycle else None
        elif "FROM trading.strategy_registry" in sql:
            self.result = self.rows
        else:
            raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self.result

    def fetchall(self):
        return self.result


class FakeConnection:
    def __init__(self, cursor):
        self.cursor_obj = cursor
        self.closed = False

    def cursor(self):
        return self.cursor_obj

    def close(self):
        self.closed = True


def make_row(strategy_id, *, lifecycle=None, is_active=True):
    row = {
        "id": strategy_id,
        "strategy_type": f"{strategy_id.upper()}_TYPE",
        "portfolio_id": f"{strategy_id.upper()}_PORTFOLIO",
        "name": strategy_id.title(),
        "description": "",
        "initial_equity": 100000,
        "managers": ["AlgoLens System"],
        "is_active": is_active,
        "sort_order": 0,
    }
    if lifecycle is not None:
        row["lifecycle"] = lifecycle
    return row


def test_list_treats_missing_lifecycle_column_as_live():
    cursor = FakeCursor(
        has_lifecycle=False,
        rows=[
            make_row("alpha"),
            make_row("beta"),
            make_row("inactive", is_active=False),
        ],
    )
    registry = PostgresStrategyRegistry(
        connection_factory=lambda: FakeConnection(cursor)
    )

    strategies = registry.list(active_only=True)

    assert [strategy["id"] for strategy in strategies] == ["alpha", "beta"]
    assert all(strategy["lifecycle"] == "live" for strategy in strategies)
    registry_select = cursor.calls[1][0]
    assert "lifecycle" not in registry_select


def test_list_filters_incubating_rows_when_lifecycle_column_exists():
    cursor = FakeCursor(
        has_lifecycle=True,
        rows=[
            make_row("live", lifecycle="live"),
            make_row("incubating", lifecycle="incubating"),
            make_row("inactive", lifecycle="live", is_active=False),
        ],
    )
    registry = PostgresStrategyRegistry(
        connection_factory=lambda: FakeConnection(cursor)
    )

    strategies = registry.list(active_only=True)

    assert [strategy["id"] for strategy in strategies] == ["live"]
    registry_select = cursor.calls[1][0]
    assert "lifecycle" in registry_select

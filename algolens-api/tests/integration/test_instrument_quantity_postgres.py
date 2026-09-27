"""Instrument-aware QT quantity edits against disposable PostgreSQL schemas.

The metadata fixture has the production column spellings. Both schemas are
claimed before use and may be dropped only when marked as test-owned.
"""

from collections.abc import Mapping
from decimal import Decimal
from functools import partial

import pytest

from tests.integration.conftest import OWNERSHIP_MARK, claim_schema, require_test_dsn

psycopg2 = pytest.importorskip("psycopg2")
psycopg2_extras = pytest.importorskip("psycopg2.extras")

from algolens.application.portfolio.use_cases import UpsertQtPosition
from algolens.domain.portfolio.position_edit import PositionValidationError
from algolens.infrastructure.config.dependencies import create_instrument_catalog
from algolens.infrastructure.portfolio.instrument_catalog import PostgresInstrumentCatalog
from algolens.infrastructure.portfolio.repositories import PostgresPortfolioRepository

pytestmark = pytest.mark.integration

STRATEGY_ID = "itest_quantity"
STRATEGY_TYPE = "ITEST_QUANTITY"
STRATEGY_NAME = "Quantity Integration"
PORTFOLIO_ID = "ITEST_QUANTITY_BOOK"
METADATA_MARK = "owned by test_instrument_quantity_postgres; safe to drop"


def _refuse_unowned_metadata(cur):
    cur.execute(
        "SELECT obj_description(oid, 'pg_namespace') AS ownership_mark "
        "FROM pg_namespace "
        "WHERE nspname = 'metadata'"
    )
    row = cur.fetchone()
    mark = (row["ownership_mark"] if isinstance(row, Mapping) else row[0]) if row else None
    if row is not None and mark != METADATA_MARK:
        pytest.fail("Refusing to replace an unowned metadata schema")


@pytest.fixture()
def db():
    dsn = require_test_dsn()
    setup = psycopg2.connect(dsn)
    setup.autocommit = True
    try:
        with setup.cursor() as cur:
            _refuse_unowned_metadata(cur)
            claim_schema(cur)
            cur.execute("DROP SCHEMA IF EXISTS metadata CASCADE")
            cur.execute("CREATE SCHEMA metadata")
            cur.execute("COMMENT ON SCHEMA metadata IS %s", (METADATA_MARK,))
            cur.execute(
                """
                CREATE TABLE metadata.contract_metadata (
                    "Databento Symbol" TEXT PRIMARY KEY,
                    "IB Symbol" TEXT,
                    "Name" TEXT,
                    "Asset Type" TEXT,
                    "Exchange" TEXT,
                    "Contract Size" DOUBLE PRECISION,
                    "Tick Size" TEXT
                );
                CREATE TABLE trading.strategy_registry (
                    id TEXT PRIMARY KEY, strategy_type TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL, name TEXT NOT NULL,
                    lifecycle TEXT DEFAULT 'live'
                );
                -- These cases deliberately exercise the explicitly disabled
                -- legacy writer, including its under-lock capability check.
                CREATE TABLE trading.qt_workflow_capabilities (
                    book_id TEXT PRIMARY KEY, enabled BOOLEAN NOT NULL,
                    version INTEGER NOT NULL CHECK (version > 0)
                );
                CREATE TABLE trading.positions (
                    symbol VARCHAR NOT NULL, quantity NUMERIC NOT NULL,
                    average_price NUMERIC NOT NULL,
                    daily_unrealized_pnl NUMERIC NOT NULL,
                    daily_realized_pnl NUMERIC NOT NULL,
                    last_update TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    strategy_id VARCHAR NOT NULL,
                    strategy_name VARCHAR NOT NULL,
                    date DATE NOT NULL,
                    portfolio_id VARCHAR NOT NULL,
                    portfolio_type TEXT NOT NULL DEFAULT 'system',
                    CONSTRAINT positions_portfolio_type_check
                        CHECK (portfolio_type IN (
                            'system', 'qt', 'benchmark', 'benchmark_rebench',
                            'benchmark_frozen_shadow')),
                    CONSTRAINT positions_pkey PRIMARY KEY (
                        portfolio_id, strategy_id, strategy_name, date,
                        symbol, portfolio_type)
                );
                CREATE TABLE trading.risk_limits (
                    id BIGSERIAL PRIMARY KEY, strategy_id TEXT NOT NULL,
                    portfolio_id TEXT NOT NULL, limits JSONB NOT NULL,
                    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
                );
                CREATE TABLE trading.position_overrides (
                    id BIGSERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    source_app TEXT NOT NULL
                        CHECK (source_app IN ('algolens', 'manual_db_edit')),
                    strategy_id TEXT NOT NULL, symbol TEXT NOT NULL,
                    before_state JSONB NOT NULL, after_state JSONB NOT NULL,
                    reason TEXT NOT NULL CHECK (length(btrim(reason)) > 0),
                    risk_check_result JSONB NOT NULL,
                    overrode_risk BOOLEAN NOT NULL DEFAULT FALSE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    portfolio_id TEXT,
                    CONSTRAINT position_overrides_new_rows_require_portfolio
                        CHECK (portfolio_id IS NOT NULL) NOT VALID
                );
                CREATE TABLE trading.strategy_book_memberships (
                    strategy_id TEXT NOT NULL, portfolio_id TEXT NOT NULL,
                    added_by TEXT, added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy_id, portfolio_id)
                );
                """
            )
            cur.execute(
                "INSERT INTO trading.strategy_registry "
                "(id, strategy_type, portfolio_id, name) VALUES (%s, %s, %s, %s)",
                (STRATEGY_ID, STRATEGY_TYPE, PORTFOLIO_ID, STRATEGY_NAME),
            )
            cur.execute(
                "INSERT INTO trading.qt_workflow_capabilities VALUES (%s, false, 1)",
                (PORTFOLIO_ID,),
            )
            cur.executemany(
                'INSERT INTO metadata.contract_metadata '
                '("Databento Symbol", "IB Symbol", "Asset Type") '
                'VALUES (%s, %s, %s)',
                [
                    ("ES", "ES", "FUTURE"),
                    ("SPY", "SPY", "EQUITY"),
                    ("BRK.B", "BRK B", "EQUITY"),
                    ("BRK", "BRK", "FUTURE"),
                    ("NQ_DB", "NQ", "FUTURE"),
                    ("DUP_ONE", "DUP", "EQUITY"),
                    ("DUP_TWO", "DUP", "FUTURE"),
                    ("COIN", "COIN", "CRYPTO"),
                    ("BLANK", "BLANK", None),
                ],
            )
            cur.execute(
                "INSERT INTO trading.positions "
                "(portfolio_id, strategy_id, strategy_name, date, symbol, "
                "portfolio_type, quantity, average_price, daily_unrealized_pnl, "
                "daily_realized_pnl, last_update) "
                "VALUES (%s, %s, %s, CURRENT_DATE, 'ES', 'qt', 4, 5280.25, 0, 0, now())",
                (PORTFOLIO_ID, STRATEGY_TYPE, STRATEGY_NAME),
            )
    finally:
        setup.close()

    def factory():
        return psycopg2.connect(dsn, cursor_factory=psycopg2_extras.RealDictCursor)

    try:
        yield factory
    finally:
        cleanup = psycopg2.connect(dsn)
        cleanup.autocommit = True
        try:
            with cleanup.cursor() as cur:
                _refuse_unowned_metadata(cur)
                cur.execute("DROP SCHEMA IF EXISTS metadata CASCADE")
                # claim_schema's ownership marker is checked again at cleanup.
                cur.execute(
                    "SELECT obj_description(oid, 'pg_namespace') "
                    "FROM pg_namespace WHERE nspname = 'trading'"
                )
                row = cur.fetchone()
                if row is not None and row[0] != OWNERSHIP_MARK:
                    pytest.fail("Refusing to drop an unowned trading schema")
                cur.execute("DROP SCHEMA IF EXISTS trading CASCADE")
        finally:
            cleanup.close()


class _Registry:
    def books_for_strategy(self, strategy_id):
        return [PORTFOLIO_ID] if strategy_id == STRATEGY_ID else []

    def get(self, strategy_id):
        if strategy_id != STRATEGY_ID:
            return None
        return {
            "id": STRATEGY_ID,
            "strategy_type": STRATEGY_TYPE,
            "portfolio_id": PORTFOLIO_ID,
            "name": STRATEGY_NAME,
            "lifecycle": "live",
        }


def _use_case(db, *, with_catalog=True):
    catalog = PostgresInstrumentCatalog(connection_factory=db) if with_catalog else None
    return UpsertQtPosition(
        _Registry(), PostgresPortfolioRepository(connection_factory=db),
        instrument_catalog=catalog,
    )


def _edit(db, symbol, quantity, *, acknowledge_risk=True, price=None,
          with_catalog=True):
    payload = {
        "strategy_id": STRATEGY_ID,
        "symbol": symbol,
        "quantity": quantity,
        "reason": "instrument quantity integration",
    }
    if price is not None:
        payload["average_price"] = price
    return _use_case(db, with_catalog=with_catalog).execute(
        payload, user_id="42", acknowledge_risk=acknowledge_risk
    )


def _state(db):
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, portfolio_type, quantity, average_price "
                "FROM trading.positions ORDER BY symbol, portfolio_type"
            )
            positions = [
                (row["symbol"], row["portfolio_type"], row["quantity"],
                 row["average_price"])
                for row in cur.fetchall()
            ]
            cur.execute(
                "SELECT symbol, before_state, after_state "
                "FROM trading.position_overrides ORDER BY id"
            )
            audits = [
                (row["symbol"], row["before_state"], row["after_state"])
                for row in cur.fetchall()
            ]
            return positions, audits
    finally:
        conn.close()


def _change_metadata(db, sql, params=()):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                _refuse_unowned_metadata(cur)
                cur.execute(sql, params)
    finally:
        conn.close()


def _full_state(db):
    """Capture entire rows so a rejected edit cannot hide a timestamp/PnL change."""
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT to_jsonb(p) AS state FROM trading.positions AS p "
                "ORDER BY portfolio_id, strategy_id, strategy_name, date, "
                "symbol, portfolio_type"
            )
            positions = [row["state"] for row in cur.fetchall()]
            cur.execute(
                "SELECT to_jsonb(o) AS state FROM trading.position_overrides AS o "
                "ORDER BY id"
            )
            audits = [row["state"] for row in cur.fetchall()]
            return positions, audits
    finally:
        conn.close()


def _assert_rejected_without_write(db, symbol, quantity, expected_code,
                                   *, price=None, with_catalog=True):
    before = _full_state(db)
    with pytest.raises(PositionValidationError) as exc:
        _edit(db, symbol, quantity, price=price, with_catalog=with_catalog)
    assert exc.value.code == expected_code
    assert _full_state(db) == before


def test_equity_fraction_round_trips_exactly_through_position_and_audit(db):
    result = _edit(db, "SPY", "2.5", price="500.12345678")
    assert result["position"]["quantity_exact"] == "2.5"
    positions, audits = _state(db)
    assert ("SPY", "qt", Decimal("2.5"), Decimal("500.12345678")) in positions
    assert len(audits) == 1
    assert audits[0][0] == "SPY"
    assert audits[0][1] == {}
    assert audits[0][2]["quantity_exact"] == "2.5"
    assert audits[0][2]["average_price_exact"] == "500.12345678"


@pytest.mark.parametrize("quantity", ["2.5", "-2.5"])
def test_fractional_future_is_rejected_even_with_risk_acknowledged(db, quantity):
    _assert_rejected_without_write(
        db, "ES", quantity, "quantity_futures_whole_required"
    )


@pytest.mark.parametrize("quantity", ["-3", "0"])
def test_signed_whole_future_and_zero_close_are_audited(db, quantity):
    result = _edit(db, "ES", quantity)
    assert result["position"]["quantity_exact"] == str(int(quantity))
    positions, audits = _state(db)
    assert ("ES", "qt", Decimal(quantity), Decimal("5280.25")) in positions
    assert len(audits) == 1
    assert audits[0][1]["quantity_exact"] == "4"
    assert audits[0][2]["quantity_exact"] == str(int(quantity))
    assert audits[0][2]["average_price_exact"] == "5280.25"


@pytest.mark.parametrize(
    "symbol,quantity,code",
    [
        ("UNKNOWN", "2.5", "instrument_type_unavailable"),
        ("DUP", "2.5", "instrument_type_ambiguous"),
        ("COIN", "2.5", "instrument_type_unsupported"),
        ("BLANK", "2.5", "instrument_type_unavailable"),
    ],
)
def test_unresolved_instrument_never_changes_position_or_audit(
    db, symbol, quantity, code
):
    _assert_rejected_without_write(db, symbol, quantity, code, price="100")


def test_missing_catalog_fails_closed_before_a_position_write(db):
    _assert_rejected_without_write(
        db, "SPY", "2.5", "instrument_type_unavailable",
        price="100", with_catalog=False,
    )


def test_canonical_symbol_colliding_with_ib_alias_is_ambiguous(db):
    _change_metadata(
        db, 'INSERT INTO metadata.contract_metadata '
        '("Databento Symbol", "IB Symbol", "Asset Type") '
        'VALUES (%s, %s, %s)',
        ("OTHER_SPY", "SPY", "FUTURE"),
    )
    _assert_rejected_without_write(
        db, "SPY", "2.5", "instrument_type_ambiguous", price="100"
    )


@pytest.mark.parametrize("symbol", ["NQ.v.12", "NQ.c.3", "NQ.n.4"])
def test_ib_alias_and_continuous_future_suffix_resolve_as_future(db, symbol):
    catalog = PostgresInstrumentCatalog(connection_factory=db)
    assert catalog.resolve_asset_type("NQ") == "FUTURE"
    assert catalog.resolve_asset_type(symbol) == "FUTURE"
    _assert_rejected_without_write(
        db, symbol, "2.5", "quantity_futures_whole_required", price="100"
    )
    result = _edit(db, symbol, "-2", price="100")
    assert result["position"]["quantity_exact"] == "-2"


def test_nonnumeric_roll_suffix_does_not_guess_a_future_root(db):
    _assert_rejected_without_write(
        db, "NQ.v.abc", "2", "instrument_type_unavailable", price="100"
    )


def test_continuous_suffix_cannot_reclassify_equity_root_as_future(db):
    _assert_rejected_without_write(
        db, "SPY.v.0", "2", "instrument_type_unavailable", price="100"
    )


def test_dotted_equity_uses_its_exact_symbol_not_the_root_future(db):
    catalog = PostgresInstrumentCatalog(connection_factory=db)
    assert catalog.resolve_asset_type("BRK.B") == "EQUITY"
    result = _edit(db, "BRK.B", "2.5", price="300")
    assert result["position"]["quantity_exact"] == "2.5"
    _assert_rejected_without_write(
        db, "BRK.X", "2.5", "instrument_type_unavailable", price="300"
    )


def test_duplicate_exact_metadata_rows_are_ambiguous(db):
    # A malformed restore can have duplicate rows even though the usual schema
    # has a primary key. The catalog must check row cardinality, not take first.
    _change_metadata(
        db, "ALTER TABLE metadata.contract_metadata "
        "DROP CONSTRAINT contract_metadata_pkey"
    )
    _change_metadata(
        db, 'INSERT INTO metadata.contract_metadata '
        '("Databento Symbol", "IB Symbol", "Asset Type") '
        'VALUES (%s, %s, %s)',
        ("ES", "ES", "FUTURE"),
    )
    _assert_rejected_without_write(
        db, "ES", "5", "instrument_type_ambiguous"
    )


@pytest.mark.parametrize(
    "defect",
    [
        "DROP TABLE metadata.contract_metadata",
        'ALTER TABLE metadata.contract_metadata DROP COLUMN "Asset Type"',
    ],
)
def test_catalog_sql_shape_failure_fails_closed_without_write(db, defect):
    _change_metadata(db, defect)
    _assert_rejected_without_write(
        db, "ES", "5", "instrument_type_unavailable"
    )


def test_rejection_preserves_existing_basis_and_noneditable_rows(db):
    conn = db()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE trading.positions SET average_price = %s "
                    "WHERE symbol = 'ES' AND portfolio_type = 'qt'",
                    (Decimal("92233720368.12345678"),),
                )
                cur.execute(
                    "INSERT INTO trading.positions "
                    "(portfolio_id, strategy_id, strategy_name, date, symbol, "
                    "portfolio_type, quantity, average_price, daily_unrealized_pnl, "
                    "daily_realized_pnl, last_update) "
                    "VALUES (%s, %s, %s, CURRENT_DATE, 'ES', 'system', "
                    "8, 777.12345678, 0, 0, now())",
                    (PORTFOLIO_ID, STRATEGY_TYPE, STRATEGY_NAME),
                )
    finally:
        conn.close()
    _assert_rejected_without_write(
        db, "ES", "2.5", "quantity_futures_whole_required"
    )


def _wire_legacy_capability_to_postgres(db, monkeypatch):
    from types import SimpleNamespace
    import algolens.adapters.http.qt_workflow as qt_http
    from algolens.infrastructure.portfolio.book_lock import acquire_qt_book_locks
    from algolens.infrastructure.portfolio.qt_publication_proof import require_legacy_qt_disabled

    # Current-user VerifySession remains the route's actual authorization
    # dependency. This legacy fixture supplies its owned SQL capability seam;
    # enabled/missing/invalid capability is still rejected by the real guard.
    def ensure_disabled(book_id, actor_id):
        assert type(actor_id) is int and actor_id > 0
        connection = db()
        try:
            with connection:
                with connection.cursor() as cursor:
                    acquire_qt_book_locks(cursor, book_id)
                    require_legacy_qt_disabled(cursor, book_id)
        finally:
            connection.close()

    monkeypatch.setattr(qt_http, "_read_service", lambda: SimpleNamespace(ensure_legacy_disabled=ensure_disabled))


def _wire_route_to_postgres(db, monkeypatch):
    import algolens.adapters.http.portfolio as portfolio_http

    _wire_legacy_capability_to_postgres(db, monkeypatch)
    reader = PostgresPortfolioRepository(connection_factory=db)
    monkeypatch.setattr(
        portfolio_http, "create_portfolio_dependencies",
        lambda: (_Registry(), reader),
    )
    monkeypatch.setattr(portfolio_http, "create_market_data", lambda: None)
    # Route composition still calls the real dependency factory. Only the
    # connection seam points at this fixture's guarded disposable database.
    monkeypatch.setattr(
        portfolio_http, "create_instrument_catalog",
        partial(create_instrument_catalog, connection_factory=db),
    )


def test_http_equity_fraction_uses_real_catalog_and_audited_postgres_write(
    db, client, monkeypatch
):
    from tests.test_position_edit_routes import _set_jwt_cookie

    _wire_route_to_postgres(db, monkeypatch)
    csrf = _set_jwt_cookie(client)
    raw = (
        '{"strategy_id":"itest_quantity","symbol":"SPY",'
        '"quantity":2.5,"average_price":500.12345678,'
        '"reason":"route equity fraction"}'
    )
    response = client.post(
        "/portfolio/positions", data=raw, content_type="application/json",
        headers={"X-CSRF-TOKEN": csrf},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["position"]["quantity_exact"] == "2.5"
    assert body["position"]["average_price_exact"] == "500.12345678"
    positions, audits = _state(db)
    assert ("SPY", "qt", Decimal("2.5"), Decimal("500.12345678")) in positions
    assert len(audits) == 1
    assert audits[0][0] == "SPY"
    assert audits[0][1] == {}
    assert audits[0][2]["quantity_exact"] == "2.5"
    assert audits[0][2]["average_price_exact"] == "500.12345678"


def test_http_future_fraction_rejects_spoofed_equity_even_with_acknowledgement(
    db, client, monkeypatch
):
    from tests.test_position_edit_routes import _set_jwt_cookie

    _wire_route_to_postgres(db, monkeypatch)
    csrf = _set_jwt_cookie(client)
    before = _full_state(db)
    raw = (
        '{"strategy_id":"itest_quantity","symbol":"ES",'
        '"quantity":2.5,"asset_type":"EQUITY",'
        '"acknowledge_risk":true,"reason":"spoofed equity"}'
    )
    response = client.post(
        "/portfolio/positions", data=raw, content_type="application/json",
        headers={"X-CSRF-TOKEN": csrf},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "quantity_futures_whole_required"
    assert _full_state(db) == before

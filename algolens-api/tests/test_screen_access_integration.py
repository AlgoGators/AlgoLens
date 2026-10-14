"""Postgres-backed tests of AlgoLens migration 003 (screen access, investor
reports) and the repositories that use it.

Opt-in: see tests/qt_fixture.py (ALGOLENS_TEST_DATABASE_URL, localhost only).
The trading schema is new_algo_data's after 021-026 (qt_fixture, "026"); the
auth schema is built here in the shape new_algo_data has (auth.users with the
auth.user_role enum). The repositories connect as svc_algolens, holding only
what production grants it on auth.users plus what 003 grants, so a privilege
003 forgot fails here as it would in production.
"""

from datetime import date, datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest

from qt_fixture import DB_URL, assert_local, build_schema, drop_schema, requires_db

pytestmark = requires_db

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "003_screen_access.sql"
ROLLBACK = Path(__file__).resolve().parents[1] / "migrations" / "003_screen_access_rollback.sql"
APP_ROLE = "svc_algolens"  # 003 grants to this role by name
QT = "QT_CONSERVATIVE_PORTFOLIO"
MODEL = "QT_CONSERVATIVE_MODEL_PORTFOLIO"
PDF = b"%PDF-1.4\n%test\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"

AUTH_SCHEMA = f"""
DROP SCHEMA IF EXISTS investor CASCADE;
DROP SCHEMA IF EXISTS auth CASCADE;
CREATE SCHEMA auth;
CREATE TYPE auth.user_role AS ENUM ('general_member', 'team_lead', 'exec_board');
CREATE TABLE auth.users (
    id            SERIAL PRIMARY KEY,
    email         VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(256) NOT NULL DEFAULT '',
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    role          auth.user_role NOT NULL,
    first_name    VARCHAR(120) NOT NULL DEFAULT '',
    last_name     VARCHAR(120) NOT NULL DEFAULT ''
);
INSERT INTO auth.users (email, role) VALUES
    ('member@x.com', 'general_member'),
    ('lead@x.com', 'team_lead'),
    ('exec@x.com', 'exec_board');
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        CREATE ROLE {APP_ROLE} NOLOGIN;
    END IF;
END $$;
-- What production grants svc_algolens on auth (\\dp auth.*, 2026-10-11).
GRANT USAGE ON SCHEMA auth TO {APP_ROLE};
GRANT SELECT, INSERT, UPDATE, DELETE ON auth.users TO {APP_ROLE};
GRANT SELECT, USAGE ON SEQUENCE auth.users_id_seq TO {APP_ROLE};
GRANT USAGE ON SCHEMA trading, metadata, futures_data TO {APP_ROLE};
GRANT SELECT ON ALL TABLES IN SCHEMA trading, metadata, futures_data TO {APP_ROLE};
"""


@pytest.fixture
def db():
    """A connection factory (as svc_algolens) with .setup, an autocommit
    superuser connection, on a fresh schema with 003 applied."""
    from psycopg2.extras import RealDictCursor

    assert_local(DB_URL)
    setup = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    setup.autocommit = True
    with setup.cursor() as cur:
        build_schema(cur, "026")
        cur.execute(AUTH_SCHEMA)
        cur.execute(MIGRATION.read_text(encoding="utf-8"))

    def factory():
        conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
        with conn.cursor() as cur:
            cur.execute(f"SET ROLE {APP_ROLE}")
        conn.commit()
        return conn

    factory.setup = setup
    yield factory

    with setup.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS investor CASCADE; DROP SCHEMA IF EXISTS auth CASCADE;")
        drop_schema(cur)
    setup.close()


def _q(db, sql, params=()):
    with db.setup.cursor() as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except psycopg2.ProgrammingError:
            return None


def _uid(db, email):
    return _q(db, "SELECT id FROM auth.users WHERE email = %s", (email,))[0]["id"]


def _screens(db):
    rows = _q(
        db,
        """
        SELECT u.email, array_agg(a.screen ORDER BY a.screen) AS screens
        FROM auth.user_screen_access a JOIN auth.users u ON u.id = a.user_id
        GROUP BY u.email ORDER BY u.email
        """,
    )
    return {r["email"]: list(r["screens"]) for r in rows}


def screen_repo(db):
    from algolens.infrastructure.identity.screen_access import PostgresScreenAccessRepository

    return PostgresScreenAccessRepository(connection_factory=db)


def investor_repo(db):
    from algolens.infrastructure.investor.repositories import PostgresInvestorRepository

    return PostgresInvestorRepository(connection_factory=db)


# --- migration ----------------------------------------------------------------


def test_backfill_keeps_todays_access(db):
    assert _screens(db) == {
        "exec@x.com": ["member", "qt"],
        "lead@x.com": ["member"],
        "member@x.com": ["member"],
    }
    log = _q(db, "SELECT count(*) AS n FROM auth.screen_access_log WHERE by_email = 'migration:003'")
    assert log[0]["n"] == 4


def test_migration_is_idempotent(db):
    _q(db, MIGRATION.read_text(encoding="utf-8"))
    assert _screens(db)["exec@x.com"] == ["member", "qt"]
    log = _q(db, "SELECT count(*) AS n FROM auth.screen_access_log")
    assert log[0]["n"] == 4


def test_new_signups_get_no_screen(db):
    _q(db, "INSERT INTO auth.users (email, role) VALUES ('new@x.com', 'general_member')")
    assert "new@x.com" not in _screens(db)
    assert screen_repo(db).screens_for(_uid(db, "new@x.com")) == []


def test_rollback_drops_everything_003_added(db):
    _q(db, ROLLBACK.read_text(encoding="utf-8"))
    tables = _q(
        db,
        """
        SELECT to_regclass('auth.user_screen_access') AS a, to_regclass('auth.screen_access_log') AS l,
               to_regnamespace('investor') AS i
        """,
    )[0]
    assert tables == {"a": None, "l": None, "i": None}


def test_missing_table_is_reported_for_the_fallback(db):
    from algolens.application.identity.screen_access import ScreenAccessUnavailable

    _q(db, ROLLBACK.read_text(encoding="utf-8"))
    with pytest.raises(ScreenAccessUnavailable):
        screen_repo(db).screens_for(1)


# --- screen access repository -------------------------------------------------


def test_set_screens_grants_revokes_and_logs(db):
    member = _uid(db, "member@x.com")
    repo = screen_repo(db)

    screens, granted, revoked = repo.set_screens(member, ("investor", "qt"), "admin@x.com")

    assert sorted(screens) == ["investor", "qt"]
    assert granted == ("investor", "qt") and revoked == ("member",)
    assert sorted(repo.screens_for(member)) == ["investor", "qt"]
    log = _q(
        db,
        "SELECT screen, action, by_email FROM auth.screen_access_log "
        "WHERE user_id = %s AND by_email = 'admin@x.com' ORDER BY action, screen",
        (member,),
    )
    assert [(r["screen"], r["action"]) for r in log] == [
        ("investor", "grant"),
        ("qt", "grant"),
        ("member", "revoke"),
    ]

    # Saving the same set again changes and logs nothing.
    _screens_again, granted, revoked = repo.set_screens(member, ("investor", "qt"), "admin@x.com")
    assert granted == () and revoked == ()


def test_set_screens_on_a_missing_user_is_none(db):
    assert screen_repo(db).set_screens(999999, ("member",), "admin@x.com") is None


def test_list_users_carries_screens(db):
    users = {u["email"]: u for u in screen_repo(db).list_users()}
    assert sorted(users["exec@x.com"]["screens"]) == ["member", "qt"]
    assert users["exec@x.com"]["role"] == "exec_board"
    _q(db, "INSERT INTO auth.users (email, role) VALUES ('new@x.com', 'general_member')")
    users = {u["email"]: u for u in screen_repo(db).list_users()}
    assert users["new@x.com"]["screens"] == []


def test_the_access_log_is_append_only_for_the_app(db):
    conn = db()
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("UPDATE auth.screen_access_log SET by_email = 'x'")
        conn.rollback()
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM auth.screen_access_log")
        conn.rollback()
    finally:
        conn.close()


def test_unknown_screens_are_refused_by_the_database(db):
    with pytest.raises(psycopg2.errors.CheckViolation):
        _q(db, "INSERT INTO auth.user_screen_access (user_id, screen, granted_by) VALUES (1, 'admin', 'x')")


# --- investor reports ---------------------------------------------------------


def test_reports_upload_list_unpublish_download(db):
    from algolens.domain.investor.reports import validate_upload

    repo = investor_repo(db)
    row = validate_upload("Q3 letter", "letter", "2026 Q3", "q3.pdf", PDF)
    report = repo.insert_report(row, "exec@x.com")

    assert report["title"] == "Q3 letter" and report["published"] is True
    assert [r["id"] for r in repo.list_reports(published_only=True)] == [report["id"]]
    assert bytes(repo.get_report(report["id"], published_only=True)["content"]) == PDF

    hidden = repo.update_report(report["id"], {"published": False})
    assert hidden["published"] is False
    assert repo.list_reports(published_only=True) == []
    assert repo.get_report(report["id"], published_only=True) is None
    assert repo.get_report(report["id"], published_only=False) is not None
    assert repo.update_report(999999, {"published": True}) is None


def test_reports_cannot_be_deleted_by_the_app(db):
    conn = db()
    try:
        with conn.cursor() as cur:
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                cur.execute("DELETE FROM investor.reports")
        conn.rollback()
    finally:
        conn.close()


def test_reports_size_must_match_the_content(db):
    with pytest.raises(psycopg2.errors.CheckViolation):
        _q(
            db,
            """
            INSERT INTO investor.reports
                (title, kind, filename, content_type, size_bytes, content, sha256, uploaded_by)
            VALUES ('t', 'other', 'f.pdf', 'application/pdf', 5, '\\x00'::bytea, 'x', 'x')
            """,
        )


# --- investor allocation ------------------------------------------------------


def _position(db, book, day, symbol, qty, price, portfolio=QT):
    stamp = datetime(day.year, day.month, day.day, 18, tzinfo=timezone.utc)
    _q(
        db,
        """
        INSERT INTO trading.positions
            (symbol, quantity, average_price, daily_unrealized_pnl, daily_realized_pnl,
             last_update, updated_at, strategy_id, strategy_name, date, portfolio_id, portfolio_type)
        VALUES (%s, %s, %s, 0, 0, %s, %s, 'LIVE_TREND_FOLLOWING', 'TREND_FOLLOWING', %s, %s, %s)
        """,
        (symbol, qty, price, stamp, stamp, day, portfolio, book),
    )


def _metadata(db, day, published, portfolio=QT):
    _q(
        db,
        """
        INSERT INTO trading.live_run_metadata (date, strategy_id, portfolio_id, published_at, published_by)
        VALUES (%s, 'LIVE_TREND_FOLLOWING', %s, %s, %s)
        """,
        (day, portfolio, datetime(2026, 10, 9, 13, 30, tzinfo=timezone.utc) if published else None,
         "desk@x.com" if published else None),
    )


def test_allocation_is_the_qt_book_of_the_latest_published_day(db):
    from algolens.application.investor.use_cases import GetInvestorAllocation
    from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry

    d1, d2 = date(2026, 10, 8), date(2026, 10, 9)
    _q(
        db,
        """
        INSERT INTO metadata.contract_metadata
            ("Databento Symbol", "IB Symbol", "Name", "Exchange", "Asset Type", "Sector", "Contract Size")
        VALUES ('ZC', 'ZC', 'Corn', 'CBOT', 'Futures', 'Agriculture', '50'),
               ('ES', 'ES', 'E-mini S&P', 'CME', 'Futures', 'Equity', '50')
        """,
    )
    _metadata(db, d1, published=True)
    _metadata(db, d2, published=False)  # not yet published: never shown
    _position(db, "qt", d1, "ZC.v.0", 2, 400)
    _position(db, "qt", d1, "ES.v.0", -1, 5000)
    _position(db, "qt", d1, "ZS.v.0", 0, 1000)  # flattened
    _position(db, "system", d1, "ZC.v.0", 9, 400)  # another book
    _position(db, "qt_proposal", d1, "ZC.v.0", 7, 400)
    _position(db, "qt", d2, "ZC.v.0", 5, 400)  # the unpublished day

    portfolios = GetInvestorAllocation(
        PostgresStrategyRegistry(connection_factory=db), investor_repo(db)
    ).execute()

    assert [p["portfolio_id"] for p in portfolios] == [QT]  # desk portfolios only
    book = portfolios[0]
    assert book["as_of"] == "2026-10-08"
    by_symbol = {p["symbol"]: p for p in book["positions"]}
    assert set(by_symbol) == {"ZC.v.0", "ES.v.0"}
    assert by_symbol["ZC.v.0"]["notional"] == pytest.approx(2 * 400 * 50)
    assert by_symbol["ES.v.0"]["notional"] == pytest.approx(-1 * 5000 * 50)
    assert by_symbol["ES.v.0"]["side"] == "short"
    sectors = {a["sector"]: a for a in book["allocation"]}
    assert sectors["Equity"]["weight"] == pytest.approx(250000 / 290000)
    assert sectors["Agriculture"]["weight"] == pytest.approx(40000 / 290000)


def test_allocation_with_nothing_published_is_empty(db):
    from algolens.application.investor.use_cases import GetInvestorAllocation
    from algolens.infrastructure.portfolio.strategy_registry import PostgresStrategyRegistry

    _metadata(db, date(2026, 10, 9), published=False)
    _position(db, "qt", date(2026, 10, 9), "ZC.v.0", 5, 400)

    portfolios = GetInvestorAllocation(
        PostgresStrategyRegistry(connection_factory=db), investor_repo(db)
    ).execute()

    assert portfolios[0]["as_of"] is None
    assert portfolios[0]["positions"] == [] and portfolios[0]["allocation"] == []


def test_role_for_reads_auth_users_now(db):
    repo = screen_repo(db)
    assert repo.role_for(_uid(db, "exec@x.com")) == "exec_board"
    assert repo.role_for(_uid(db, "member@x.com")) == "general_member"
    assert repo.role_for(999999) is None  # no such user: no role, so no access


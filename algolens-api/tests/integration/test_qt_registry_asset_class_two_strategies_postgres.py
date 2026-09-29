"""F1 Postgres proof: a book reaching two registered strategies -- one
declaring EQUITY, one declaring no asset_class at all (NULL) -- must resolve
each strategy's OWN key from its OWN registry row, never book-wide.

Before PLAN14, registry_asset_class(registries) unioned every reachable
trading.strategy_registry row into a single scalar for the whole book, skipping
NULL rows. A NULL strategy's own catalog-silent key therefore silently
inherited whatever single class the *other* declared strategy in the book
declared (it failed OPEN). PLAN14 resolves per key, from the key's own
strategy_type row only.

Fixture shape (PLAN15 rewrite). Every model-seed publication of one book and
day must carry the same strategy_id (qt_provenance.reconcile_qt_source refuses
otherwise with `publication_scope_mismatch`, which empties the proposal's
seed_rows), so a SECOND strategy cannot be given its own seed publication.
The NULL strategy 'engine-null' is therefore added the same way a retired
strategy is in the last test below: a registry row, a book membership, and one
saved 'qt' position (SYN2) and nothing else -- an immutable saved row that
`read_source_evidence` reads with no strategy filter and hands to
`resolve_instrument_types` together with the seed keys. It appears in
`saved_qt_rows`, not in `seed_rows`.

Written per this task's PostgreSQL-integration-lane convention; the
integration lane runs it against an owned database.
"""
import psycopg2
import pytest

from algolens.infrastructure.config.dependencies import create_qt_decision_read_service
from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from tests.integration.test_qt_a3_read_set_postgres import a3_db  # noqa: F401  (fixture)


def _query(dsn, sql, params=()):
    with psycopg2.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall() if cursor.description else None


@pytest.fixture
def two_strategy_db(a3_db):
    """Production-shaped: contract_metadata knows futures ('ES') only. Both
    'SYN' (engine-one's editable seed symbol, from a3_db) and 'SYN2'
    (engine-null's saved symbol, added here) are absent from the catalog, so
    both strategies' resolution depends entirely on the registry fallback.
    a3_db's registry row 'ui-one' is active+live with asset_class NULL until a
    test sets it; the added 'ui-null' row is active+live with NULL too."""
    _query(a3_db, '''CREATE SCHEMA IF NOT EXISTS metadata;
        CREATE TABLE IF NOT EXISTS metadata.contract_metadata (
            "Databento Symbol" text, "IB Symbol" text, "Asset Type" text);
        TRUNCATE metadata.contract_metadata;
        INSERT INTO metadata.contract_metadata VALUES ('ES', 'ES', 'FUTURE');''')
    with psycopg2.connect(a3_db) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO trading.strategy_registry
                    (id, strategy_type, portfolio_id, is_active, lifecycle, updated_at, asset_class)
                VALUES ('ui-null', 'engine-null', 'BOOK', true, 'live', now(), NULL);
                INSERT INTO trading.strategy_book_memberships VALUES ('ui-null', 'BOOK');
            """)
            cursor.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")
            day = cursor.fetchone()[0]
            # a3_db creates trading.positions with 9 columns (portfolio_id ..
            # qt_proposal_revision): a 9-value row, like a3_db's own seed rows.
            # Only a saved 'qt' row: no system/qt_proposal row and no seed
            # publication (a second strategy's publication would be a
            # publication_scope_mismatch for the whole book and day).
            cursor.execute("""
                INSERT INTO trading.positions VALUES
                  ('BOOK','engine-null','NULLSTRAT',%(day)s,'SYN2','qt',6,50,NULL)
            """, {"day": day})
    return a3_db


def _reader(dsn):
    return create_qt_decision_read_service(connection_factory=lambda: psycopg2.connect(dsn))


def test_the_declared_strategys_own_key_resolves_from_its_own_row(two_strategy_db):
    # engine-one declares EQUITY, engine-null (whose saved SYN2 row is in the
    # same batch of keys get_proposal resolves) declares nothing. The catalog
    # is silent for both, so the NULL strategy's own key has no fallback and
    # the batch refuses -- a NULL sibling gets no class, even though the
    # declared sibling in the same book has one.
    _query(two_strategy_db, "UPDATE trading.strategy_registry SET asset_class = 'EQUITY' WHERE id = 'ui-one'")
    with pytest.raises(QtWorkflowError) as blocked:
        _reader(two_strategy_db).get_proposal("BOOK", 101)
    assert blocked.value.code == "draft_identity_unresolved"


def test_the_null_siblings_own_key_does_not_inherit_the_declared_class(two_strategy_db):
    """The key of the NULL strategy must not take engine-one's class. Three
    steps over the same book:

    1. both strategies declare EQUITY -> both keys resolve EQUITY (the
       fixture itself is sound: SYN is a seed row, SYN2 a saved row);
    2. only engine-null goes back to NULL while engine-one still declares
       EQUITY -> the proposal refuses. A book-wide resolver (the pre-PLAN14
       union that skipped NULL rows) resolves SYN2 to EQUITY here and does
       NOT raise, so this step fails on it;
    3. engine-null declares FUTURE while engine-one declares EQUITY -> each
       key gets its OWN row's class (SYN EQUITY, SYN2 FUTURE). A book-wide
       resolver sees two distinct classes and refuses, so this step also
       fails on it.
    """
    dsn = two_strategy_db
    _query(dsn, "UPDATE trading.strategy_registry SET asset_class = 'EQUITY' WHERE id IN ('ui-one', 'ui-null')")
    both_declared = _reader(dsn).get_proposal("BOOK", 101).to_wire()
    syn = next(row for row in both_declared["seed_rows"] if row["key"]["symbol"] == "SYN")
    syn2 = next(row for row in both_declared["saved_qt_rows"] if row["key"]["symbol"] == "SYN2")
    assert syn["asset_type"] == "EQUITY"
    assert syn2["asset_type"] == "EQUITY" and syn2["editable"] is False

    _query(dsn, "UPDATE trading.strategy_registry SET asset_class = NULL WHERE id = 'ui-null'")
    with pytest.raises(QtWorkflowError) as blocked:
        _reader(dsn).get_proposal("BOOK", 101)
    assert blocked.value.code == "draft_identity_unresolved"

    _query(dsn, "UPDATE trading.strategy_registry SET asset_class = 'FUTURE' WHERE id = 'ui-null'")
    own_classes = _reader(dsn).get_proposal("BOOK", 101).to_wire()
    syn = next(row for row in own_classes["seed_rows"] if row["key"]["symbol"] == "SYN")
    syn2 = next(row for row in own_classes["saved_qt_rows"] if row["key"]["symbol"] == "SYN2")
    assert syn["asset_type"] == "EQUITY"
    assert syn2["asset_type"] == "FUTURE"


# --- revision 3: a single retired (or incubating) owner resolves ------------
#
# Revision 2 required exactly one ACTIVE+LIVE row per strategy_type, which
# refused a single retired or incubating owner -- a shape the codebase
# explicitly supports (migration 002's real lifecycle values;
# `_validate_catalog`, qt_workflow.py:324-326, requires active+live only for an
# EDITABLE row, not for the type gate itself). PLAN14 matches
# `_validate_catalog`'s rule: exactly one REACHABLE row of any status.

@pytest.fixture
def live_and_retired_db(a3_db):
    """The independent review's own regression shape: LIVE ('ui-one'/
    'engine-one', active+live, set to EQUITY) alongside OLD ('ui-old'/
    'engine-old', a SINGLE retired row, EQUITY). Both strategies' own
    symbols (SYN and SYN3 respectively) are absent from the catalog, so
    both depend entirely on the registry fallback. Both must resolve.

    OLD gets ONLY a saved 'qt' row -- deliberately no 'system'/'qt_proposal'
    seed and no qt_model_seed_publications entry, so its row is genuinely
    IMMUTABLE (never part of `seeds`, so `_preview_access`'s active+live
    ownership check, which applies only to editable rows, never runs
    against it) -- exactly the shape independent review 1 names: "a single
    retired or incubating owner" whose rows are immutable, read by
    `read_source_evidence` without any strategy filter, reaching
    `resolve_instrument_types` on their own."""
    _query(a3_db, '''CREATE SCHEMA IF NOT EXISTS metadata;
        CREATE TABLE IF NOT EXISTS metadata.contract_metadata (
            "Databento Symbol" text, "IB Symbol" text, "Asset Type" text);
        TRUNCATE metadata.contract_metadata;
        INSERT INTO metadata.contract_metadata VALUES ('ES', 'ES', 'FUTURE');''')
    with psycopg2.connect(a3_db) as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO trading.strategy_registry
                    (id, strategy_type, portfolio_id, is_active, lifecycle, updated_at, asset_class)
                VALUES ('ui-old', 'engine-old', 'BOOK', false, 'retired', now(), 'EQUITY');
                INSERT INTO trading.strategy_book_memberships VALUES ('ui-old', 'BOOK');
                UPDATE trading.strategy_registry SET asset_class = 'EQUITY' WHERE id = 'ui-one';
            """)
            cursor.execute("SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")
            day = cursor.fetchone()[0]
            # a3_db creates trading.positions with 9 columns (portfolio_id
            # ... qt_proposal_revision) -- no pnl or last_update columns;
            # only preview_db's own fixture adds those. Match a3_db's own
            # seed row shape exactly (9 values).
            cursor.execute("""
                INSERT INTO trading.positions VALUES
                  ('BOOK','engine-old','OLDSTRAT',%(day)s,'SYN3','qt',9,75,NULL)
            """, {"day": day})
    return a3_db


def test_a_single_retired_owner_resolves_alongside_an_active_live_owner(live_and_retired_db):
    service = create_qt_decision_read_service(connection_factory=lambda: psycopg2.connect(live_and_retired_db))
    proposal = service.get_proposal("BOOK", 101).to_wire()
    # engine-one's own SYN key (active+live owner) -- an editable seed row.
    syn = next(row for row in proposal["seed_rows"] if row["key"]["symbol"] == "SYN")
    assert syn["asset_type"] == "EQUITY"
    # engine-old's own SYN3 key (single retired owner) -- immutable saved
    # row. Under revision 2 this raised draft_identity_unresolved for the
    # WHOLE proposal (resolve_instrument_types resolves the entire batch of
    # seed + saved keys in one call and raises on the first unresolved
    # key), taking engine-one's own SYN down with it.
    syn3 = next(row for row in proposal["saved_qt_rows"] if row["key"]["symbol"] == "SYN3")
    assert syn3["asset_type"] == "EQUITY" and syn3["editable"] is False

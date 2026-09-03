"""The schema contract, and the two failures it exists to catch.

These run without a database: `check_schema` only needs something that answers
the information_schema query, so the shape of a hypothetical database is given
directly. The point is to guard the checker itself -- a checker that silently
stops catching things is worse than none, because it reads as reassurance.
"""

from algolens.infrastructure.db.schema_contract import (
    CONTRACTS,
    TableContract,
    check_schema,
    format_findings,
)


class _Cursor:
    """Answers the one information_schema query check_schema issues."""

    def __init__(self, tables):
        # {(schema, table): {column: (is_nullable, default)}}
        self.tables = tables
        self._rows = []

    def execute(self, _sql, params):
        schema, table = params
        self._rows = [
            (name, nullable, default)
            for name, (nullable, default) in self.tables.get((schema, table), {}).items()
        ]

    def fetchall(self):
        return self._rows


def _table(columns):
    """Every column nullable unless stated, which is the permissive case."""
    return {name: ("YES", None) for name in columns}


READS_AND_WRITES = TableContract(
    name="trading.thing",
    source="this test",
    reads=("a", "b"),
    writes=("a", "b"),
    inserts_rows=True,
)


def test_a_database_that_satisfies_the_contract_reports_nothing():
    cursor = _Cursor({("trading", "thing"): _table(["a", "b"])})
    assert check_schema(cursor, [READS_AND_WRITES]) == []


def test_a_column_the_application_reads_but_the_database_lacks_is_reported():
    cursor = _Cursor({("trading", "thing"): _table(["a"])})
    findings = check_schema(cursor, [READS_AND_WRITES])
    assert [f["kind"] for f in findings] == ["missing_column"]
    assert findings[0]["column"] == "b"


def test_a_required_column_the_application_never_supplies_is_reported():
    # The exact shape of the bug this file exists for: the database insists on a
    # value, has no default to fall back on, and the INSERT does not mention it.
    cursor = _Cursor({
        ("trading", "thing"): {
            "a": ("YES", None), "b": ("YES", None),
            "last_update": ("NO", None),
        }
    })
    findings = check_schema(cursor, [READS_AND_WRITES])
    assert [f["kind"] for f in findings] == ["unsupplied_not_null"]
    assert findings[0]["column"] == "last_update"


def test_a_required_column_with_a_default_is_not_reported():
    # The database fills this one in itself, so omitting it is safe.
    cursor = _Cursor({
        ("trading", "thing"): {
            "a": ("YES", None), "b": ("YES", None),
            "created_at": ("NO", "now()"),
        }
    })
    assert check_schema(cursor, [READS_AND_WRITES]) == []


def test_tables_the_application_only_updates_are_not_checked_for_insert_columns():
    # AlgoLens never creates strategy_registry rows. A NOT NULL column there is
    # whoever-writes-it's business, and reporting it would be noise.
    update_only = TableContract(
        name="trading.thing", source="this test", reads=("a",), writes=("a",)
    )
    cursor = _Cursor({
        ("trading", "thing"): {"a": ("YES", None), "id": ("NO", None)}
    })
    assert check_schema(cursor, [update_only]) == []


def test_a_missing_table_is_reported_once_not_once_per_column():
    cursor = _Cursor({})
    findings = check_schema(cursor, [READS_AND_WRITES])
    assert [f["kind"] for f in findings] == ["missing_table"]


def test_the_report_names_the_table_and_column():
    cursor = _Cursor({("trading", "thing"): _table(["a"])})
    text = format_findings(check_schema(cursor, [READS_AND_WRITES]))
    assert "trading.thing.b" in text
    assert "1 schema mismatch" in text


def test_the_clean_report_does_not_read_as_a_warning():
    assert "satisfied" in format_findings([])


def test_every_declared_contract_cites_where_its_shape_came_from():
    # A contract with no provenance is another guess wearing a uniform.
    for contract in CONTRACTS:
        assert contract.source.strip(), contract.name
        assert contract.reads or contract.writes, contract.name


def test_the_registry_contract_still_admits_it_is_unverified():
    # If someone confirms this table against a real database, they should have
    # to come here and say so deliberately.
    registry = next(c for c in CONTRACTS if c.name == "trading.strategy_registry")
    assert "UNVERIFIED" in registry.source

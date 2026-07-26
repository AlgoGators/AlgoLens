"""Structural guards on the position write path.

Two invariants matter more than any single behaviour here, and both are the kind
that a future edit breaks silently:

  1. Every INSERT/UPDATE against trading.positions is accompanied by an insert
     into trading.position_overrides in the SAME function -- so a position can
     never change without an audit row.
  2. No write ever names a stream other than 'qt'.

Neither can be checked by running the code without a database, so they are
checked by reading it. Companion to test_stream_scoping.py.
"""

import ast
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRITER = os.path.join(BACKEND_DIR, "services", "position_writer.py")


def _source():
    with open(WRITER, encoding="utf-8") as fh:
        return fh.read()


def _string_constants(tree):
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


def test_the_writer_module_exists():
    """Guard the guard: a scan that finds nothing must not silently pass."""
    assert os.path.exists(WRITER), "position_writer.py is missing"


def test_every_position_write_function_also_writes_the_audit_row():
    tree = ast.parse(_source())

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        sql = " ".join(_string_constants(node)).lower()
        touches_positions = (
            "into trading.positions" in sql or "update trading.positions" in sql
        )
        writes_audit = "trading.position_overrides" in sql
        if touches_positions and not writes_audit:
            offenders.append(f"{node.name} (line {node.lineno})")

    assert not offenders, (
        "These functions write trading.positions without writing an audit row "
        "in the same function: " + ", ".join(offenders) + ". A position that "
        "changes without an audit row is exactly what F2 exists to prevent."
    )


def test_no_write_names_a_stream_other_than_qt():
    sql = " ".join(_string_constants(ast.parse(_source()))).lower()
    for forbidden in ("'system'", "'benchmark'"):
        assert forbidden not in sql, (
            f"The writer references {forbidden}. Only the qt stream is writable; "
            "system and benchmark are the baseline QT is measured against."
        )


def test_no_sql_is_built_by_string_formatting():
    """trade-ngin#42 exists because this was violated once already."""
    tree = ast.parse(_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):  # f-string
            for value in ast.walk(node):
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    lowered = value.value.lower()
                    assert not any(
                        kw in lowered
                        for kw in ("select ", "insert ", "update ", "delete ")
                    ), (
                        f"SQL built with an f-string at line {node.lineno}. "
                        "Use parameterized queries."
                    )

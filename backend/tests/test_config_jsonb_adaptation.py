"""Regression guard: JSONB parameters must be serialized before they reach psycopg2.

`trading.strategy_config.overrides` is a JSONB column, and the natural thing to
write is:

    cursor.execute(INSERT ..., (portfolio_id, version, overrides, ...))

That fails at runtime with `ProgrammingError: can't adapt type 'dict'` -- psycopg2
has no adapter for a plain dict. It must be `json.dumps(overrides)`.

This shipped broken once. Every unit test in this suite is pure-function or
AST-based and none of them reach the database driver, so the whole config write
path returned HTTP 500 while the suite stayed green. The bug was only visible by
issuing a real request against a real database.

Rather than add a database-dependent test (which would fail in CI, where there is
no database), this asserts the structural property that makes the bug impossible:
any function writing to a JSONB column serializes first. Companion to
test_stream_scoping.py and test_write_path_guards.py, which guard other invariants
the same way.
"""

import ast
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVICE = os.path.join(BACKEND_DIR, "services", "config_service.py")

# Columns declared JSONB in migration 006. A dict bound to any of these without
# json.dumps() raises at execute time.
JSONB_COLUMNS = ("overrides",)


def _source():
    with open(SERVICE, encoding="utf-8") as fh:
        return fh.read()


def _functions_writing_jsonb(tree):
    """Functions containing an INSERT/UPDATE naming a JSONB column."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        sql = " ".join(
            n.value.lower()
            for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
        )
        writes = "insert into trading.strategy_config" in sql or (
            "update trading.strategy_config" in sql and "set overrides" in sql
        )
        if writes and any(col in sql for col in JSONB_COLUMNS):
            found.append(node)
    return found


def test_the_service_module_exists():
    """Guard the guard: a scan that finds nothing must not silently pass."""
    assert os.path.exists(SERVICE), "config_service.py is missing"


def test_there_are_jsonb_writers_to_check():
    """If this fires, the writers were renamed and the scan below is now vacuous."""
    writers = _functions_writing_jsonb(ast.parse(_source()))
    assert writers, (
        "No function writing a JSONB column was found in config_service.py. "
        "Either the write path moved or this scan is broken -- do not treat "
        "this as a pass."
    )


def test_every_jsonb_write_serializes_with_json_dumps():
    tree = ast.parse(_source())

    offenders = []
    for fn in _functions_writing_jsonb(tree):
        calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "dumps"
        ]
        if not calls:
            offenders.append(f"{fn.name} (line {fn.lineno})")

    assert not offenders, (
        "These functions write a JSONB column without calling json.dumps: "
        + ", ".join(offenders)
        + ". psycopg2 cannot adapt a dict and will raise "
        "\"can't adapt type 'dict'\" at execute time -- which no pure-function "
        "test in this suite would catch."
    )

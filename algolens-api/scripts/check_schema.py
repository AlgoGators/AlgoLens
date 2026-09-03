#!/usr/bin/env python
"""Check a database against what AlgoLens actually needs of it.

    python scripts/check_schema.py "postgresql://user@host:5432/dbname"

or, with no argument, the usual DB_* environment variables.

Point it at a restored snapshot of the real database. It answers the question
that no test in this repository could answer on its own: does the schema this
application was built against resemble the one it will meet?

Exit status is 0 when the contract is satisfied and 1 when it is not, so this
can gate a deployment.

It only ever runs SELECTs against information_schema. It reads no data, and
changes nothing.
"""

import os
import sys

import psycopg2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from algolens.infrastructure.db.schema_contract import (  # noqa: E402
    CONTRACTS,
    check_schema,
    format_findings,
)


def _dsn_from_argv_or_env():
    if len(sys.argv) > 1:
        return sys.argv[1]
    missing = [v for v in ("DB_HOST", "DB_NAME", "DB_USER") if not os.getenv(v)]
    if missing:
        raise SystemExit(
            "Pass a connection string, or set DB_HOST, DB_PORT, DB_NAME, "
            "DB_USER and DB_PASSWORD. Missing: " + ", ".join(missing)
        )
    password = os.getenv("DB_PASSWORD", "")
    return (
        f"postgresql://{os.getenv('DB_USER')}:{password}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME')}"
    )


def main():
    dsn = _dsn_from_argv_or_env()
    # Never print the DSN: it carries a password.
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cursor:
            findings = check_schema(cursor)
    finally:
        conn.close()

    print(format_findings(findings))
    print()
    print("Where each expectation comes from:")
    for contract in CONTRACTS:
        print(f"  {contract.name}: {contract.source}")
        for note in contract.notes:
            print(f"      note: {note}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())

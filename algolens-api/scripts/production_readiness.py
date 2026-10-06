#!/usr/bin/env python3
"""Run the secret-free, read-only production readiness boundary."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algolens.infrastructure.config.production_readiness import (  # noqa: E402
    evaluate_readiness,
    evaluate_runtime_readiness,
    load_runtime_contract,
)
from algolens.infrastructure.config.app_factory import create_app  # noqa: E402
from algolens.infrastructure.db.postgres import get_db_connection  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', action='store_true',
                        help='print the secret-free evidence object after every gate passes')
    parser.add_argument(
        '--rehearsal-root',
        type=Path,
        help=(
            'explicit private /dev/shm/algolens-qt-rehearsal.* root; '
            'requires qt_rehearsal_migrated over its Unix socket'
        ),
    )
    options = parser.parse_args(argv)
    contract = load_runtime_contract(
        context='rehearsal' if options.rehearsal_root is not None else 'production',
        rehearsal_root=options.rehearsal_root,
    )
    preflight = evaluate_readiness(contract)
    if any('_contract_' in code for code in preflight.failure_codes):
        result = preflight
    else:
        application = (create_app(rehearsal_root=options.rehearsal_root)
                       if options.rehearsal_root is not None else create_app())
        result = evaluate_runtime_readiness(
            contract,
            application=application,
            connection_factory=get_db_connection,
        )
    payload = result.evidence_payload() if options.evidence and result.ready else result.public_payload()
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

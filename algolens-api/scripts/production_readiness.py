#!/usr/bin/env python3
"""Run the secret-free, read-only production readiness boundary."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from algolens.infrastructure.config.production_readiness import (  # noqa: E402
    evaluator_isolation_probe,
    evaluate_readiness,
    load_runtime_contract,
    runtime_configuration_file_probe,
)
from algolens.infrastructure.db.postgres import get_db_connection  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', action='store_true',
                        help='print the secret-free evidence object after every gate passes')
    options = parser.parse_args(argv)
    contract = load_runtime_contract()
    # T3 supplies the schema and role probes; T1/T4 supply their dependency
    # probes at integration. Their absence is an intentional hard refusal.
    result = evaluate_readiness(
        contract,
        connection_factory=get_db_connection,
        runtime_configuration_probe=runtime_configuration_file_probe,
        evaluator_probe=evaluator_isolation_probe,
    )
    payload = result.evidence_payload() if options.evidence and result.ready else result.public_payload()
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if result.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

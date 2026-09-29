"""Actual legacy receipt reporting must not require the optional v2 producer table."""
from copy import deepcopy
import json

import pytest

from tests.integration.test_qt_a3_read_set_postgres import a3_db
from tests.integration.test_qt_preview_evaluator import preview_db
from tests.integration.test_qt_connected_workflow import (
    assert_positions_rows_match_saved, connected_db, desk, observe, prepare, query, report,
)


def immutable_rows(dsn):
    result = {}
    for relation in ("positions", "qt_decisions", "qt_previews", "qt_desk_receipts",
                     "qt_desk_results", "qt_execution_observations", "position_overrides"):
        result[relation] = query(dsn, "SELECT to_jsonb(r) FROM trading." + relation +
                                 " r ORDER BY to_jsonb(r)::text")
    return deepcopy(result)


@pytest.mark.parametrize("optional_producer_table", [False, True])
def test_real_v1_receipt_report_preserves_optional_v2_boundary(
        connected_db, tmp_path, monkeypatch, optional_producer_table):
    assert query(connected_db, "SELECT to_regclass('trading.desk_run_results')") == [(None,)]
    http, preview, decision = prepare(connected_db, "7", monkeypatch)
    observe(connected_db, preview, decision, "7")
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    assert query(connected_db, "SELECT payload->>'schema_version' FROM "
                 "trading.qt_execution_observations WHERE observation_id="
                 "'60000000-0000-4000-8000-000000000051'") == [("qt-execution/v1",)]
    ready = http["browser"].get("/portfolio/qt-decisions/" + decision["decision_id"])
    assert ready.status_code == 200 and ready.json["report_ready"] is True, ready.json
    if optional_producer_table:
        # An unclaimed empty relation does not turn an external v1 observation
        # into an accounting-producer result or an empty-owner publication.
        query(connected_db, "CREATE TABLE trading.desk_run_results "
                            "(decision_id uuid, payload jsonb)")
    before = immutable_rows(connected_db)
    rendered = report(preview, tmp_path / "qt-report-legacy-v1")
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    output = json.loads(rendered.stdout)
    assert output["delivery_guard_loaded"] is True and output["delivery_calls"] == 0
    assert output["quantities"] == {"ONE": {"SYN": "7"}}
    # Same saved SYN row as test_qt_connected_workflow.py: average_price 101,
    # equity multiplier 1, probe market price 102.
    assert_positions_rows_match_saved(output["report_html"], output["report_csv"],
        output["baseline_html"], output["baseline_csv"], [("One", "SYN", "7", "101", "1", "102")])
    assert immutable_rows(connected_db) == before
    query(connected_db, "UPDATE trading.positions SET daily_realized_pnl=9 "
                        "WHERE portfolio_type='qt'")
    refused = report(preview, tmp_path / "qt-report-legacy-v1-stale")
    assert refused.returncode == 12 and refused.stdout == "REPORT_BLOCKED=1\n"

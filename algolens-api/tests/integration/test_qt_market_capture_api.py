"""Actual SQL market reader through native accounting and API report proof.

Bars and historical starting records are explicitly synthetic. All current
capture, finalization, sourced processing and API reads use real components.
"""
from copy import deepcopy
from pathlib import Path
import json
import sys

import pytest
import tests

from tests.qt_native_artifacts import require_native_artifact_paths

ENGINE_SOURCE = require_native_artifact_paths(allow_module_level=True).source_dir
ENGINE_TESTS = ENGINE_SOURCE / 'tests/integration'
tests.__path__ = [*tests.__path__, str(ENGINE_SOURCE / 'tests')]
sys.path.insert(0, str(ENGINE_TESTS))
from test_qt_desk_market_capture import capture
from test_qt_desk_upstream import upstream, invoke, OLD, MARKET, FINAL, DECISION, ATTEMPT
from test_qt_desk_accounting import accounting
from test_qt_desk_storage import desk
from tests.integration.qt_native_schema import connection
from tests.integration.test_qt_upstream_accounting import evidence, current_read_evidence
from algolens.infrastructure.portfolio.qt_finalization_proof import verified_market_source
from algolens.infrastructure.portfolio.qt_decision_report_proof import processed_report_blocked_reasons
from algolens.infrastructure.portfolio.qt_receipt_provenance import verified_receipt_chain
from psycopg2.extras import RealDictCursor

pytestmark = [pytest.mark.parametrize('desk', ['futures_mes'], indirect=True),
              pytest.mark.parametrize('accounting', ['no_input'], indirect=True)]


@pytest.mark.parametrize('host_timezone', ['UTC', 'America/New_York', 'Asia/Tokyo'])
def test_actual_market_capture_accounting_and_api_quantity_proof(capture, monkeypatch, host_timezone):
    monkeypatch.setenv('TZ', host_timezone)
    conn, request = capture
    result = invoke('--capture', payload=request)
    assert result.returncode == 0, result.stdout + result.stderr
    market = json.loads(result.stdout)
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('SELECT * FROM trading.qt_model_seed_publications WHERE publication_id=%s',
                       (market['model_publication_id'],))
        model = dict(cursor.fetchone())
    admitted = verified_market_source({'market_row': market, 'model_publication': model},
                                     market['book_id'], market['source_day'])
    assert admitted['capture']['rows'][0]['source_time'].endswith('T16:30:00Z')
    assert admitted['instruments'][0]['price_model_number'] == '102'
    result = invoke('--finalize', OLD, FINAL, MARKET)
    assert result.returncode == 0, result.stdout + result.stderr
    input_id = 'd0000000-0000-4000-8000-000000000019'
    result = invoke('--sourced', DECISION, ATTEMPT, input_id, MARKET, 'qt-finalization/' + FINAL)
    assert result.returncode == 0, result.stdout + result.stderr
    decision, loaded = evidence(conn, DECISION, input_id)
    with conn.cursor(cursor_factory=RealDictCursor) as cursor:
        cursor.execute('SELECT * FROM trading.qt_desk_receipts WHERE decision_id=%s', (DECISION,))
        receipt = dict(cursor.fetchone())
        cursor.execute('SELECT * FROM trading.qt_previews WHERE preview_id=%s', (decision['preview_id'],))
        preview = dict(cursor.fetchone())
    original_receipt = deepcopy(receipt)
    current = current_read_evidence(conn, decision, preview, receipt)
    assert processed_report_blocked_reasons(current) == ()
    origin = verified_receipt_chain(decision['book_id'], decision['source_day'], [current],
                                   current['audits'], current['current_facts']['saved_accounting'])
    assert origin is not None and origin['choices']
    chosen = {row['key']['symbol']: row['quantity_exact'] for row in preview['payload']['selection_rows']}
    assert {row['key']['symbol']: row['selected_quantity_exact']
            for row in loaded['payload']['observation']['fills']} == chosen
    assert receipt == original_receipt
    with conn.cursor() as cursor:
        cursor.execute("UPDATE trading.equity_curve SET equity=equity+1 WHERE portfolio_type='qt' AND timestamp=%s",
                       (str(decision['source_day']) + 'T00:00:00Z',))
    invalid = current_read_evidence(conn, decision, preview, receipt)
    assert processed_report_blocked_reasons(invalid)

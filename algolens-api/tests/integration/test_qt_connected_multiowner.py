"""Owned HTTP -> native desk -> report gates for full component ownership.

No server or delivery method is invoked. Native rendering requires the same
preloaded no-delivery sentinel as the root connected harness.
"""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
import subprocess
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

from algolens.infrastructure.config.dependencies import create_qt_workflow_service
from algolens.domain.portfolio.qt_canonical import qt_digest_v1
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_read_set import internal_snapshot_digest
from algolens.infrastructure.portfolio.qt_workflow_repository import QtWorkflowRepository
from tests.integration.test_qt_a3_read_set_postgres import a3_db, PUBLICATION, REVISION
from tests.integration.test_qt_a8_http_postgres import http_harness
from tests.integration.test_qt_preview_evaluator import preview_db, authority, query
from tests.integration.test_qt_connected_workflow import (
    assert_positions_rows_match_saved, connected_db, desk, REPORT, DELIVERY_GUARD, OBSERVATION,
)
from tests.qt_native_evaluator import native_evaluator_configuration


SECOND_PUBLICATION = "10000000-0000-4000-8000-000000000071"
SECOND_REVISION = "30000000-0000-4000-8000-000000000071"
KEY_FIELDS = ("portfolio_id", "strategy_id", "strategy_name", "date", "symbol", "portfolio_type")


def identity(key):
    return tuple(key[field] for field in KEY_FIELDS)


class CurrentQuantitySpans(HTMLParser):
    """Bind raw text spans to Today's Positions / owner / symbol only."""
    def __init__(self, document):
        super().__init__(convert_charrefs=False)
        self.document = document
        self.lines = [0]
        self.lines.extend(index + 1 for index, char in enumerate(document) if char == "\n")
        self.section = None
        self.owner = None
        self.heading = None
        self.headers = []
        self.header = None
        self.in_current_table = False
        self.cell = None
        self.cells = []
        self.spans = {}
        self.feed(document)
        self.close()

    def absolute_offset(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag, attrs):
        if tag in {"h2", "h3"}:
            self.heading = (tag, [])
        if tag == "tr":
            self.cells = []
        if tag == "table" and self.section == "Today's Positions":
            assert self.owner and not self.in_current_table
            self.in_current_table = True
            self.headers = []
        if tag == "th" and self.section == "Today's Positions":
            self.header = []
        if tag == "td":
            self.cell = self.absolute_offset() + len(self.get_starttag_text())

    def handle_data(self, data):
        if self.heading:
            self.heading[1].append(data)
        if self.header is not None:
            self.header.append(data)

    def handle_endtag(self, tag):
        if self.heading and tag == self.heading[0]:
            name = "".join(self.heading[1]).strip()
            if tag == "h2":
                self.section, self.owner = name, None
            elif self.section == "Today's Positions":
                self.owner = name
            self.heading = None
        if tag == "td" and self.cell is not None:
            self.cells.append((self.cell, self.absolute_offset(), self.document[self.cell:self.absolute_offset()]))
            self.cell = None
        if tag == "th" and self.header is not None:
            self.headers.append("".join(self.header))
            self.header = None
        if tag == "table" and self.section == "Today's Positions":
            assert self.in_current_table
            self.in_current_table = False
        if tag == "tr" and self.section == "Today's Positions" and self.cells:
            assert self.in_current_table and self.owner and len(self.cells) == 5
            assert self.headers == ['Symbol', 'Quantity', 'Market Price', 'Notional', '% of Total']
            symbol = self.cells[0][2]
            assert (self.owner, symbol) not in self.spans
            self.spans[(self.owner, symbol)] = self.cells[1]


def assert_html_quantities_only(before, after, old, selected):
    baseline = CurrentQuantitySpans(before).spans
    projected = CurrentQuantitySpans(after).spans
    assert set(baseline) == set(projected) == set(old) == set(selected)
    expected = before
    for key, (start, end, text) in sorted(baseline.items(), key=lambda item: item[1][0], reverse=True):
        assert text == old[key]
        assert projected[key][2] == selected[key]
        expected = expected[:start] + selected[key] + expected[end:]
    assert after == expected


def sample_html(rows, *, yesterday="4.00"):
    tables = []
    for owner, symbol, quantity in rows:
        tables.append("<h3>" + owner + "</h3><table><tr><th>Symbol</th><th>Quantity</th>"
                      "<th>Market Price</th><th>Notional</th><th>% of Total</th></tr><tr>"
                      "<td>" + symbol + "</td><td>" + quantity + "</td><td>$102</td>"
                      "<td>$400</td><td>50%</td></tr></table>")
    return "<h2>Today's Positions</h2>" + "".join(tables) + (
        "<h2>Yesterday's Finalized Position Results</h2><h3>One</h3><table><tr>"
        "<td>SYN</td><td>" + yesterday + "</td><td>100</td><td>101</td><td>-1</td></tr></table>")


def test_semantic_spans_bind_owner_and_section_and_keep_other_bytes():
    old = {("One", "SYN"): "4", ("Two", "SYN"): "2"}
    selected = {("One", "SYN"): "5", ("Two", "SYN"): "1"}
    before = sample_html([(owner, symbol, quantity) for (owner, symbol), quantity in old.items()])
    after = sample_html([(owner, symbol, quantity) for (owner, symbol), quantity in selected.items()])
    assert_html_quantities_only(before, after, old, selected)
    with pytest.raises(AssertionError):
        assert_html_quantities_only(before, sample_html([("One", "SYN", "1"), ("Two", "SYN", "5")]), old, selected)
    with pytest.raises(AssertionError):
        assert_html_quantities_only(before, after.replace("4.00", "5.00"), old, selected)
    with pytest.raises(AssertionError):
        assert_html_quantities_only(before, after.replace("$400", "$500", 1), old, selected)
    with pytest.raises(AssertionError):
        CurrentQuantitySpans(before.replace('<th>Quantity</th>', '<th>Market Price</th>', 1))


def test_semantic_spans_reject_duplicate_current_owner_symbol():
    before = sample_html([("One", "SYN", "4"), ("One", "SYN", "4")])
    with pytest.raises(AssertionError):
        CurrentQuantitySpans(before)


def test_semantic_spans_reject_position_row_outside_current_owner_table():
    before = sample_html([('One', 'SYN', '4')])
    malformed = before.replace('</table>', '</table><h3>Ghost</h3><tr><td>FUT</td><td>7</td>'
                               '<td>$102</td><td>$400</td><td>50%</td></tr>', 1)
    with pytest.raises(AssertionError):
        CurrentQuantitySpans(malformed)


@pytest.fixture
def multiowner_db(connected_db):
    dsn = connected_db
    day = query(dsn, "SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")[0][0].isoformat()
    # A later immutable publication preserves ONE's original proof and inserts
    # TWO; no historical publication, proposal token or seed is rewritten.
    query(dsn, """UPDATE trading.positions SET quantity=4 WHERE portfolio_type='qt';
        INSERT INTO metadata.contract_metadata VALUES ('IMM','IMM','EQUITY');
        INSERT INTO trading.positions
          (portfolio_id,strategy_id,strategy_name,date,symbol,portfolio_type,quantity,average_price,
           qt_proposal_revision,daily_unrealized_pnl,daily_realized_pnl,last_update)
        VALUES ('BOOK','engine-one','TWO',%s,'SYN','system',2,100,NULL,NULL,NULL,NULL),
               ('BOOK','engine-one','TWO',%s,'SYN','qt_proposal',2,100,%s,NULL,NULL,NULL),
               ('BOOK','engine-one','TWO',%s,'SYN','qt',2,100,NULL,2.25,-0.75,clock_timestamp()),
               ('BOOK','engine-one','HELD',%s,'IMM','qt',8,25,NULL,1.25,-0.5,clock_timestamp());""",
          (day, day, SECOND_REVISION, day, day))
    seed, manifest = [], []
    for owner, quantity, revision, origin, action in (
        ("ONE", "4", REVISION, PUBLICATION, "preserved"),
        ("TWO", "2", SECOND_REVISION, SECOND_PUBLICATION, "inserted"),
    ):
        key = dict(zip(KEY_FIELDS, ("BOOK", "engine-one", owner, day, "SYN", "system")))
        seed.append({"key": key, "quantity_exact": quantity, "average_price_exact": "100"})
        manifest.append({"key": {**key, "portfolio_type": "qt_proposal"}, "quantity_exact": quantity,
                         "average_price_exact": "100", "action": action, "position_revision": revision,
                         "origin_publication_id": origin})
    query(dsn, """INSERT INTO trading.qt_model_seed_publications
        (publication_id,portfolio_id,strategy_id,source_day,publication_version,system_components,
         seed_digest,producer_version,proposal_components,proposal_manifest_digest)
        VALUES(%s,'BOOK','engine-one',%s,2,%s,%s,'synthetic-connected-multiowner',%s,%s)""",
        (SECOND_PUBLICATION, day, Json(seed), qt_digest_v1({"seed_rows": seed}), Json(manifest),
         internal_snapshot_digest("qt-proposal-manifest/v1", {"proposal_rows": manifest})))
    return dsn


def saved_components(dsn):
    rows = query(dsn, """SELECT portfolio_id,strategy_id,strategy_name,date::text,symbol,portfolio_type,
        quantity,average_price,daily_unrealized_pnl,daily_realized_pnl,last_update
        FROM trading.positions WHERE portfolio_type='qt' ORDER BY portfolio_id,strategy_id,strategy_name,date,symbol""")
    return {tuple(row[:6]): tuple(row[6:]) for row in rows}


def prepare_multiowner(dsn, monkeypatch, quantities):
    config = native_evaluator_configuration()
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(dsn)),
                                evaluator_bundle_directory=config["bundle_directory"])
    _, clients, _ = http_harness(dsn, service, monkeypatch)
    browser, headers = clients(101)
    initial_response = browser.get('/portfolio/qt-books/BOOK/draft')
    assert initial_response.status_code == 200, initial_response.json
    initial = initial_response.json
    assert len(initial['selection_rows']) == 3
    assert {row['key']['strategy_name']: (row['quantity_exact'], row['editable'], row['origin'])
            for row in initial['selection_rows']} == {
                'ONE': ('4', True, 'verified_model_seed'), 'TWO': ('2', True, 'verified_model_seed'),
                'HELD': ('8', False, 'immutable')}
    response = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json={
        'expected_source_digest': initial['source_digest'], 'expected_provenance_digest': initial['provenance_digest'],
        'expected_draft_revision': 0, 'idempotency_key': str(uuid4()), 'selection_rows': [
            {'key': row['key'], 'quantity_exact': quantities[row['key']['strategy_name']]}
            for row in initial['selection_rows'] if row['editable']]})
    assert response.status_code == 200, response.json
    draft = response.json
    authority(dsn, selection=draft['selection_rows'])
    payload = deepcopy(query(dsn, 'SELECT payload FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1')[0][0])
    payload['model_publication_id'] = SECOND_PUBLICATION
    for cost in payload['engine_inputs']['component_cost_inputs']:
        cost['calculation_increment_exact'] = '0.25'
    query(dsn, """INSERT INTO trading.qt_evaluation_snapshots
        (book_id,source_day,model_publication_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        SELECT book_id,source_day,%s,producer_id,policy_version,'connected-multiowner-v2',as_of,valid_until,%s,%s
        FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1""",
        (SECOND_PUBLICATION, sha256(canonical_qt_input_bytes(payload)).hexdigest(), Json(payload)))
    response = browser.post('/portfolio/qt-previews', headers=headers, json={
        'book_id': 'BOOK', 'draft_id': draft['draft_id'], 'draft_revision': draft['draft_revision'],
        'draft_digest': draft['draft_digest'], 'expected_source_digest': draft['source_digest'],
        'expected_provenance_digest': draft['provenance_digest'], 'idempotency_key': str(uuid4())})
    assert response.status_code == 200, response.json
    preview = response.json
    assert preview['confirmable'] and preview['requires_override'] is False, preview
    assert {row['key']['strategy_name']: row['quantity_exact'] for row in preview['selection_rows']} == {
        **quantities, 'HELD': '8'}
    response = browser.post('/portfolio/qt-previews/' + preview['preview_id'] + '/confirm', headers=headers, json={
        'action': 'confirm_selected_book', 'expected_digest': preview['payload_digest'],
        'idempotency_key': str(uuid4()), 'acknowledge_warnings': False})
    assert response.status_code == 200, response.json
    decision = response.json
    assert decision['report_ready'] is False and decision['receipt'] is None
    return browser, preview, decision


def observe_multiowner(dsn, preview, decision, before):
    now = query(dsn, 'SELECT clock_timestamp()')[0][0]
    fills = []
    for row in preview['selection_rows']:
        key = {**row['key'], 'portfolio_type': 'qt'}
        prior = before[identity(key)]
        held = not row['editable']
        fills.append({'key': key, 'observation_kind': 'carried' if held else 'executed',
            'selected_quantity_exact': row['quantity_exact'], 'average_price_exact': '25' if held else '101',
            'actual_cash_cost_exact': '0' if held else '0.02', 'currency': 'USD',
            'execution_id': None if held else 'synthetic-connected-' + key['strategy_name'],
            'accounting_source_id': 'synthetic-connected-multiowner-accounting',
            'daily_unrealized_pnl_exact': '1.25' if held else '3',
            'daily_realized_pnl_exact': '-0.5' if held else '-1',
            'last_update': (prior[-1] if held else now).isoformat().replace('+00:00', 'Z')})
    payload = {'schema_version': 'qt-execution/v1', 'decision_id': decision['decision_id'], 'book_id': 'BOOK',
        'source_day': preview['source_day'], 'fills': fills, 'results': {'position_count': 3,
        'currency_totals': [{'currency': 'USD', 'actual_cash_cost_exact': '0.04',
                            'daily_unrealized_pnl_exact': '7.25', 'daily_realized_pnl_exact': '-2.5'}]}}
    query(dsn, """INSERT INTO trading.qt_source_policies
        (book_id,purpose,enabled,version,producer_id,policy_version,allowed_override_codes)
        VALUES('BOOK','execution',true,1,'synthetic-connected-execution','connected-execution-v1','[]')""")
    query(dsn, """INSERT INTO trading.qt_execution_observations
        (observation_id,decision_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        VALUES(%s,%s,'synthetic-connected-execution','connected-execution-v1','connected-multiowner-v1',%s,%s,%s,%s)""",
        (OBSERVATION, decision['decision_id'], now, now + timedelta(minutes=5),
         sha256(canonical_qt_input_bytes(payload)).hexdigest(), Json(payload)))


def report_multiowner(preview, directory):
    directory.mkdir()
    assert DELIVERY_GUARD.is_file()
    return subprocess.run([str(REPORT), 'BOOK', preview['source_day'], 'engine-one', str(directory),
                           'ONE', 'TWO', 'HELD'], capture_output=True, text=True, timeout=30,
                          env={**os.environ, 'LD_PRELOAD': str(DELIVERY_GUARD)})


@pytest.mark.parametrize('quantities', [
    {'ONE': '5', 'TWO': '1'}, {'ONE': '5', 'TWO': '-5'}, {'ONE': '2.5', 'TWO': '-1.25'},
], ids=['split-4-2-to-5-1', 'same-symbol-net-zero-5-minus5', 'equity-fractions'])
def test_actual_multiowner_decision_keeps_complete_keys_and_only_report_quantities_change(
        multiowner_db, tmp_path, monkeypatch, quantities):
    before = saved_components(multiowner_db)
    assert len(before) == 3
    browser, preview, decision = prepare_multiowner(multiowner_db, monkeypatch, quantities)
    assert saved_components(multiowner_db) == before
    assert query(multiowner_db, 'SELECT count(*) FROM trading.position_overrides') == [(0,)]
    pending_dir = tmp_path / 'qt-report-multiowner-pending'
    assert report_multiowner(preview, pending_dir).returncode != 0 and list(pending_dir.iterdir()) == []
    observe_multiowner(multiowner_db, preview, decision, before)
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    after = saved_components(multiowner_db)
    assert set(after) == set(before)
    for key in before:
        if key[2] == 'HELD':
            assert after[key] == before[key]
        else:
            assert after[key][0] == Decimal(quantities[key[2]])
    assert query(multiowner_db, "SELECT sum(quantity) FROM trading.positions WHERE portfolio_type='qt' AND symbol='SYN'") == [
        (sum(Decimal(quantity) for quantity in quantities.values()),)]
    ready = browser.get('/portfolio/qt-decisions/' + decision['decision_id'])
    assert ready.status_code == 200 and ready.json['report_ready'] is True, ready.json
    assert ready.json['receipt']['status'] == 'processed'
    assert ready.json['receipt']['report_eligibility']['status'] == 'eligible'
    receipt = query(multiowner_db, 'SELECT publication_payload FROM trading.qt_desk_receipts')[0][0]
    assert {identity(row['key']) for row in receipt['before_accounting']} == set(before)
    assert {identity(row['key']) for row in receipt['after_accounting']} == set(after)
    assert receipt['selected_book_digest'] == receipt['published_book_digest'] == preview['selected_book_digest']
    assert {identity(row['key']): Decimal(row['quantity_exact']) for row in receipt['after_accounting']} == {
        key: values[0] for key, values in after.items()}
    audits = query(multiowner_db, 'SELECT before_state,after_state FROM trading.position_overrides')
    assert len(audits) == 3
    assert {tuple(row[0][field] for field in KEY_FIELDS) for row in audits} == set(before)
    assert {tuple(row[1][field] for field in KEY_FIELDS) for row in audits} == set(after)
    rendered = report_multiowner(preview, tmp_path / 'qt-report-multiowner-processed')
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    output = json.loads(rendered.stdout)
    assert output['delivery_guard_loaded'] is True and output['delivery_calls'] == 0
    assert output['quantities'] == {'ONE': {'SYN': quantities['ONE']}, 'TWO': {'SYN': quantities['TWO']}, 'HELD': {'IMM': '8'}}
    # ONE and TWO's saved average_price is 101 after desk processing
    # (observe_multiowner's fill); HELD/IMM is carried, unchanged, at 25.
    # SYN and IMM are both equities: multiplier 1. Market price is the
    # probe's fixed 102 for every symbol (qt_processed_report_probe.cpp:
    # 79,81,84).
    assert_positions_rows_match_saved(output['report_html'], output['report_csv'],
        output['baseline_html'], output['baseline_csv'], [
            ('One', 'SYN', quantities['ONE'], '101', '1', '102'),
            ('Two', 'SYN', quantities['TWO'], '101', '1', '102'),
            ('Held', 'IMM', '8', '25', '1', '102'),
        ])
    print('QT_MULTIOWNER_REPORT_EVIDENCE=' + json.dumps({'selected_quantities_exact': quantities,
          'source_day': preview['source_day'], **output}, sort_keys=True, separators=(',', ':')), flush=True)


# Append-only proposed addition to test_qt_connected_multiowner.py.
# Prepared outside pytest collection while root owns the full API run.

FUTURE_PUBLICATION = "10000000-0000-4000-8000-000000000081"
FUTURE_REVISION = "30000000-0000-4000-8000-000000000081"


@pytest.fixture
def future_connected_db(connected_db):
    dsn = connected_db
    day = query(dsn, "SELECT (clock_timestamp() AT TIME ZONE 'UTC')::date")[0][0].isoformat()
    # Original SYN publication remains historical; a distinct FUT insertion is
    # proven by the later complete source publication, never a type relabel.
    query(dsn, """INSERT INTO metadata.contract_metadata VALUES('FUT','FUT','FUTURE');
        UPDATE trading.positions SET symbol='FUT';
        UPDATE trading.positions SET qt_proposal_revision=%s WHERE portfolio_type='qt_proposal';""",
        (FUTURE_REVISION,))
    key = dict(zip(KEY_FIELDS, ('BOOK', 'engine-one', 'ONE', day, 'FUT', 'system')))
    seed = [{'key': key, 'quantity_exact': '4', 'average_price_exact': '100'}]
    manifest = [{'key': {**key, 'portfolio_type': 'qt_proposal'}, 'quantity_exact': '4',
                 'average_price_exact': '100', 'action': 'inserted', 'position_revision': FUTURE_REVISION,
                 'origin_publication_id': FUTURE_PUBLICATION}]
    query(dsn, """INSERT INTO trading.qt_model_seed_publications
        (publication_id,portfolio_id,strategy_id,source_day,publication_version,system_components,
         seed_digest,producer_version,proposal_components,proposal_manifest_digest)
        VALUES(%s,'BOOK','engine-one',%s,2,%s,%s,'synthetic-connected-future',%s,%s)""",
        (FUTURE_PUBLICATION, day, Json(seed), qt_digest_v1({'seed_rows': seed}), Json(manifest),
         internal_snapshot_digest('qt-proposal-manifest/v1', {'proposal_rows': manifest})))
    return dsn


def explicit_future_authority(dsn, selection):
    from algolens.domain.portfolio.position_decimal import canonical_position_decimal8
    authority(dsn, selection=selection)
    payload = deepcopy(query(dsn, 'SELECT payload FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1')[0][0])
    instrument = {'instrument_type': 'FUTURE', 'symbol': 'FUT'}
    payload['model_publication_id'] = FUTURE_PUBLICATION
    payload['instrument_catalog'] = [{'key': selection[0]['key'], 'instrument_type': 'FUTURE', 'editable': True}]
    inputs = payload['engine_inputs']
    for value in inputs['risk_inputs']['valuations']:
        value['instrument'] = deepcopy(instrument)
        value['price_multiplier'] = '50'
    for index, value in enumerate(inputs['risk_inputs']['closes']):
        value['instrument'] = deepcopy(instrument)
        value['close'] = canonical_position_decimal8(Decimal('98') + Decimal(index) * Decimal('0.25'))
    inputs['quantity_rules'] = [{'instrument': deepcopy(instrument), 'increment_exact': '1',
                                'mode': 'reject_off_increment', 'minimum_exact': '-1000000', 'maximum_exact': '1000000'}]
    inputs['component_cost_inputs'] = [{'key': selection[0]['key'], 'instrument': deepcopy(instrument),
        'calculation_increment_exact': '1', 'cash_cost_per_increment_exact': '0.01',
        'approved_model_id': 'linear-cash-per-increment-v1', 'source_id': 'synthetic-future-whole-cost-v1', 'currency': 'USD'}]
    query(dsn, """INSERT INTO trading.qt_evaluation_snapshots
        (book_id,source_day,model_publication_id,producer_id,policy_version,source_version,as_of,valid_until,content_digest,payload)
        SELECT book_id,source_day,%s,producer_id,policy_version,'connected-explicit-future-v2',as_of,valid_until,%s,%s
        FROM trading.qt_evaluation_snapshots ORDER BY snapshot_id DESC LIMIT 1""",
        (FUTURE_PUBLICATION, sha256(canonical_qt_input_bytes(payload)).hexdigest(), Json(payload)))


def full_future_refusal_state(dsn):
    tables = ('positions', 'position_overrides', 'qt_drafts', 'qt_draft_heads', 'qt_idempotency',
              'qt_previews', 'qt_decisions', 'qt_override_requests', 'qt_override_approvals',
              'qt_desk_receipts', 'qt_desk_results', 'qt_execution_observations')
    return {table: query(dsn, 'SELECT row_to_json(p)::text FROM trading.' + table + ' p ORDER BY row_to_json(p)::text')
            for table in tables}


def test_actual_future_fraction_refuses_without_writes_then_whole_seven_publishes_and_renders(
        future_connected_db, tmp_path, monkeypatch, average_price_exact='101'):
    # average_price_exact is the true saved basis for FUT after this flow's
    # desk processing, which differs by which producer writes it. The
    # standalone flow (this function's default) writes it via observe()'s
    # synthetic fill (average_price_exact='101', test_qt_connected_workflow.py
    # :95). test_qt_accounting_connected.py wraps this same function with its
    # own accounting-producer desk() and observe() and must pass its own
    # actual basis -- see that module's call site for the derivation.
    from tests.integration.test_qt_connected_workflow import observe, report
    dsn = future_connected_db
    config = native_evaluator_configuration()
    service = create_qt_workflow_service(QtWorkflowRepository(lambda: psycopg2.connect(dsn)),
                                evaluator_bundle_directory=config['bundle_directory'])
    _, clients, _ = http_harness(dsn, service, monkeypatch)
    browser, headers = clients(101)
    response = browser.get('/portfolio/qt-books/BOOK/draft')
    assert response.status_code == 200, response.json
    initial = response.json
    assert len(initial['selection_rows']) == 1
    row = initial['selection_rows'][0]
    assert row['asset_type'] == 'FUTURE' and row['key']['symbol'] == 'FUT'
    assert row['quantity_exact'] == '4' and row['origin'] == 'verified_model_seed'
    request = {'expected_source_digest': initial['source_digest'], 'expected_provenance_digest': initial['provenance_digest'],
        'expected_draft_revision': 0, 'idempotency_key': str(uuid4()),
        'selection_rows': [{'key': row['key'], 'quantity_exact': '2.5'}]}
    before_refusal = full_future_refusal_state(dsn)
    refused = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json=request)
    assert refused.status_code == 400 and refused.json['error']['code'] == 'invalid_qt_exact', refused.json
    assert full_future_refusal_state(dsn) == before_refusal
    response = browser.put('/portfolio/qt-books/BOOK/draft', headers=headers, json={
        **request, 'idempotency_key': str(uuid4()), 'selection_rows': [{'key': row['key'], 'quantity_exact': '7'}]})
    assert response.status_code == 200, response.json
    draft = response.json
    assert draft['selection_rows'][0]['asset_type'] == 'FUTURE'
    explicit_future_authority(dsn, draft['selection_rows'])
    response = browser.post('/portfolio/qt-previews', headers=headers, json={
        'book_id': 'BOOK', 'draft_id': draft['draft_id'], 'draft_revision': draft['draft_revision'],
        'draft_digest': draft['draft_digest'], 'expected_source_digest': draft['source_digest'],
        'expected_provenance_digest': draft['provenance_digest'], 'idempotency_key': str(uuid4())})
    assert response.status_code == 200, response.json
    preview = response.json
    assert preview['confirmable'] is True and preview['requires_override'] is False, preview
    assert preview['selection_rows'][0]['quantity_exact'] == '7'
    assert preview['selection_rows'][0]['asset_type'] == 'FUTURE'
    assert preview['evaluation']['selected_costs']['total_exact'] == '0.02'
    before_publish = saved_components(dsn)
    response = browser.post('/portfolio/qt-previews/' + preview['preview_id'] + '/confirm', headers=headers, json={
        'action': 'confirm_selected_book', 'expected_digest': preview['payload_digest'],
        'idempotency_key': str(uuid4()), 'acknowledge_warnings': False})
    assert response.status_code == 200, response.json
    decision = response.json
    assert decision['report_ready'] is False and decision['receipt'] is None
    assert saved_components(dsn) == before_publish
    assert query(dsn, 'SELECT count(*) FROM trading.position_overrides') == [(0,)]
    pending_dir = tmp_path / 'qt-report-future-pending'
    assert report(preview, pending_dir).returncode != 0 and list(pending_dir.iterdir()) == []
    observe(dsn, preview, decision, '7')
    processed = desk(decision)
    assert processed.returncode == 0, processed.stdout + processed.stderr
    after = saved_components(dsn)
    assert set(after) == set(before_publish)
    assert {key: values[0] for key, values in after.items()} == {
        identity({**row['key'], 'portfolio_type': 'qt'}): Decimal('7')}
    ready = browser.get('/portfolio/qt-decisions/' + decision['decision_id'])
    assert ready.status_code == 200 and ready.json['report_ready'] is True, ready.json
    assert ready.json['receipt']['status'] == 'processed'
    assert ready.json['receipt']['report_eligibility']['status'] == 'eligible'
    rendered = report(preview, tmp_path / 'qt-report-future-processed')
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    output = json.loads(rendered.stdout)
    assert output['delivery_guard_loaded'] is True and output['delivery_calls'] == 0
    assert output['quantities'] == {'ONE': {'FUT': '7'}}
    # average_price_exact (default '101', overridden by
    # test_qt_accounting_connected.py) is the true saved basis for this
    # fixture -- see the function-level comment above. FUT's multiplier is 50
    # (explicit_future_authority's price_multiplier, this file:390) and the
    # probe's market price is the fixed 102 (qt_processed_report_probe.cpp:
    # 79,81,84).
    assert_positions_rows_match_saved(output['report_html'], output['report_csv'],
        output['baseline_html'], output['baseline_csv'],
        [('One', 'FUT', '7', average_price_exact, '50', '102')])
    print('QT_FUTURES_REPORT_EVIDENCE=' + json.dumps({'selected_quantity_exact': '7',
          'source_day': preview['source_day'], **output}, sort_keys=True, separators=(',', ':')), flush=True)

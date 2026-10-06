"""Staged retained-S-bundle transport; a digest summary is never SQL proof.

The caller proves original publication and archived authority before invocation.
Only native code computes the successor. No expected successor is supplied.
The original accounting operation and its canonical bounds remain unchanged.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_equity_accounting_proof import canonical_equity_accounting_output_bytes
from algolens.infrastructure.portfolio.qt_equity_finalization_proof import FINALIZATION_MARKET_SCHEMA
from algolens.infrastructure.portfolio.qt_equity_recompute_client import (
    _AUTHORITY, _INPUT, _need, _shape, _digest, _text, _uuid, _day, _utc, _pairs, _reject_number)
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess, QtEvaluatorUnavailable

_SCHEMA = 'qt-equity-finalization-proof/v1'
_OPERATION = 'recompute_equity_finalization'
_CALCULATION = 'equity-prior-close-mark/v1'
_PROVENANCE = {'finalization_id','original_accounting_input_id','original_run_result_digest',
    'original_observation_digest','predecessor_finalization_source_id','predecessor_finalization_digest',
    'market_source_id','market_source_digest','actions_source_id','actions_source_digest',
    'unchanged_execution_digest','policy_identity','finalizer_authority'}
_MARKET = {'schema_version','calculation_version','book_id','source_day','model_publication_id',
    'previous_day','valuation_time','day_mode','currency','cost_config','instruments','actions_source_id','actions_source_digest'}
_RESPONSE = {'schema','operation','evaluator_build','context_fingerprint','calculation_version',
    'original_output_digest','market_digest','actions_digest','before_financial_digest','provenance_digest','successor_digest'}


def _source_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8', 'strict')


def _hash(value): return sha256(_source_bytes(value)).hexdigest()


def _parse_original(text):
    """Bounded duplicate-free canonical source JSON with a closed float child."""
    _need(type(text) is str and len(text.encode('utf-8', 'strict')) <= 1024*1024)
    result = json.loads(text, object_pairs_hook=_pairs, parse_constant=_reject_number)
    events = 0
    def check(value, depth=0):
        nonlocal events
        events += 1
        _need(events <= 400000 and depth <= 32)
        if type(value) is dict:
            for key, child in value.items(): check(key, depth+1); check(child, depth+1)
        elif type(value) is list:
            for child in value: check(child, depth+1)
    check(result)
    _need(canonical_equity_accounting_output_bytes(result) == text.encode('utf-8', 'strict'))
    return result


class QtEquityFinalizationUnavailable(QtEvaluatorUnavailable):
    """Safe fixed classification, never native stderr or financial operands."""


class QtEquityFinalizationRecomputeClient:
    def __init__(self, process):
        if not isinstance(process, QtEvaluatorProcess):
            raise QtEquityFinalizationUnavailable('equity_finalization_configuration_unavailable')
        self.process = process

    def recompute(self, decision, original_input, original_output, market_payload,
                  actions_payload, before_financial, provenance, finalizer_authority,
                  *, expected_authority_digest):
        try:
            process = self.process
            _need(process.bundle_directory is not None and process.expected_bundle_sha256 is not None)
            original_wire = canonical_equity_accounting_output_bytes(original_output)
            _need(len(original_wire) <= 1024*1024)
            out = _parse_original(original_wire.decode('utf-8', 'strict'))
            values = {'decision':decision,'original_input':original_input,'original_output_json':'',
                'market_payload':market_payload,'actions_payload':actions_payload,
                'before_financial':before_financial,'provenance':provenance,'finalizer_authority':finalizer_authority}
            # Only the dedicated nested string is exempt from the existing
            # 4096-character bound. Every other operand remains input-canonical.
            values = json.loads(canonical_qt_input_bytes(values), object_pairs_hook=_pairs)
            d,i,m,e,b,p,a = (values[k] for k in ('decision','original_input','market_payload',
                'actions_payload','before_financial','provenance','finalizer_authority'))
            _shape(d, {'decision_id','book_id','source_day','model_publication_id'})
            _uuid(d['decision_id']); _text(d['book_id']); _day(d['source_day']); _uuid(d['model_publication_id'])
            _shape(a, _AUTHORITY); _need(a['schema_version'] == 'qt-input-authority/v1')
            _digest(expected_authority_digest); _need(_hash(a) == expected_authority_digest)
            for key in ('evaluator_sha256','evaluator_bundle_sha256','content_digest'): _digest(a[key])
            _need(a['evaluator_build'] == process.expected_build and a['evaluator_sha256'] == process.expected_sha256
                  and a['evaluator_bundle_sha256'] == process.expected_bundle_sha256)
            for key in ('producer_id','policy_version','source_version','evaluator_build'): _text(a[key])
            _need(type(a['snapshot_id']) is int and 0 < a['snapshot_id'] < (1<<63))
            _need(type(a['policy_revision']) is int and 0 < a['policy_revision'] < (1<<63))
            _need(_utc(a['as_of']) < _utc(a['valid_until'])); _utc(a['policy_updated_at'])
            for key in ('book_id','source_day','model_publication_id'): _need(a[key] == d[key])
            codes = a['allowed_override_codes']
            _need(type(codes) is list and all(type(c) is str and 0 < len(c) <= 4096 for c in codes) and codes == sorted(codes))
            _shape(i, _INPUT)
            empty_owner=i['schema_version']=='qt-equity-accounting-input-empty-owner/v2'
            _need(i['schema_version'] in {'qt-equity-accounting-input/v1','qt-equity-accounting-input-empty-owner/v2'}
                  and i['calculation_version'] == 'qt-equity-main08b15c/v1')
            _need(out['schema_version']==('qt-equity-accounting-empty-owner/v2' if empty_owner else 'qt-equity-accounting/v1'))
            if empty_owner:
                _need(i['previous_positions']==i['instruments']==i['actions']==[]
                    and type(i['previous_totals']) is list and len(i['previous_totals'])==1
                    and i['previous_totals'][0]['strategy_id']=='LIVE_EQUITY_MEAN_REVERSION')
            for key in ('decision_id','book_id','source_day'): _need(i[key] == d[key] == out['observation'][key])
            _need(i['timestamp'] == d['source_day']+'T00:00:00Z' and i['day_mode'] == 'open' and i['currency'] == 'USD')
            _need(out['input_digest'] == _hash(i) and out['producer_authority'] == a)
            _shape(p, _PROVENANCE); _need(p['finalizer_authority'] == a)
            _uuid(p['finalization_id']); _uuid(p['market_source_id'])
            _need(p['original_accounting_input_id'] == i['accounting_input_id']
                  and p['original_run_result_digest'] == _hash(out)
                  and p['original_observation_digest'] == _hash(out['observation'])
                  and p['unchanged_execution_digest'] == _hash(out['executions'])
                  and p['predecessor_finalization_source_id'] == i['prior_finalization_source_id']
                  and p['predecessor_finalization_digest'] == i['prior_finalization_digest'])
            _shape(m, _MARKET); _shape(e, {'schema_version','book_id','source_day','previous_day','valuation_time','events'})
            # The finalization-only market (equity day 2) binds no model and is only for a non-empty-owner S->D finalization.
            finalization_only = not empty_owner and m['schema_version'] == FINALIZATION_MARKET_SCHEMA
            _need((finalization_only or m['schema_version'] == ('qt-equity-accounting-market-empty-owner/v2' if empty_owner else 'qt-equity-accounting-market/v1'))
                  and m['calculation_version'] == i['calculation_version']
                  and m['day_mode'] == 'open' and m['currency'] == 'USD' and e['schema_version'] == 'qt-equity-actions-source/v1')
            _day(m['source_day'])
            if finalization_only: _need(m['model_publication_id'] is None)
            else: _uuid(m['model_publication_id'])
            _need(m['source_day'] > d['source_day'] and m['previous_day'] == d['source_day']
                  and m['book_id'] == d['book_id'] and m['valuation_time'] == m['source_day']+'T00:00:00Z')
            for key in ('book_id','source_day','previous_day','valuation_time'): _need(e[key] == m[key])
            _need(e['events'] == [] and p['market_source_digest'] == _hash(m)
                  and p['actions_source_digest'] == m['actions_source_digest'] == _hash(e)
                  and p['actions_source_id'] == m['actions_source_id'])
            policy = p['policy_identity']; _shape(policy, {'book_id','purpose','version','producer_id','policy_version'})
            _need(policy['book_id'] == d['book_id'] and policy['purpose'] == 'execution'
                  and type(policy['version']) is int and policy['version'] > 0)
            _text(policy['producer_id']); _text(policy['policy_version'])
            _shape(b, {'positions','live_results','equity_curve'}); _need(all(type(b[k]) is list for k in b))
            if empty_owner:
                _need(m['instruments']==[] and b['positions']==[] and len(b['live_results'])==len(b['equity_curve'])==1
                    and b['live_results']==out['live_results'] and b['equity_curve']==out['equity_curve'])
            request = {'schema':_SCHEMA,'operation':_OPERATION,'evaluator_build':process.expected_build,**values}
            request['context_fingerprint'] = ''
            canonical_qt_input_bytes(request)
            request['original_output_json'] = original_wire.decode('utf-8', 'strict')
            request['context_fingerprint'] = _hash({k:v for k,v in request.items() if k != 'context_fingerprint'})
            # Native source-canonical mode is independently capped at 1MiB.
            # The existing 8MiB transport limit remains an outer ceiling.
            encoded = _source_bytes(request); _need(len(encoded) <= min(1024*1024, process.max_input_bytes))
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,QtWorkflowError,ArithmeticError):
            raise QtEquityFinalizationUnavailable('equity_finalization_request_invalid') from None
        if os.name != 'posix' or not Path('/usr/bin/unshare').is_file() or not hasattr(os, 'memfd_create'):
            raise QtEquityFinalizationUnavailable('equity_finalization_isolation_unavailable')
        try:
            with process._launch() as (argv, pass_fds):
                with tempfile.TemporaryDirectory(prefix='qt-equity-finalizer-') as scratch:
                    child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        env={'PATH':'/usr/bin:/bin','TZ':'UTC','PYTHON_DOTENV_DISABLED':'1'}, cwd=scratch,
                        start_new_session=True, pass_fds=pass_fds)
                    output = process._exchange(child, encoded)
        except (QtEvaluatorUnavailable,OSError):
            raise QtEquityFinalizationUnavailable('equity_finalization_transport_unavailable') from None
        try:
            result = json.loads(output.decode('utf-8', 'strict'), object_pairs_hook=_pairs,
                                parse_float=_reject_number, parse_constant=_reject_number)
            _shape(result, _RESPONSE); _need(all(type(v) is str for v in result.values()))
            for key in ('schema','operation','evaluator_build','context_fingerprint'): _need(result[key] == request[key])
            _need(result['calculation_version'] == _CALCULATION)
            for key in _RESPONSE-{'schema','operation','evaluator_build','context_fingerprint','calculation_version'}: _digest(result[key])
            for key,value in [('original_output',out),('market',m),('actions',e),('before_financial',b),('provenance',p)]:
                _need(result[key+'_digest'] == _hash(value))
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
            raise QtEquityFinalizationUnavailable('equity_finalization_response_invalid') from None
        return result

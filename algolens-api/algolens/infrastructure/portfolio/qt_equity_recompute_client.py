"""Staged, separate bounded equity recomputation client, not SQL authority.

The proof caller must establish durable source/decision/physical closure first.
No expected output is sent to the native kernel. Protected launch/exchange are
temporarily reused without modifying the accepted QtEvaluatorProcess.run wire.
"""
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import UUID

from algolens.domain.portfolio.qt_workflow_errors import QtWorkflowError
from algolens.domain.portfolio.qt_workflow_models import QtSelectionRow
from algolens.domain.shared.fixed_decimal8 import parse_fixed_decimal8
from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes
from algolens.infrastructure.portfolio.qt_evaluator_process import QtEvaluatorProcess, QtEvaluatorUnavailable

_SCHEMA = 'qt-equity-proof/v1'
_OPERATION = 'recompute_equity_accounting'
_CALCULATION = 'qt-equity-main08b15c/v1'
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_UTC = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z\Z')
_AUTHORITY = frozenset({'schema_version','book_id','source_day','model_publication_id','snapshot_id',
    'source_version','as_of','valid_until','content_digest','producer_id','policy_version','policy_revision',
    'policy_updated_at','evaluator_build','evaluator_sha256','evaluator_bundle_sha256','allowed_override_codes'})
_INPUT = frozenset({'schema_version','calculation_version','decision_id','book_id','source_day',
    'accounting_input_id','market_source_id','market_source_digest','accounting_source_id',
    'prior_finalization_source_id','prior_finalization_digest','previous_day','timestamp','day_mode',
    'currency','previous_positions','previous_totals','instruments','cost_config','actions'})
_RESPONSE = frozenset({'schema','operation','evaluator_build','context_fingerprint','calculation_version',
    'input_digest','selection_digest','financial_output_digest','output_digest'})


def _need(ok):
    if not ok: raise ValueError('invalid_equity_recompute_request')


def _shape(value, fields): _need(type(value) is dict and set(value) == fields)
def _text(value): _need(type(value) is str and bool(value.strip()) and len(value) <= 4096)
def _digest(value): _need(type(value) is str and _HASH.fullmatch(value) is not None)
def _hash(value): return sha256(canonical_qt_input_bytes(value)).hexdigest()
def _uuid(value): _need(type(value) is str and str(UUID(value)) == value)
def _day(value): _need(type(value) is str and date.fromisoformat(value).isoformat() == value)


def _utc(value):
    _need(type(value) is str and _UTC.fullmatch(value) is not None)
    result = datetime.fromisoformat(value.replace('Z','+00:00'))
    _need(result.tzinfo is not None and result.utcoffset() == timezone.utc.utcoffset(result))
    return result


def _pairs(items):
    result = {}
    for name, value in items:
        if name in result: raise ValueError('duplicate_equity_response_key')
        result[name] = value
    return result


def _reject_number(value): raise ValueError('equity_response_number_unsupported')


class QtEquityRecomputeUnavailable(QtEvaluatorUnavailable):
    """Fixed safe reason; no native stderr or financial operands."""


class QtEquityRecomputeClient:
    def __init__(self, process):
        if not isinstance(process, QtEvaluatorProcess):
            raise QtEquityRecomputeUnavailable('equity_recompute_configuration_unavailable')
        self.process = process

    def recompute(self, decision, selection_rows, accounting_input, producer_authority,
                  *, expected_authority_digest):
        """Return a transport-validated computed digest summary, not readiness.

        expected_authority_digest is captured from the original immutable
        preview external source by the independent SQL publication proof.
        No current-clock lease check or mutable-policy fallback is performed.
        """
        try:
            process = self.process
            _need(process.bundle_directory is not None and process.expected_bundle_sha256 is not None)
            # Freeze caller operands before validation and launch; canonical
            # input mode rejects financial float tokens and bounds recursion.
            values = json.loads(canonical_qt_input_bytes({'decision':decision,'selection_rows':selection_rows,
                'accounting_input':accounting_input,'producer_authority':producer_authority}))
            d,s,i,a = (values[name] for name in ('decision','selection_rows','accounting_input','producer_authority'))
            _shape(d, {'decision_id','book_id','source_day'})
            _uuid(d['decision_id']); _text(d['book_id']); _day(d['source_day'])
            _shape(a,_AUTHORITY); _need(a['schema_version'] == 'qt-input-authority/v1')
            _digest(expected_authority_digest); _need(_hash(a) == expected_authority_digest)
            for field in ('evaluator_sha256','evaluator_bundle_sha256','content_digest'): _digest(a[field])
            _need(a['evaluator_build'] == process.expected_build and a['evaluator_sha256'] == process.expected_sha256
                  and a['evaluator_bundle_sha256'] == process.expected_bundle_sha256)
            for field in ('producer_id','policy_version','source_version','evaluator_build'): _text(a[field])
            _uuid(a['model_publication_id'])
            _need(type(a['snapshot_id']) is int and 0 < a['snapshot_id'] < (1<<63))
            _need(type(a['policy_revision']) is int and a['policy_revision'] > 0)
            _need(_utc(a['as_of']) < _utc(a['valid_until'])); _utc(a['policy_updated_at'])
            _day(a['source_day']); _need(a['book_id'] == d['book_id'] and a['source_day'] == d['source_day'])
            codes = a['allowed_override_codes']
            _need(type(codes) is list and all(type(code) is str and 0 < len(code) <= 4096 for code in codes)
                  and codes == sorted(codes))
            _shape(i,_INPUT)
            empty_owner=i['schema_version']=='qt-equity-accounting-input-empty-owner/v2'
            _need(i['schema_version'] in {'qt-equity-accounting-input/v1','qt-equity-accounting-input-empty-owner/v2'} and i['calculation_version'] == _CALCULATION
                  and i['day_mode'] == 'open' and i['currency'] == 'USD')
            for field in ('decision_id','book_id','source_day'): _need(i[field] == d[field])
            _uuid(i['accounting_input_id']); _uuid(i['market_source_id'])
            _digest(i['market_source_digest']); _digest(i['prior_finalization_digest'])
            _day(i['previous_day']); _need(i['previous_day'] < d['source_day'])
            _need(i['timestamp'] == d['source_day'] + 'T00:00:00Z')
            for field in ('previous_positions','previous_totals','instruments','actions'): _need(type(i[field]) is list)
            _need(type(i['cost_config']) is dict and type(s) is list and (not s if empty_owner else bool(s)))
            if empty_owner:
                _need(all(i[name]==[] for name in ('previous_positions','instruments','actions'))
                      and len(i['previous_totals'])==1)
                total=i['previous_totals'][0]
                _shape(total,{'strategy_id','initial_capital_exact','equity_exact','total_pnl_exact',
                    'total_realized_pnl_exact','total_transaction_costs_exact','total_unrealized_pnl_exact'})
                _need(total['strategy_id']=='LIVE_EQUITY_MEAN_REVERSION')
                for name in ('initial_capital_exact','equity_exact','total_pnl_exact','total_realized_pnl_exact',
                             'total_transaction_costs_exact','total_unrealized_pnl_exact'):
                    _need(type(total[name]) is str and parse_fixed_decimal8(total[name]) is not None)
                from decimal import Decimal
                _need(Decimal(total['initial_capital_exact'])>0 and Decimal(total['equity_exact'])>0
                      and Decimal(total['total_unrealized_pnl_exact'])==0)
            seen = set()
            for raw in s:
                row = QtSelectionRow.from_wire(raw)
                _need(row.asset_type == 'EQUITY' and row.key.portfolio_id == d['book_id'] and row.key.date == d['source_day'])
                _need(row.key.portfolio_type in {'qt','qt_proposal'})
                identity = (row.key.portfolio_id,row.key.strategy_id,row.key.strategy_name,row.key.date,row.key.symbol)
                _need(identity not in seen); seen.add(identity)
                _need(type(row.quantity_exact) is str and parse_fixed_decimal8(row.quantity_exact) is not None)
                if row.average_price_exact is not None:
                    _need(type(row.average_price_exact) is str and parse_fixed_decimal8(row.average_price_exact) is not None)
            request = {'schema':_SCHEMA,'operation':_OPERATION,'evaluator_build':process.expected_build,**values}
            request['context_fingerprint'] = _hash(request)
            encoded = canonical_qt_input_bytes(request)
            _need(len(encoded) <= process.max_input_bytes)
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError,QtWorkflowError,ArithmeticError):
            raise QtEquityRecomputeUnavailable('equity_recompute_request_invalid') from None
        if os.name != 'posix' or not Path('/usr/bin/unshare').is_file() or not hasattr(os,'memfd_create'):
            raise QtEquityRecomputeUnavailable('equity_recompute_isolation_unavailable')
        try:
            # Explicit full bundle only. Protected helpers already enforce
            # verified private bytes, timeout/size/strict stderr/reaping.
            with process._launch() as (argv,pass_fds):
                with tempfile.TemporaryDirectory(prefix='qt-equity-proof-') as scratch:
                    child = subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                        env={'PATH':'/usr/bin:/bin','TZ':'UTC','PYTHON_DOTENV_DISABLED':'1'},cwd=scratch,
                        start_new_session=True,pass_fds=pass_fds)
                    output = process._exchange(child,encoded)
        except (QtEvaluatorUnavailable,OSError):
            raise QtEquityRecomputeUnavailable('equity_recompute_transport_unavailable') from None
        try:
            result = json.loads(output.decode('utf-8','strict'),object_pairs_hook=_pairs,
                                parse_float=_reject_number,parse_constant=_reject_number)
            _shape(result,_RESPONSE)
            for field in ('schema','operation','evaluator_build','context_fingerprint'): _need(result[field] == request[field])
            _need(result['calculation_version'] == _CALCULATION)
            for field in ('input_digest','selection_digest','financial_output_digest','output_digest'): _digest(result[field])
            _need(result['input_digest'] == _hash(i) and result['selection_digest'] == _hash(s))
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
            raise QtEquityRecomputeUnavailable('equity_recompute_response_invalid') from None
        return result

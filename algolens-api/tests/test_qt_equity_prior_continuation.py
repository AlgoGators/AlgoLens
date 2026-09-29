"""Equity day 2 (verified-desk-prior), API mirror, pure controls (lane A1).

Everything here is synthetic and network/database free.  The rows have the to_jsonb shape the
native validator sees (the restated prices are hand-computed literals, not produced by the port);
a few tests hand the same rows over in the psycopg2 representation (UUID / date / datetime) to
prove the port compares meaning, not spelling.  The native/API shared vectors are consumed by
test_qt_equity_prior_continuation_vectors.py.
"""
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID
import importlib
import json

import pytest

from algolens.infrastructure.portfolio.qt_evaluation_inputs import canonical_qt_input_bytes

proof = importlib.import_module('algolens.infrastructure.portfolio.qt_equity_finalization_proof')
core = importlib.import_module('algolens.infrastructure.portfolio.qt_equity_accounting_proof')
evidence = importlib.import_module('algolens.infrastructure.portfolio.qt_equity_finalization_evidence')

CODE = 'qt_equity_prior_continuation_unavailable'
FIN = 'qt-equity-finalization-market/v1'
V1 = 'qt-equity-accounting-market/v1'
BOOK, S, D = 'BOOK', '2026-09-25', '2026-09-26'
S_DEC, D_DEC = '10000000-0000-4000-8000-000000000001', '10000000-0000-4000-8000-000000000002'
P1, P2 = '50000000-0000-4000-8000-000000000001', '50000000-0000-4000-8000-000000000002'
FID, M_ID, A_ID = '40000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000001', '30000000-0000-4000-8000-000000000002'
ACT_M, ACT_D = 'qt-actions/M-empty', 'qt-actions/D-applied'
ENGINE, OWNER_NAME = 'LIVE_EQUITY_MEAN_REVERSION', 'EQUITY_MEAN_REVERSION'
COST = {'explicit_fee_per_contract': '1.5', 'max_participation': '1', 'min_adv': '10000', 'min_participation': '0'}
# Hand-computed Decimal(1e-8) restatements of the MODEL arithmetic (equity_model_action_frame.cpp:80).
SPLIT_2_OF_90 = '45'
DIVIDEND_1_OVER_100_OF_90 = '89.10891089'          # 90 / (1 + 1/100), screened to 8 places
ADR_HALF_OF_90 = '180'                              # factor 0.5 < 1
SPLIT_3_THEN_DIVIDEND_OF_37_13 = '12.25412542'     # 37.13 / 3 (screened) / 1.01 (screened)
DIVIDEND_THEN_SPLIT_3_OF_37_13 = '12.25412541'     # the other order differs in the last place


def h(value):
    return sha256(canonical_qt_input_bytes(value)).hexdigest()


def key(symbol, day):
    return {'portfolio_id': BOOK, 'strategy_id': ENGINE, 'strategy_name': OWNER_NAME, 'date': day, 'symbol': symbol,
            'portfolio_type': 'qt'}


def position(symbol, quantity='10', basis='50', frame='adjusted-1'):
    return {'key': key(symbol, S), 'quantity_exact': quantity, 'average_price_exact': basis,
            'daily_realized_pnl_exact': '0', 'daily_unrealized_pnl_exact': '0', 'last_update': D + 'T00:00:00Z',
            'basis_evidence': {'source_id': 'qt-basis/' + FID + '/' + symbol, 'source_digest': 'c' * 64,
                               'price_frame_id': frame, 'formed_day': '2026-09-20'}}


def quote(price, frame, source):
    return {'date': S, 'price_frame_id': frame, 'price_model_number': price, 'source_digest': 'f' * 64, 'source_id': source}


def instrument(symbol, price, frame='adjusted-1', source=None):
    source = source or 'owned-S-close/' + symbol  # one source-id namespace, one id per symbol
    return {'asset_type': 'EQUITY', 'symbol': symbol, 'mark': quote(price, frame, source), 'reference': quote(price, frame, source),
            'cost_evidence': {'adv_model_number': '1000000', 'date': S, 'source_digest': 'd' * 64,
                              'source_id': 'owned-cost', 'volatility_multiplier_model_number': '1'},
            'cost_parameters': {'tick_size': '0.01', 'point_value': '1'}}


def event(symbol, kind, value, close=None, before='adjusted-1', after='adjusted-2', quantity=None):
    return {'key': key(symbol, D), 'type': kind, 'ex_date': D, 'value_model_number': value,
            'basis_provenance': 'formed_on_or_before_ex_date', 'basis_provenance_evidence': 'qt-basis/' + FID + '/' + symbol,
            'frame_before': before, 'frame_after': after, 'raw_close_model_number': close, 'eligible_quantity_exact': quantity}


def parts(action=None, new_symbol=False, v2=None):
    """Plain primitives; assemble() derives rows, hashes and links."""
    p = SimpleNamespace(positions=[position('SYN')], m_instruments=[instrument('SYN', '90')], events=[],
                        cost_m=deepcopy(COST), cost_a=deepcopy(COST), vt_m=None, vt_a=None, vt_act=None, cur_m='USD', cur_a='USD',
                        sid=S_DEC, fdec=S_DEC, act_d=ACT_D, fpdec=None)
    if action == 'split':
        p.events = [event('SYN', 'SPLIT', '2')]
        p.a_instruments = [instrument('SYN', SPLIT_2_OF_90, 'adjusted-2')]
    elif action == 'adr':
        p.events = [event('SYN', 'ADR_SPLIT', '0.5')]
        p.a_instruments = [instrument('SYN', ADR_HALF_OF_90, 'adjusted-2')]
    elif action == 'dividend':
        p.events = [event('SYN', 'DIVIDEND', '1', close='100', quantity='10')]
        p.a_instruments = [instrument('SYN', DIVIDEND_1_OVER_100_OF_90, 'adjusted-2')]
    elif action == 'both':
        p.m_instruments = [instrument('SYN', '37.13')]
        p.events = [event('SYN', 'SPLIT', '3', after='adjusted-2'),
                    event('SYN', 'DIVIDEND', '1', close='100', before='adjusted-2', after='adjusted-3', quantity='10')]
        p.a_instruments = [instrument('SYN', SPLIT_3_THEN_DIVIDEND_OF_37_13, 'adjusted-3')]
    else:
        p.a_instruments = [instrument('SYN', '90')]
    if new_symbol:
        p.a_instruments.append(instrument('NEW', '12'))
    p.v2 = bool(p.events) if v2 is None else v2
    return p


def actions_row(source_id, events, day=D, valuation_time=None):
    payload = {'schema_version': 'qt-equity-actions-source/v1', 'book_id': BOOK, 'source_day': day, 'previous_day': S,
               'valuation_time': day + 'T00:00:00Z' if valuation_time is None else valuation_time, 'events': events}
    return {'source_id': source_id, 'purpose': 'actions', 'book_id': BOOK, 'source_day': day, 'producer_id': 'owned-producer',
            'policy_version': 'owned-policy/v1', 'policy_revision': 1, 'source_version': source_id, 'content_digest': h(payload),
            'payload': payload, 'created_at': D + 'T00:00:01.000001+00:00'}


def market_row(source_id, schema, model, instruments, actions, cost=None, valuation_time=None, currency='USD'):
    payload = {'schema_version': schema, 'calculation_version': 'qt-equity-main08b15c/v1', 'book_id': BOOK, 'source_day': D,
               'model_publication_id': model, 'previous_day': S, 'valuation_time': D + 'T00:00:00Z' if valuation_time is None else valuation_time, 'day_mode': 'open',
               'currency': currency, 'cost_config': deepcopy(COST if cost is None else cost), 'instruments': instruments,
               'actions_source_id': actions['source_id'], 'actions_source_digest': actions['content_digest']}
    return {'source_id': source_id, 'book_id': BOOK, 'source_day': D, 'model_publication_id': model, 'producer_id': 'owned-producer',
            'policy_version': 'owned-policy/v1', 'policy_revision': 1, 'source_version': 'market-' + source_id,
            'content_digest': h(payload), 'payload': payload, 'as_of': D + 'T00:00:00+00:00',
            'valid_until': '2026-09-27T00:00:00+00:00', 'created_at': D + 'T00:00:02+00:00'}


def assemble(p):
    empty = actions_row(ACT_M, [], valuation_time=p.vt_act)
    applied = actions_row(p.act_d, deepcopy(p.events), valuation_time=p.vt_act) if p.events else None
    m = market_row(M_ID, FIN, None, deepcopy(p.m_instruments), empty, p.cost_m, p.vt_m, p.cur_m)
    a = market_row(A_ID, V1, P2, deepcopy(p.a_instruments), applied or empty, p.cost_a, p.vt_a, p.cur_a)
    f_payload = {'schema_version': 'qt-equity-desk-finalization/v1', 'finalization_id': FID, 'decision_id': p.fdec if p.fpdec is None else p.fpdec,
                 'market_source_id': M_ID, 'market_source_digest': m['content_digest'],
                 'actions_source_id': empty['source_id'], 'actions_source_digest': empty['content_digest']}
    finalization = {'finalization_id': FID, 'decision_id': p.fdec, 'market_source_id': M_ID, 'book_id': BOOK, 'source_day': S,
                    'valuation_day': D, 'producer_id': 'owned-producer', 'policy_version': 'owned-policy/v1',
                    'source_version': 'qt-finalization/' + FID, 'policy_revision': 1, 'input_digest': '1' * 64,
                    'output_digest': '2' * 64, 'content_digest': h(f_payload), 'payload': f_payload}
    anchor_payload = {'schema_version': 'qt-equity-finalized-accounting/v2', 'calculation_version': 'qt-equity-main08b15c/v1',
                      'book_id': BOOK, 'source_day': S, 'currency': 'USD', 'policy_revision': 1,
                      'previous_positions': p.positions, 'previous_totals': [], 'finalization_id': FID,
                      'finalization_digest': finalization['content_digest']}
    anchor = {'source_id': 'qt-finalization/' + FID, 'book_id': BOOK, 'source_day': S, 'producer_id': 'owned-producer',
              'policy_version': 'owned-policy/v1', 'source_version': 'qt-finalization/' + FID,
              'content_digest': h(anchor_payload), 'payload': anchor_payload}
    reference = {'schema_version': 'qt-equity-model-prior/v1', 'mode': 'verified_desk_prior', 'book_id': BOOK, 'source_day': S,
                 'valuation_day': D, 'decision_id': p.sid, 'finalization_id': FID, 'finalization_digest': finalization['content_digest'],
                 'finalization_source_id': anchor['source_id'], 'finalization_source_digest': anchor['content_digest'],
                 'model_publication_id': P1, 'model_seed_digest': 'e' * 64, 'accounting_input_id': '20000000-0000-4000-8000-000000000001',
                 'accounting_input_digest': '1' * 64, 'attempt_id': '20000000-0000-4000-8000-000000000002',
                 'observation_id': '20000000-0000-4000-8000-000000000001', 'observation_digest': '2' * 64,
                 'results_digest': '3' * 64, 'basis_positions': deepcopy(p.positions), 'action_admission': 'action_free_only'}
    binding = {'publication_id': P2, 'book_id': BOOK, 'source_day': D, 'strategy_id': ENGINE, 'decision_id': p.sid,
               'finalization_id': FID, 'finalization_digest': finalization['content_digest'],
               'finalization_source_id': anchor['source_id'], 'finalization_source_digest': anchor['content_digest'],
               'actions_source_id': None, 'actions_source_digest': None}
    if p.v2:
        source = applied or empty
        frame = {'schema_version': 'qt-equity-model-action-frame/v1',
                 'owner': {'portfolio_id': BOOK, 'strategy_id': ENGINE, 'strategy_name': OWNER_NAME, 'source_day': S, 'valuation_day': D},
                 'original_action_count': 0, 'original_action_digest': h([]), 'successor_action_count': len(source['payload']['events']),
                 'successor_action_digest': h(source['payload']['events']), 'original_basis_positions': deepcopy(p.positions),
                 'derived_model_basis_positions': [], 'actions_source': deepcopy(source),
                 'policy_identity': {'book_id': BOOK, 'purpose': 'execution', 'version': 1, 'producer_id': 'owned-producer',
                                     'policy_version': 'owned-policy/v1'},
                 'raw_capture': {'bars': [], 'aliases': [], 'terminations': [], 'restating_metadata': []}, 'adjustments': []}
        reference.update(schema_version='qt-equity-model-prior/v2', action_admission='proved_action_adjusted_prior',
                         action_frame=frame, action_frame_digest=h(frame))
        binding.update(actions_source_id=source['source_id'], actions_source_digest=source['content_digest'])
    binding.update(replay_reference=reference, replay_reference_digest=h(reference), created_at=D + 'T00:00:03+00:00')
    return {'decision': {'decision_id': D_DEC, 'book_id': BOOK, 'source_day': D, 'model_publication_id': P2},
            'prior_decision': {'decision_id': p.sid, 'book_id': BOOK, 'source_day': S, 'model_publication_id': P1},
            'finalization_market': m, 'input_market': a, 'finalization': finalization, 'anchor': anchor, 'binding': binding,
            'actions_row': applied or empty, 'candidate_action_sources': [p.act_d] if applied else []}


def refused(inputs):
    with pytest.raises(ValueError) as caught:
        proof.validate_qt_equity_verified_prior_continuation(inputs)
    assert str(caught.value) == CODE
    assert proof.qt_equity_prior_continuation_holds(inputs) is False


def accepted(inputs):
    assert proof.validate_qt_equity_verified_prior_continuation(inputs) is None
    assert proof.qt_equity_prior_continuation_holds(inputs) is True


def rehash(row):
    row['content_digest'] = h(row['payload'])
    return row


def reseal_binding(inputs):
    inputs['binding']['replay_reference_digest'] = h(inputs['binding']['replay_reference'])
    return inputs


# ---- positive ----------------------------------------------------------------------------

@pytest.mark.parametrize('action', [None, 'split', 'adr', 'dividend', 'both'])
def test_continuation_is_proved_for_no_action_split_adr_dividend_and_both(action):
    accepted(assemble(parts(action)))


def test_a_new_symbol_on_d_is_a_proven_open():
    accepted(assemble(parts(new_symbol=True)))
    accepted(assemble(parts('split', new_symbol=True)))


def test_a_v2_reference_over_the_empty_row_is_accepted():
    accepted(assemble(parts(v2=True)))


def test_a_second_untouched_symbol_beside_an_action_symbol_must_stay_byte_equal():
    p = parts('split')
    p.positions.append(position('OTH', '5', '20'))
    p.m_instruments.append(instrument('OTH', '21'))
    p.a_instruments.append(instrument('OTH', '21'))
    accepted(assemble(p))
    p.a_instruments[1]['mark']['price_model_number'] = '22'
    refused(assemble(p))


def test_sql_representations_are_compared_by_meaning():
    inputs = assemble(parts('split'))
    for name in ('decision', 'prior_decision'):
        row = inputs[name]
        row['decision_id'], row['model_publication_id'] = UUID(row['decision_id']), UUID(row['model_publication_id'])
        row['source_day'] = date.fromisoformat(row['source_day'])
    for name in ('finalization_market', 'input_market'):
        row = inputs[name]
        row['source_id'] = UUID(row['source_id'])
        row['source_day'] = date.fromisoformat(row['source_day'])
        row['model_publication_id'] = None if row['model_publication_id'] is None else UUID(row['model_publication_id'])
        for field in ('as_of', 'valid_until', 'created_at'):
            row[field] = datetime.fromisoformat(row[field])
    f = inputs['finalization']
    f.update(finalization_id=UUID(f['finalization_id']), decision_id=UUID(f['decision_id']), market_source_id=UUID(f['market_source_id']),
             source_day=date.fromisoformat(f['source_day']), valuation_day=date.fromisoformat(f['valuation_day']))
    inputs['anchor']['source_day'] = date.fromisoformat(inputs['anchor']['source_day'])
    b = inputs['binding']
    b.update(publication_id=UUID(b['publication_id']), decision_id=UUID(b['decision_id']), finalization_id=UUID(b['finalization_id']),
             source_day=date.fromisoformat(b['source_day']), created_at=datetime.now(timezone.utc))
    row = inputs['actions_row']
    row['source_day'] = date.fromisoformat(row['source_day'])
    row['created_at'] = datetime(2026, 9, 26, 0, 0, 1, 1, tzinfo=timezone.utc)  # == 00:00:01.000001+00:00 in the frame copy
    accepted(inputs)
    row['created_at'] = datetime(2026, 9, 26, 0, 0, 1, 2, tzinfo=timezone.utc)
    refused(inputs)


# ---- a) the binding ------------------------------------------------------------------------

def test_a_missing_binding_refuses():
    inputs = assemble(parts())
    inputs['binding'] = None
    refused(inputs)


@pytest.mark.parametrize('field,value', [
    ('publication_id', '50000000-0000-4000-8000-0000000000ff'), ('book_id', 'OTHER'), ('source_day', S),
    ('strategy_id', 'LIVE_FUTURES'), ('decision_id', D_DEC), ('finalization_id', '40000000-0000-4000-8000-0000000000ff'),
    ('finalization_source_id', 'qt-finalization/40000000-0000-4000-8000-0000000000ff')])
def test_a_foreign_or_other_binding_refuses(field, value):
    inputs = assemble(parts())
    inputs['binding'][field] = value
    refused(inputs)


def test_the_binding_has_exactly_its_fourteen_columns():
    inputs = assemble(parts())
    inputs['binding']['surprise'] = 1
    refused(inputs)
    inputs = assemble(parts())
    del inputs['binding']['created_at']
    refused(inputs)


@pytest.mark.parametrize('field', ['finalization_digest', 'finalization_source_digest', 'replay_reference_digest'])
def test_each_binding_digest_mismatch_refuses(field):
    inputs = assemble(parts())
    inputs['binding'][field] = '0' * 64
    refused(inputs)


def test_a_binding_digest_that_is_not_hex_refuses():
    inputs = assemble(parts())
    inputs['binding']['finalization_digest'] = 'G' * 64
    refused(inputs)


def test_the_binding_must_name_the_finalization_that_is_the_anchor():
    inputs = assemble(parts())
    inputs['finalization']['finalization_id'] = '40000000-0000-4000-8000-0000000000ff'
    refused(inputs)
    inputs = assemble(parts())
    inputs['finalization']['content_digest'] = '9' * 64
    refused(inputs)
    inputs = assemble(parts())
    inputs['anchor']['payload']['finalization_id'] = '40000000-0000-4000-8000-0000000000ff'
    rehash(inputs['anchor'])
    refused(inputs)


@pytest.mark.parametrize('field,value', [
    ('mode', 'seed'), ('book_id', 'OTHER'), ('source_day', '2026-09-24'), ('valuation_day', '2026-09-27'),
    ('decision_id', D_DEC), ('finalization_id', '40000000-0000-4000-8000-0000000000ff'), ('finalization_digest', '0' * 64),
    ('finalization_source_id', 'qt-finalization/x'), ('finalization_source_digest', '0' * 64),
    ('model_publication_id', P2), ('action_admission', 'proved_action_adjusted_prior'), ('schema_version', 'qt-equity-model-prior/v9')])
def test_replay_scope_mismatch_refuses_even_when_the_reference_digest_is_recomputed(field, value):
    inputs = assemble(parts())
    inputs['binding']['replay_reference'][field] = value
    refused(reseal_binding(inputs))


def test_the_replay_reference_has_exactly_the_engines_key_set():
    inputs = assemble(parts())
    inputs['binding']['replay_reference']['extra'] = 1
    refused(reseal_binding(inputs))
    inputs = assemble(parts('split'))
    del inputs['binding']['replay_reference']['action_frame_digest']
    refused(reseal_binding(inputs))


def test_the_replay_basis_must_be_the_anchors_basis():
    inputs = assemble(parts())
    inputs['binding']['replay_reference']['basis_positions'][0]['quantity_exact'] = '11'
    refused(reseal_binding(inputs))
    inputs = assemble(parts())
    inputs['anchor']['payload']['previous_positions'][0]['average_price_exact'] = '51'
    rehash(inputs['anchor'])
    refused(inputs)


def test_a_v1_reference_may_not_claim_an_applied_actions_row():
    inputs = assemble(parts())
    inputs['binding'].update(actions_source_id=ACT_M, actions_source_digest=inputs['actions_row']['content_digest'])
    refused(inputs)


def test_a_v2_reference_must_carry_its_frame_and_actions_columns():
    inputs = assemble(parts('split'))
    inputs['binding']['actions_source_id'] = inputs['binding']['actions_source_digest'] = None
    refused(inputs)
    inputs = assemble(parts('split'))
    inputs['binding']['replay_reference']['action_frame_digest'] = '0' * 64
    refused(reseal_binding(inputs))


@pytest.mark.parametrize('damage', ['owner_day', 'original_basis', 'count', 'digest_of_events', 'schema'])
def test_the_action_frame_is_bound_to_the_scope_the_basis_and_its_events(damage):
    inputs = assemble(parts('split'))
    frame = inputs['binding']['replay_reference']['action_frame']
    if damage == 'owner_day':
        frame['owner']['valuation_day'] = '2026-09-27'
    elif damage == 'original_basis':
        frame['original_basis_positions'][0]['quantity_exact'] = '11'
    elif damage == 'count':
        frame['successor_action_count'] = 2
    elif damage == 'digest_of_events':
        frame['successor_action_digest'] = '0' * 64
    else:
        frame['schema_version'] = 'qt-equity-model-action-frame/v2'
    inputs['binding']['replay_reference']['action_frame_digest'] = h(frame)
    refused(reseal_binding(inputs))


# ---- c) the actions ------------------------------------------------------------------------

def test_a_swapped_actions_row_refuses():
    inputs = assemble(parts('split'))
    other = actions_row('qt-actions/D-other', [event('SYN', 'SPLIT', '3')])
    inputs['input_market']['payload'].update(actions_source_id=other['source_id'], actions_source_digest=other['content_digest'])
    rehash(inputs['input_market'])
    inputs['actions_row'] = other
    inputs['candidate_action_sources'] = [other['source_id']]
    refused(inputs)


def test_the_loaded_row_must_be_the_row_the_market_names():
    inputs = assemble(parts('split'))
    inputs['actions_row'] = actions_row(ACT_M, [])
    refused(inputs)


def test_a_changed_actions_row_refuses_even_when_its_own_digest_is_recomputed():
    inputs = assemble(parts('split'))
    row = inputs['actions_row']
    row['payload']['events'][0]['value_model_number'] = '4'
    rehash(row)
    inputs['input_market']['payload']['actions_source_digest'] = row['content_digest']
    rehash(inputs['input_market'])
    refused(inputs)


def test_a_tampered_actions_payload_without_a_new_digest_refuses():
    inputs = assemble(parts('split'))
    inputs['actions_row']['payload']['events'][0]['value_model_number'] = '4'
    refused(inputs)


@pytest.mark.parametrize('field,value', [('created_at', '2026-09-26T05:00:00.000000+00:00'), ('producer_id', 'other'),
    ('policy_version', 'other/v2'), ('source_version', 'other'), ('policy_revision', 2)])
def test_the_whole_actions_row_is_compared_not_only_the_payload(field, value):
    inputs = assemble(parts('split'))
    inputs['actions_row'][field] = value
    refused(inputs)


def test_a_late_action_row_after_a_no_action_run_refuses():
    inputs = assemble(parts())
    inputs['candidate_action_sources'] = ['qt-actions/late']
    refused(inputs)
    inputs = assemble(parts())
    late = actions_row('qt-actions/late', [event('SYN', 'SPLIT', '2')])
    inputs['input_market']['payload'].update(actions_source_id=late['source_id'], actions_source_digest=late['content_digest'])
    rehash(inputs['input_market'])
    inputs['actions_row'] = late
    inputs['candidate_action_sources'] = [late['source_id']]
    refused(inputs)  # the MODEL ran action-free (v1): a nonempty row is not what it applied


def test_a_second_candidate_row_refuses_even_when_the_applied_row_is_named():
    inputs = assemble(parts('split'))
    inputs['candidate_action_sources'] = [ACT_D, 'qt-actions/second']
    refused(inputs)


def test_the_applied_row_must_itself_be_the_only_candidate():
    inputs = assemble(parts('split'))
    inputs['candidate_action_sources'] = []
    refused(inputs)
    inputs['candidate_action_sources'] = ['qt-actions/other']
    refused(inputs)
    inputs['candidate_action_sources'] = [ACT_D, ACT_D]
    refused(inputs)


def test_a_missing_or_malformed_candidate_set_refuses():
    for bad in (None, 'not-a-list', [7], [''], ['x'] * 4097):
        inputs = assemble(parts())
        inputs['candidate_action_sources'] = bad
        refused(inputs)


def test_the_actions_row_must_be_for_d_and_the_same_policy():
    for field, value in (('book_id', 'OTHER'), ('source_day', '2026-09-27'), ('policy_revision', 2), ('producer_id', 'other'),
                         ('purpose', 'basis')):
        inputs = assemble(parts())
        inputs['actions_row'][field] = value
        refused(inputs)


def test_no_action_needs_ms_own_empty_actions_source():
    inputs = assemble(parts())
    other = actions_row('qt-actions/other-empty', [])
    inputs['input_market']['payload'].update(actions_source_id=other['source_id'], actions_source_digest=other['content_digest'])
    rehash(inputs['input_market'])
    inputs['actions_row'] = other
    refused(inputs)


@pytest.mark.parametrize('spelling', ['2026-09-26T02:00:01.000001+02:00', '2026-09-25T19:00:01.000001-05:00',
    '2026-09-26 00:00:01.000001Z', '2026-09-26T00:00:01.000001+00', '2026-09-26T02:00:01.000001+0200',
    '2026-09-26T05:30:01.000001+05:30', '2026-09-26T00:00:01.000001Z'])
def test_the_applied_rows_created_at_is_the_same_instant_in_any_offset_spelling(spelling):
    inputs = assemble(parts('split'))
    inputs['actions_row']['created_at'] = spelling
    accepted(inputs)


@pytest.mark.parametrize('spelling', ['2026-09-26T00:00:01.000002+00:00', '2026-09-26T02:00:01.000001+00:00',
    '2026-09-26T00:00:01.000001', '2026-09-26T24:00:00Z', '2026-09-26T00:00:01.0000011Z', 'yesterday', 7, None,
    '2026-13-26T00:00:01.000001Z', '2026-09-26T00:00:01.000001+24:00'])
def test_a_different_or_unparseable_created_at_refuses(spelling):
    inputs = assemble(parts('split'))
    inputs['actions_row']['created_at'] = spelling
    refused(inputs)


@pytest.mark.parametrize('spelling', ['2026-09-25T24:00:01.000001Z', '2026-09-25T23:60:01.000001Z', '2026-09-25T23:59:60.000001Z',
    '2026-09-27T00:00:01.000001+24:00', '2026-09-26T00:00:01.000001+00:60'])
def test_out_of_range_clock_or_offset_fields_are_refused_even_when_they_would_name_the_same_instant(spelling):
    inputs = assemble(parts('split'))
    inputs['actions_row']['created_at'] = spelling
    refused(inputs)


def test_an_extra_key_on_the_loaded_actions_row_is_not_the_captured_row():
    inputs = assemble(parts('split'))
    inputs['actions_row']['surprise'] = 1
    refused(inputs)


def test_an_offset_created_at_never_relaxes_the_rest_of_the_row():
    inputs = assemble(parts('split'))
    inputs['actions_row']['created_at'] = '2026-09-26T02:00:01.000001+02:00'
    inputs['actions_row']['source_version'] = 'other'
    refused(inputs)


# ---- d) the marks --------------------------------------------------------------------------

def test_an_unrestated_mark_refuses():
    for action in ('split', 'dividend'):
        p = parts(action)
        p.a_instruments = [instrument('SYN', '90', 'adjusted-2')]
        refused(assemble(p))
        p.a_instruments = [instrument('SYN', '90', 'adjusted-1')]
        refused(assemble(p))


def test_a_wrongly_restated_mark_refuses_by_one_unit_in_the_last_place():
    p = parts('split')
    p.a_instruments = [instrument('SYN', '44.99999999', 'adjusted-2')]
    refused(assemble(p))
    p = parts('dividend')
    p.a_instruments = [instrument('SYN', '89.10891090', 'adjusted-2')]  # right value, non-canonical spelling
    refused(assemble(p))
    p.a_instruments = [instrument('SYN', '89.1089109', 'adjusted-2')]
    refused(assemble(p))
    p = parts('dividend')
    p.a_instruments = [instrument('SYN', SPLIT_2_OF_90, 'adjusted-2')]
    refused(assemble(p))


def test_the_restated_price_is_compared_by_its_decimal_spelling():
    p = parts('split')
    p.a_instruments = [instrument('SYN', '45.0', 'adjusted-2')]
    refused(assemble(p))
    p.a_instruments = [instrument('SYN', '4.5e1', 'adjusted-2')]
    refused(assemble(p))


def test_the_event_order_split_then_dividend_is_observable_and_enforced():
    p = parts('both')
    p.a_instruments = [instrument('SYN', DIVIDEND_THEN_SPLIT_3_OF_37_13, 'adjusted-3')]
    refused(assemble(p))
    p = parts('both')
    p.events.reverse()
    p.events[0]['frame_before'], p.events[0]['frame_after'] = 'adjusted-1', 'adjusted-2'
    p.events[1]['frame_before'], p.events[1]['frame_after'] = 'adjusted-2', 'adjusted-3'
    p.a_instruments = [instrument('SYN', DIVIDEND_THEN_SPLIT_3_OF_37_13, 'adjusted-3')]
    refused(assemble(p))  # the MODEL never applies dividend before split


def test_the_first_step_reads_the_mark_as_a_double_and_only_the_quotient_is_screened():
    # 10.123456789 / 2 = 5.0617283945: screening the mark first would give 5.0617284, the MODEL's order gives 5.06172839
    p = parts('split')
    p.m_instruments = [instrument('SYN', '10.123456789')]
    p.a_instruments = [instrument('SYN', '5.06172839', 'adjusted-2')]
    accepted(assemble(p))
    p.a_instruments = [instrument('SYN', '5.0617284', 'adjusted-2')]
    refused(assemble(p))


def test_the_reference_is_restated_like_the_mark_and_the_two_must_agree():
    p = parts('split')
    p.a_instruments[0]['reference']['price_model_number'] = '90'
    refused(assemble(p))
    p = parts('split')
    p.a_instruments[0]['reference']['price_frame_id'] = 'adjusted-1'
    refused(assemble(p))


def test_the_restated_frame_must_be_the_events_frame_after():
    p = parts('split')
    p.a_instruments = [instrument('SYN', SPLIT_2_OF_90, 'adjusted-9')]
    refused(assemble(p))


def test_only_the_price_and_frame_of_an_action_symbol_may_move():
    p = parts('split')
    p.a_instruments[0]['mark']['source_id'] = 'other-close'
    refused(assemble(p))
    p = parts('split')
    p.a_instruments[0]['cost_parameters']['tick_size'] = '0.05'
    refused(assemble(p))
    p = parts('split')
    p.a_instruments[0]['mark']['source_digest'] = 'a' * 64
    refused(assemble(p))


def test_an_untouched_symbol_may_not_change_at_all():
    for change in (lambda i: i['mark'].update(price_model_number='91'), lambda i: i['reference'].update(source_digest='0' * 64),
                   lambda i: i['cost_evidence'].update(source_id='other'), lambda i: i['cost_parameters'].update(tick_size='1')):
        p = parts()
        change(p.a_instruments[0])
        refused(assemble(p))


def test_the_marks_are_previous_close_priced_in_one_frame_with_sourced_digests():
    for change in (lambda i: i['mark'].update(date=D), lambda i: i['reference'].update(price_frame_id='adjusted-2'),
                   lambda i: i['mark'].update(source_digest='xyz'), lambda i: i['mark'].update(price_model_number='0'),
                   lambda i: i['mark'].update(price_model_number='nan'), lambda i: i['reference'].update(price_model_number='1e'),
                   lambda i: i['cost_evidence'].update(date=D), lambda i: i.update(asset_type='FUT'),
                   lambda i: i.pop('cost_parameters')):
        p = parts()
        change(p.m_instruments[0])
        change(p.a_instruments[0])
        refused(assemble(p))


def test_a_held_symbol_missing_from_a_refuses():
    p = parts()
    p.a_instruments = []
    refused(assemble(p))


def test_an_event_that_breaks_the_models_screening_refuses():
    for change in (lambda e: e.update(frame_before='adjusted-7'), lambda e: e.update(frame_after='adjusted-1'),
                   lambda e: e.update(ex_date=S), lambda e: e.update(type='SPINOFF'), lambda e: e.update(value_model_number='1'),
                   lambda e: e.update(value_model_number='0'), lambda e: e.update(value_model_number='nan'),
                   lambda e: e.update(raw_close_model_number='100'), lambda e: e.update(eligible_quantity_exact='10'),
                   lambda e: e['key'].update(symbol='GHOST'), lambda e: e['key'].update(date=S),
                   lambda e: e['key'].update(portfolio_type='system'), lambda e: e['key'].update(strategy_name='OTHER'),
                   lambda e: e.pop('basis_provenance')):
        p = parts('split')
        change(p.events[0])
        refused(assemble(p))


def test_a_dividend_needs_a_positive_close_and_an_eligible_quantity():
    for close in (None, '0', '-1', 'x'):
        p = parts('dividend')
        p.events[0]['raw_close_model_number'] = close
        refused(assemble(p))
    p = parts('dividend')
    p.events[0]['eligible_quantity_exact'] = None
    refused(assemble(p))


def test_a_duplicate_or_misordered_event_refuses():
    p = parts('both')
    p.events.reverse()
    refused(assemble(p))
    p = parts('split')
    p.events.append(deepcopy(p.events[0]))
    refused(assemble(p))


def test_an_action_on_a_symbol_in_m_that_is_not_held_refuses():
    p = parts('split')
    p.positions = [position('OTH', '5', '20')]
    refused(assemble(p))


# ---- new symbols (spec default 6) -------------------------------------------------------------------

def test_a_new_symbol_that_was_held_is_not_an_open():
    p = parts(new_symbol=True)
    p.positions.append(position('NEW', '0', '12'))  # a zero row still counts as held
    refused(assemble(p))


def test_a_new_symbol_with_a_d_action_refuses():
    p = parts('split', new_symbol=True)
    p.events.append(event('NEW', 'SPLIT', '2', after='adjusted-2'))
    refused(assemble(p))


def test_a_new_symbol_priced_on_d_or_from_two_frames_or_not_an_equity_refuses():
    for change in (lambda i: i['mark'].update(date=D), lambda i: i['reference'].update(date=D),
                   lambda i: i['reference'].update(price_frame_id='other-frame'), lambda i: i['cost_evidence'].update(date=D),
                   lambda i: i.update(asset_type='FUT'), lambda i: i['mark'].update(price_model_number='inf')):
        p = parts(new_symbol=True)
        change(p.a_instruments[1])
        refused(assemble(p))


def test_a_new_symbol_shares_ms_single_source_id_namespace():
    for change in (lambda i: i['mark'].update(source_id='vendor-x/NEW'), lambda i: i['reference'].update(source_id='vendor-x/NEW'),
                   lambda i: i['mark'].update(source_id='owned-S-close'), lambda i: i['mark'].update(source_id='/NEW'),
                   lambda i: i['reference'].update(source_id='')):
        p = parts(new_symbol=True)
        change(p.a_instruments[1])
        refused(assemble(p))
    p = parts(new_symbol=True)
    p.a_instruments[1]['mark']['source_id'] = 'owned-S-close/deeper/NEW'  # the namespace is the text before the LAST slash
    refused(assemble(p))
    p = parts(new_symbol=True)
    p.a_instruments[1]['mark']['source_id'] = 'owned-S-close/other-id'  # any id inside the namespace is fine
    accepted(assemble(p))


def test_a_leading_slash_is_no_namespace():
    p = parts(new_symbol=True)
    for rows in (p.m_instruments, p.a_instruments):
        rows[0]['mark']['source_id'] = rows[0]['reference']['source_id'] = '/SYN'
    p.a_instruments[1]['mark']['source_id'] = p.a_instruments[1]['reference']['source_id'] = '/NEW'
    refused(assemble(p))


def test_a_new_symbol_needs_m_to_have_exactly_one_namespace_and_no_open_consults_it():
    def two_namespaces(p):
        p.positions.append(position('OTH', '5', '20'))
        for rows in (p.m_instruments, p.a_instruments):
            rows.append(instrument('OTH', '21', source='second-close/OTH'))
    for namespace in ('owned-S-close', 'second-close'):   # whichever namespace the open picks, M has two
        p = parts(new_symbol=True)
        two_namespaces(p)
        p.a_instruments[-2]['mark']['source_id'] = p.a_instruments[-2]['reference']['source_id'] = namespace + '/NEW'
        refused(assemble(p))
    p = parts()
    two_namespaces(p)
    accepted(assemble(p))                     # no new symbol: the namespaces are not consulted
    for action in (None, 'split', 'dividend'):   # M's ids have no namespace at all: nothing consults them without an open
        p = parts(action)
        for rows in (p.m_instruments, p.a_instruments):
            rows[0]['mark']['source_id'] = rows[0]['reference']['source_id'] = 'no-slash-at-all'
        accepted(assemble(p))
    p = parts()
    for rows in (p.m_instruments, p.a_instruments):
        rows[0]['mark']['source_id'] = rows[0]['reference']['source_id'] = '/SYN'
    accepted(assemble(p))
    for action in (None, 'split'):              # ...but an open needs M to have one shared namespace
        p = parts(action, new_symbol=True)
        for rows in (p.m_instruments, p.a_instruments[:1]):
            rows[0]['mark']['source_id'] = rows[0]['reference']['source_id'] = 'no-slash-at-all'
        refused(assemble(p))


def test_a_duplicate_symbol_in_a_refuses():
    p = parts(new_symbol=True)
    p.a_instruments.append(deepcopy(p.a_instruments[1]))
    refused(assemble(p))


# ---- b) the valuation fields, policy and metadata -------------------------------------------------------

@pytest.mark.parametrize('field,value', [
    ('valuation_time', D + 'T01:00:00Z'), ('previous_day', '2026-09-24'), ('day_mode', 'close'), ('currency', 'EUR'),
    ('calculation_version', 'qt-equity-main08b15c/v2'), ('book_id', 'OTHER'), ('source_day', '2026-09-27'),
    ('cost_config', {**COST, 'min_adv': '1'}), ('cost_config', {**COST, 'extra': '1'})])
def test_a_changed_valuation_field_refuses(field, value):
    inputs = assemble(parts())
    inputs['input_market']['payload'][field] = value
    rehash(inputs['input_market'])
    refused(inputs)


@pytest.mark.parametrize('field,value', [('policy_revision', 2), ('producer_id', 'other'), ('policy_version', 'owned-policy/v2'),
                                         ('book_id', 'OTHER'), ('source_day', '2026-09-27')])
def test_policy_and_metadata_mismatch_between_the_rows_refuses(field, value):
    inputs = assemble(parts())
    inputs['input_market'][field] = value
    refused(inputs)


def test_policy_and_metadata_of_f_and_the_anchor_follow_a():
    inputs = assemble(parts())
    inputs['finalization']['policy_revision'] = 2
    refused(inputs)
    inputs = assemble(parts())
    inputs['anchor']['producer_id'] = 'other'
    refused(inputs)
    inputs = assemble(parts())
    inputs['anchor']['payload']['policy_revision'] = 2
    rehash(inputs['anchor'])
    refused(inputs)


def test_extra_or_missing_payload_keys_refuse():
    inputs = assemble(parts())
    inputs['input_market']['payload']['surprise'] = 1
    rehash(inputs['input_market'])
    refused(inputs)
    inputs = assemble(parts())
    del inputs['finalization_market']['payload']['cost_config']
    rehash(inputs['finalization_market'])
    refused(inputs)


def test_every_sealed_row_refuses_a_payload_that_no_longer_matches_its_digest():
    for name in ('finalization_market', 'input_market', 'finalization', 'anchor', 'actions_row'):
        inputs = assemble(parts('split'))
        inputs[name]['payload']['zz'] = 'changed'
        refused(inputs)


def test_the_schemas_and_the_model_of_the_two_markets_are_fixed():
    inputs = assemble(parts())
    inputs['finalization_market']['payload']['schema_version'] = V1
    rehash(inputs['finalization_market'])
    refused(inputs)
    inputs = assemble(parts())
    inputs['input_market']['payload']['schema_version'] = FIN
    rehash(inputs['input_market'])
    refused(inputs)
    inputs = assemble(parts())
    inputs['finalization_market']['model_publication_id'] = P2
    inputs['finalization_market']['payload']['model_publication_id'] = P2
    rehash(inputs['finalization_market'])
    refused(inputs)
    inputs = assemble(parts())
    inputs['finalization_market']['payload']['model_publication_id'] = P2  # payload only: the row column stays null
    rehash(inputs['finalization_market'])
    refused(inputs)
    inputs = assemble(parts())
    inputs['input_market']['model_publication_id'] = P1
    inputs['input_market']['payload']['model_publication_id'] = P1
    rehash(inputs['input_market'])
    refused(inputs)
    inputs = assemble(parts())
    inputs['input_market']['model_publication_id'] = None
    refused(inputs)


def test_the_same_market_is_not_a_continuation():
    inputs = assemble(parts())
    inputs['input_market'] = deepcopy(inputs['finalization_market'])
    refused(inputs)
    inputs = assemble(parts())
    inputs['input_market']['source_id'] = inputs['finalization_market']['source_id']
    refused(inputs)


def test_the_chain_of_decisions_and_days_is_checked():
    for name, field, value in (('decision', 'book_id', 'OTHER'), ('prior_decision', 'book_id', 'OTHER'),
                               ('prior_decision', 'source_day', D), ('decision', 'source_day', S),
                               ('prior_decision', 'decision_id', D_DEC), ('decision', 'model_publication_id', P1)):
        inputs = assemble(parts())
        inputs[name][field] = value
        refused(inputs)
    inputs = assemble(parts())
    inputs['finalization']['valuation_day'] = '2026-09-27'
    refused(inputs)
    inputs = assemble(parts())
    inputs['finalization']['market_source_id'] = A_ID
    refused(inputs)
    inputs = assemble(parts())
    inputs['finalization']['payload']['market_source_digest'] = '0' * 64
    rehash(inputs['finalization'])
    refused(inputs)
    inputs = assemble(parts())
    inputs['finalization']['payload']['actions_source_id'] = 'qt-actions/other'
    rehash(inputs['finalization'])
    refused(inputs)
    inputs = assemble(parts())
    inputs['anchor']['source_id'] = 'qt-finalization/40000000-0000-4000-8000-0000000000ff'
    refused(inputs)
    inputs = assemble(parts())
    inputs['anchor']['payload']['schema_version'] = 'qt-equity-finalized-accounting-empty-owner/v3'
    rehash(inputs['anchor'])
    refused(inputs)


def test_absent_or_malformed_operands_refuse_without_leaking_a_different_error():
    good = assemble(parts())
    for name in good:
        inputs = deepcopy(good)
        inputs[name] = 7 if name != 'candidate_action_sources' else 'not-a-list'
        refused(inputs)
        inputs = deepcopy(good)
        del inputs[name]
        refused(inputs)
    inputs = deepcopy(good)
    inputs['unexpected'] = 1
    refused(inputs)
    refused(None)
    refused([])


def test_inputs_are_not_mutated():
    for p in (parts('both', new_symbol=True), parts()):
        inputs = assemble(p)
        before = deepcopy(inputs)
        accepted(inputs)
        assert inputs == before


def test_the_decimal_screening_and_spelling_match_the_native_class():
    dec, text = proof._decimal8, proof._decimal8_text
    assert [text(dec(v)) for v in (45.0, 89.108910891089, 0.5, 100.0, 12.000000005, 1e-9, 123456.78901234567)] == [
        '45', '89.10891089', '0.5', '100', '12.00000001', '0', '123456.78901235']
    assert text(dec(-0.5)) == '-0.5' and text(dec(-1e-9)) == '0' and dec(-0.5) == -50000000
    for bad in (float('inf'), float('nan'), 1e11, -1e11):
        with pytest.raises((ValueError, OverflowError)):
            dec(bad)
    assert proof._decimal8_double(dec(30.333333333333332)) == 30.33333333


# ---- finalization-only market: accepted by the finalization proof's M checks only -----------------------------

def scope_args():
    """(row m, payload market, model) of a well-formed finalization-only market."""
    row = market_row(M_ID, FIN, None, [], actions_row(ACT_M, []))
    return row, row['payload'], None


def publication(day=D, publication_id=P2):
    document = {'portfolio_id': BOOK, 'source_day': day, 'publication_id': publication_id, 'system_components': []}
    document['seed_digest'] = proof.qt_digest_v1({'seed_rows': []})
    return document


def prove_scope(m, market, model, *, empty_owner=False):
    return proof._prove_market_scope(m, market, model, book=BOOK, day=S, valuation=D, empty_owner=empty_owner)


def test_the_finalization_only_market_binds_to_no_model():
    prove_scope(*scope_args())


def test_the_finalization_only_market_refuses_any_model_or_a_non_null_column():
    m, market, model = scope_args()
    with pytest.raises(ValueError):
        prove_scope(m, market, publication())  # a loaded publication is never expected
    m, market, model = scope_args()
    m['model_publication_id'] = P2
    with pytest.raises(ValueError):
        prove_scope(m, market, model)
    m, market, model = scope_args()
    market['model_publication_id'] = P2
    rehash(m)
    with pytest.raises(ValueError):
        prove_scope(m, market, model)


def test_a_null_model_is_only_allowed_for_the_finalization_only_schema():
    m = market_row(A_ID, V1, None, [], actions_row(ACT_M, []))
    with pytest.raises(ValueError):
        prove_scope(m, m['payload'], None)


def test_the_finalization_only_market_is_still_scoped_to_book_and_days():
    for field, value in (('book_id', 'OTHER'), ('source_day', S), ('previous_day', '2026-09-24')):
        m, market, model = scope_args()
        market[field] = value
        if field != 'previous_day':
            m[field] = value
        rehash(m)
        with pytest.raises(ValueError):
            prove_scope(m, market, model)


def test_the_finalization_only_row_must_agree_with_its_payload_on_book_and_day():
    for field, value in (('book_id', 'OTHER'), ('source_day', '2026-09-27')):
        m, market, model = scope_args()
        m[field] = value
        with pytest.raises(ValueError):
            prove_scope(m, market, model)
    m, market, model = scope_args()
    m['source_day'] = date.fromisoformat(D)  # psycopg2 spelling of the same day is the same day
    prove_scope(m, market, model)
    m, market, model = scope_args()
    market['book_id'] = ''
    m['book_id'] = ''
    rehash(m)
    with pytest.raises(ValueError):
        proof._prove_market_scope(m, market, None, book='', day=S, valuation=D, empty_owner=False)


def test_the_finalization_only_payload_has_exactly_the_market_key_set_with_a_json_null_model():
    m, market, model = scope_args()
    market['model_seed_digest'] = 'a' * 64
    rehash(m)
    with pytest.raises(ValueError):
        prove_scope(m, market, model)
    m, market, model = scope_args()
    del market['model_publication_id']
    rehash(m)
    with pytest.raises(ValueError):
        prove_scope(m, market, model)
    m, market, model = scope_args()
    del market['cost_config']
    rehash(m)
    with pytest.raises(ValueError):
        prove_scope(m, market, model)


def test_the_finalization_only_row_needs_its_null_column_and_its_seal():
    m, market, model = scope_args()
    del m['model_publication_id']
    with pytest.raises(ValueError):
        prove_scope(m, market, model)
    m, market, model = scope_args()
    market['currency'] = 'USD '  # payload changed, row digest not recomputed
    with pytest.raises(ValueError):
        prove_scope(m, market, model)
    m, market, model = scope_args()
    m['source_version'] = ' '
    with pytest.raises(ValueError):
        prove_scope(m, market, model)


def test_the_empty_owner_path_never_accepts_the_finalization_only_schema():
    m, market, model = scope_args()
    with pytest.raises(ValueError):
        prove_scope(m, market, model, empty_owner=True)


def test_the_v1_market_scope_is_unchanged():
    m = market_row(A_ID, V1, P2, [], actions_row(ACT_M, []))
    market = m['payload']
    prove_scope(m, market, publication())
    with pytest.raises(ValueError):
        prove_scope(m, market, None)
    market['model_publication_id'] = P1
    rehash(m)
    with pytest.raises(ValueError):
        prove_scope(m, market, publication())
    market['model_publication_id'] = P2
    rehash(m)
    bad = publication()
    bad['seed_digest'] = '0' * 64
    with pytest.raises(ValueError):
        prove_scope(m, market, bad)
    with pytest.raises(ValueError):
        prove_scope(m, market, publication(day=S))


def test_the_finalization_schema_constant_is_the_contract_string():
    assert proof.FINALIZATION_MARKET_SCHEMA == FIN


# ---- D accounting must still refuse the finalization-only market ---------------------------------------------------

def d_accounting(schema):
    decision = {'decision_id': D_DEC, 'book_id': BOOK, 'source_day': D, 'model_publication_id': P2}
    market = market_row(A_ID, schema, P2, [], actions_row(ACT_M, []))
    anchor_payload = {'schema_version': 'qt-equity-finalized-accounting/v1', 'calculation_version': 'qt-equity-main08b15c/v1',
                      'book_id': BOOK, 'source_day': S, 'currency': 'USD', 'policy_revision': 1, 'previous_positions': [],
                      'previous_totals': []}
    anchor = {'source_id': 'qt-finalization/' + FID, 'source_version': 'qt-finalization/' + FID, 'book_id': BOOK, 'source_day': S,
              'producer_id': 'owned-producer', 'policy_version': 'owned-policy/v1', 'content_digest': h(anchor_payload),
              'payload': anchor_payload}
    input_payload = {'schema_version': 'qt-equity-accounting-input/v1'}
    inputs = {'input_id': A_ID, 'decision_id': D_DEC, 'source_version': 'qt-input/' + A_ID, 'producer_id': 'owned-producer',
              'policy_version': 'owned-policy/v1', 'content_digest': h(input_payload), 'payload': input_payload,
              'as_of': market['as_of'], 'valid_until': market['valid_until'], 'created_at': market['created_at']}
    sources = {'market_row': market, 'model_publication': None, 'actions_row': actions_row(ACT_M, []), 'basis_rows': [],
               'evaluation_snapshot': None}
    return {'input_row': inputs, 'finalization_row': anchor, 'equity_sources': sources}, decision


def test_d_accounting_refuses_the_finalization_only_market_before_any_timing_or_source_work(monkeypatch):
    reached = []
    real = core._sql_time
    monkeypatch.setattr(core, '_sql_time', lambda value: reached.append(value) or real(value))
    for schema, expect_reached in ((FIN, False), (V1, True)):
        del reached[:]
        accounting, decision = d_accounting(schema)
        with pytest.raises(ValueError):
            core._source_input(accounting, decision, [])
        assert bool(reached) is expect_reached, schema


# ---- the context shape and the "same market or proven continuation" rule ----------------------------------------------------

BASE_SOURCES = {'market_row', 'model_publication', 'actions_row', 'basis_rows', 'evaluation_snapshot'}


def test_the_equity_sources_context_accepts_the_legacy_and_the_extended_shape_only(monkeypatch):
    reached = []
    real = core._row_digest
    monkeypatch.setattr(core, '_row_digest', lambda row: reached.append(row) or real(row))
    for extra, shape_ok in ((set(), True), ({'prior_binding', 'action_candidates'}, True),
                            ({'prior_binding'}, False), ({'action_candidates'}, False), ({'surprise'}, False)):
        del reached[:]
        accounting, decision = d_accounting(V1)
        template = accounting['equity_sources']
        accounting['equity_sources'] = {name: template.get(name) for name in BASE_SOURCES | extra}
        with pytest.raises(ValueError):  # always fails later (no basis, no snapshot); the shape decides whether it gets that far
            core._source_input(accounting, decision, [])
        assert bool(reached) is shape_ok, extra


def chain(action=None):
    inputs = assemble(parts(action))
    preceding = {'market_source_id': inputs['finalization_market']['source_id'],
                 'market_source_digest': inputs['finalization_market']['content_digest']}
    source = {'market_source_id': inputs['input_market']['source_id'], 'market_source_digest': inputs['input_market']['content_digest']}
    preceding_node = {'decision': inputs['prior_decision'],
                      'accounting': {'successor': {'market_row': inputs['finalization_market'], 'transition_row': inputs['finalization']}}}
    node = {'decision': inputs['decision'],
            'accounting': {'input_row': {'payload': source}, 'finalization_row': inputs['anchor'],
                           'equity_sources': {'market_row': inputs['input_market'], 'actions_row': inputs['actions_row'],
                                              'prior_binding': inputs['binding'],
                                              'action_candidates': inputs['candidate_action_sources']}}}
    return preceding, preceding_node, node


def test_the_same_market_keeps_the_old_path_and_needs_no_continuation_evidence():
    preceding, preceding_node, node = chain()
    node['accounting']['input_row']['payload'] = dict(preceding)
    node['accounting']['equity_sources'] = {}
    assert proof._market_continues(preceding, preceding_node, node) is True


def test_the_same_id_with_another_digest_is_never_a_continuation():
    preceding, preceding_node, node = chain()
    node['accounting']['input_row']['payload'] = {'market_source_id': preceding['market_source_id'], 'market_source_digest': '0' * 64}
    assert proof._market_continues(preceding, preceding_node, node) is False


@pytest.mark.parametrize('action', [None, 'split', 'dividend'])
def test_another_market_is_accepted_only_when_the_continuation_is_proved(action):
    preceding, preceding_node, node = chain(action)
    assert proof._market_continues(preceding, preceding_node, node) is True


def test_the_accounting_input_must_name_the_market_the_continuation_was_proved_for():
    preceding, preceding_node, node = chain('split')
    node['accounting']['input_row']['payload']['market_source_digest'] = '0' * 64
    assert proof._market_continues(preceding, preceding_node, node) is False
    preceding, preceding_node, node = chain('split')
    node['accounting']['input_row']['payload']['market_source_id'] = 'another-market'
    assert proof._market_continues(preceding, preceding_node, node) is False


def test_another_market_without_evidence_or_with_a_broken_proof_is_refused():
    for damage in ('binding_none', 'binding_missing_key', 'candidates_none', 'mark', 'sources_absent'):
        preceding, preceding_node, node = chain('split')
        sources = node['accounting']['equity_sources']
        if damage == 'binding_none':
            sources['prior_binding'] = None
        elif damage == 'binding_missing_key':
            del sources['prior_binding']
        elif damage == 'candidates_none':
            sources['action_candidates'] = None
        elif damage == 'mark':
            sources['market_row']['payload']['instruments'][0]['mark']['price_model_number'] = '90'
            sources['market_row']['content_digest'] = h(sources['market_row']['payload'])
            node['accounting']['input_row']['payload']['market_source_digest'] = sources['market_row']['content_digest']
        else:
            del node['accounting']['equity_sources']
        assert proof._market_continues(preceding, preceding_node, node) is False, damage


# ---- r2: type-strict JSON equality (true is not 1), UTF-8 byte caps, per-row caps ------------------------------------------

def test_json_equality_is_type_strict_like_nlohmann():
    eq = proof._eq
    assert eq(True, True) and eq(1, 1) and eq(1, 1.0) and eq('a', 'a') and eq(None, None)
    assert not eq(True, 1) and not eq(1, True) and not eq(False, 0) and not eq(0.0, False) and not eq(None, False)
    assert not eq('1', 1) and not eq([], {}) and not eq({'a': 1}, {'a': True}) and not eq([True], [1])
    assert eq({'a': [1, {'b': None}]}, {'a': [1.0, {'b': None}]}) and not eq({'a': 1}, {'a': 1, 'b': 2})


def relink_anchor(inputs):
    """After an anchor payload edit: reseal it and carry its digest into the binding, as a real chain would."""
    rehash(inputs['anchor'])
    inputs['binding']['finalization_source_digest'] = inputs['anchor']['content_digest']
    inputs['binding']['replay_reference']['finalization_source_digest'] = inputs['anchor']['content_digest']
    return reseal_binding(inputs)


def reseal_frame(inputs):
    reference = inputs['binding']['replay_reference']
    reference['action_frame_digest'] = h(reference['action_frame'])
    return reseal_binding(inputs)


def test_a_boolean_never_equals_an_integer_in_an_instrument_or_the_cost_config():
    p = parts()
    p.m_instruments[0]['cost_parameters']['tick_constrained'] = 1
    p.a_instruments[0]['cost_parameters']['tick_constrained'] = True
    refused(assemble(p))
    p.a_instruments[0]['cost_parameters']['tick_constrained'] = 1
    accepted(assemble(p))
    p = parts()                                      # valuation field: cost_config (everything else linked and sealed)
    p.cost_m['flag'], p.cost_a['flag'] = 1, True
    refused(assemble(p))
    p.cost_a['flag'] = 1
    accepted(assemble(p))


def test_a_boolean_never_equals_an_integer_in_a_policy_revision():
    for operand in ('finalization_market', 'finalization', 'actions_row'):
        inputs = assemble(parts())
        inputs[operand]['policy_revision'] = True
        refused(inputs)
    inputs = assemble(parts())
    inputs['anchor']['payload']['policy_revision'] = True
    refused(relink_anchor(inputs))


def test_a_boolean_never_equals_an_integer_in_the_basis_or_the_applied_row_copy():
    inputs = assemble(parts())                      # anchor basis 1 versus the reference's true
    inputs['anchor']['payload']['previous_positions'][0]['flag'] = 1
    inputs['binding']['replay_reference']['basis_positions'][0]['flag'] = True
    refused(relink_anchor(inputs))
    inputs = assemble(parts())
    inputs['anchor']['payload']['previous_positions'][0]['flag'] = 1
    inputs['binding']['replay_reference']['basis_positions'][0]['flag'] = 1
    accepted(relink_anchor(inputs))                 # the control: equal spellings pass
    inputs = assemble(parts('split'))               # the frame's own copy of the basis
    inputs['anchor']['payload']['previous_positions'][0]['flag'] = 1
    inputs['binding']['replay_reference']['basis_positions'][0]['flag'] = 1
    inputs['binding']['replay_reference']['action_frame']['original_basis_positions'][0]['flag'] = True
    relink_anchor(inputs)
    refused(reseal_frame(inputs))
    inputs = assemble(parts('split'))               # the whole actions row (revision 1) versus the frame's copy (true)
    accepted(inputs)
    frame = inputs['binding']['replay_reference']['action_frame']
    frame['actions_source']['policy_revision'] = True
    refused(reseal_frame(inputs))


def test_text_is_capped_at_4096_utf8_bytes_not_code_points():
    for symbol, ok in (('E' * 4096, True), ('\u00c9' * 2048, True), ('\u00c9' * 2049, False), ('\u00c9' * 3000, False)):
        p = parts(new_symbol=True)
        p.a_instruments[1]['symbol'] = symbol
        (accepted if ok else refused)(assemble(p))
    with pytest.raises(UnicodeError):               # a lone surrogate cannot be UTF-8; UnicodeError is in the refusal set
        proof._text('\ud800')
    assert issubclass(UnicodeError, proof._CONTINUATION_FAILURES)


def test_the_finalization_only_scope_caps_book_and_day_text_by_bytes_too():
    big = '\u00c9' * 2049
    m, market, model = scope_args()
    market['book_id'] = m['book_id'] = big
    rehash(m)
    with pytest.raises(ValueError):
        proof._prove_market_scope(m, market, None, book=big, day=S, valuation=D, empty_owner=False)
    ok = '\u00c9' * 2048
    m, market, model = scope_args()
    market['book_id'] = m['book_id'] = ok
    rehash(m)
    proof._prove_market_scope(m, market, None, book=ok, day=S, valuation=D, empty_owner=False)


@pytest.mark.parametrize('operand,field', [('finalization_market', 'as_of'), ('prior_decision', 'note'), ('binding', 'created_at'),
                                           ('actions_row', 'note')])
def test_the_rows_the_native_wrapper_loads_are_capped_at_2_mib_of_jsonb_text(operand, field):
    inputs = assemble(parts())
    inputs[operand][field] = ['x' * 4000] * 400              # ~1.6 MB of text in a column no rule reads: under the cap
    accepted(inputs)
    inputs = assemble(parts())
    inputs[operand][field] = ['x' * 4000] * 600              # ~2.4 MB: over the cap
    refused(inputs)


def test_the_other_operands_keep_the_8_mib_pure_cap():
    inputs = assemble(parts())
    inputs['input_market']['note'] = ['x' * 4000] * 600      # 2.4 MB is fine for A (the caller's row)
    accepted(inputs)
    inputs['input_market']['note'] = ['x' * 4000] * 2200     # 8.8 MB is not
    refused(inputs)


# ---- the hookup inside the real bounded graph proof ---------------------------------------------------------------------------

def graph_evidence(action=None):
    """A two-node lineage (S, then D) for the real _prove_graph; only the per-node proofs are stubbed."""
    preceding, s_node, d_node = chain(action)
    preceding.update(source_day=S, valuation_day=D)
    s_node['accounting']['finalization_row'] = {'payload': {'schema_version': 'qt-equity-finalized-accounting/v1'}}
    accounting = d_node['accounting']
    accounting.update(payload={'schema_version': 'qt-equity-accounting/v1'}, content_digest='c' * 64)
    accounting['input_row']['payload']['schema_version'] = 'qt-equity-accounting-input/v1'
    accounting['equity_sources'].setdefault('basis_rows', [])
    for name in ('preview', 'result', 'receipt', 'observation'):
        d_node[name] = {'kind': name}
    root = dict(accounting)
    root['equity_lineage'] = [d_node, s_node]
    evidence_record = {'decision': dict(d_node['decision']), 'accounting': root, **{n: dict(d_node[n]) for n in ('preview', 'result', 'receipt', 'observation')}}
    return evidence_record, preceding, d_node, s_node


@pytest.fixture()
def graph(monkeypatch):
    stubs = {}
    monkeypatch.setattr(proof, '_prove_anchor_record', lambda *args: {})
    monkeypatch.setattr(core, '_prove_original_sql', lambda node, factory, prior_anchor_validator=None: {})

    def successor(node, output, factory):
        return stubs['preceding']
    monkeypatch.setattr(proof, '_prove_successor', successor)
    return stubs


def run_graph(graph, evidence_record, preceding):
    graph['preceding'] = preceding
    return proof._prove_graph(evidence_record, lambda authority: None, lambda authority: None)


@pytest.mark.parametrize('action', [None, 'split', 'dividend'])
def test_the_graph_accepts_a_proven_continuation_and_takes_the_old_path_for_the_same_market(graph, action):
    evidence_record, preceding, d_node, s_node = graph_evidence(action)
    run_graph(graph, evidence_record, preceding)                     # A is not M: the port holds
    evidence_record, preceding, d_node, s_node = graph_evidence(action)
    d_node['accounting']['input_row']['payload'] = {                 # the input names M itself
        'schema_version': 'qt-equity-accounting-input/v1', 'market_source_id': preceding['market_source_id'],
        'market_source_digest': preceding['market_source_digest']}
    d_node['accounting']['equity_sources'] = {'basis_rows': []}      # no continuation evidence needed at all
    run_graph(graph, evidence_record, preceding)


def test_the_graph_refuses_another_market_without_a_proof_and_keeps_its_day_conjuncts(graph):
    for damage in ('binding', 'candidates', 'mark', 'source_day', 'valuation_day'):
        evidence_record, preceding, d_node, s_node = graph_evidence('split')
        sources = d_node['accounting']['equity_sources']
        if damage == 'binding':
            sources['prior_binding'] = None
        elif damage == 'candidates':
            sources['action_candidates'] = []
        elif damage == 'mark':
            sources['market_row']['payload']['instruments'][0]['mark']['price_model_number'] = '90'
            sources['market_row']['content_digest'] = h(sources['market_row']['payload'])
            d_node['accounting']['input_row']['payload']['market_source_digest'] = sources['market_row']['content_digest']
        else:
            preceding[damage] = '2026-01-01'
        with pytest.raises(ValueError):
            run_graph(graph, evidence_record, preceding)


# ---- the SQL loader for the continuation evidence --------------------------------------------------------------------------

class Cursor:
    def __init__(self, table_present=True, binding=None, candidates=()):
        self.table_present, self.binding, self.candidates = table_present, binding, candidates
        self.log, self._rows = [], []

    def execute(self, sql, args=None):
        self.log.append((sql, args))
        if 'to_regclass' in sql:
            self._rows = [{'present': self.table_present}]
        elif 'AS market_octets' in sql:
            self._rows = [{'market_octets': 1000, 'decision_octets': 1000, 'actions_octets': 1000}]
        elif 'qt_equity_model_prior_bindings' in sql:
            self._rows = [] if self.binding is None else [self.binding]
        elif 'qt_equity_desk_evidence_sources' in sql:
            self._rows = [{'source_id': s} for s in self.candidates]
        else:
            raise AssertionError(sql)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


def loader_case(same_market):
    inputs = assemble(parts('split'))
    finalization = dict(inputs['finalization'])
    if same_market:
        finalization['market_source_id'] = inputs['input_market']['source_id']
    accounting = {'equity_sources': {'market_row': inputs['input_market'], 'prior_binding': None, 'action_candidates': None}}
    return inputs, finalization, accounting


def test_the_loader_reads_nothing_new_when_the_input_market_is_the_finalization_market():
    inputs, finalization, accounting = loader_case(True)
    cursor = Cursor()
    evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
    assert cursor.log == []
    assert accounting['equity_sources']['prior_binding'] is None


def test_the_loader_reads_the_binding_by_the_nodes_model_and_the_nonempty_candidates_by_the_markets_role():
    inputs, finalization, accounting = loader_case(False)
    cursor = Cursor(binding=inputs['binding'], candidates=[ACT_D])
    evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
    reads = {sql.split('FROM')[1].split()[0]: (sql, args) for sql, args in cursor.log if 'FROM' in sql}
    assert reads['trading.qt_equity_model_prior_bindings'][1] == (P2,)
    sql, args = reads['trading.qt_equity_desk_evidence_sources']
    market = inputs['input_market']
    assert args == (BOOK, D, S, market['producer_id'], market['policy_version'], market['policy_revision'])
    # the MODEL's own selection (equity_model_action_source.cpp:44), predicate for predicate
    for predicate in ("book_id=%s", "source_day=%s::date", "purpose='actions'", "payload->>'previous_day'=%s", "producer_id=%s",
                      "policy_version=%s", "policy_revision=%s", "jsonb_array_length(payload->'events')>0",
                      "ORDER BY source_id LIMIT 4097"):
        assert predicate in sql, predicate
    assert 'CASE' not in sql
    assert accounting['equity_sources']['prior_binding'] == inputs['binding']
    assert accounting['equity_sources']['action_candidates'] == [ACT_D]
    assert not any(word in text.upper() for text, _ in cursor.log for word in ('INSERT ', 'UPDATE ', 'DELETE '))


def test_the_loader_refuses_by_privilege_probe_and_caps_the_binding_row():
    inputs, finalization, accounting = loader_case(False)
    cursor = Cursor(binding=inputs['binding'], candidates=[ACT_D])
    evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
    probe = cursor.log[0][0]
    assert 'has_table_privilege' in probe and "'SELECT'" in probe and 'to_regclass' in probe and 'CASE' in probe
    binding_sql = next(sql for sql, _ in cursor.log if sql.startswith('SELECT * FROM trading.qt_equity_model_prior_bindings'))
    assert 'octet_length(to_jsonb(b)::text)<=2097152' in binding_sql.replace(' ', '')
    # no SELECT privilege behaves like no table: the binding stays empty, nothing on it is read, the transaction is not aborted
    cursor = Cursor(table_present=False, candidates=[ACT_D])
    inputs, finalization, accounting = loader_case(False)
    evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
    assert accounting['equity_sources']['prior_binding'] is None
    assert not any(sql.startswith('SELECT * FROM trading.qt_equity_model_prior_bindings') for sql, _ in cursor.log)


def test_the_loader_leaves_the_binding_empty_when_no_row_or_no_table_exists():
    for cursor in (Cursor(binding=None, candidates=[ACT_D]), Cursor(table_present=False, candidates=[ACT_D])):
        inputs, finalization, accounting = loader_case(False)
        evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
        assert accounting['equity_sources']['prior_binding'] is None
        assert accounting['equity_sources']['action_candidates'] == [ACT_D]
    cursor = Cursor(table_present=False)
    inputs, finalization, accounting = loader_case(False)
    evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
    assert not any('qt_equity_model_prior_bindings' in q and 'to_regclass' not in q for q, _ in cursor.log)


def test_the_loader_bounds_the_candidate_set():
    inputs, finalization, accounting = loader_case(False)
    with pytest.raises(ValueError):
        evidence.load_continuation_evidence(Cursor(binding=inputs['binding'], candidates=['s%d' % i for i in range(4097)]),
                                            inputs['decision'], accounting, finalization)


def test_a_finalization_market_without_a_model_loads_no_publication():
    inputs = assemble(parts())
    assert evidence.market_model_publication(None, inputs['finalization_market'], loader=lambda *a: pytest.fail('loaded')) is None
    sentinel = object()
    assert evidence.market_model_publication(None, inputs['input_market'], loader=lambda cursor, ident: (ident, sentinel)) == (P2, sentinel)


# ---- r3: the remaining operand comparisons, the byte-capped ids, the exact size measures -------------------------------------

def test_b1_a_boolean_valuation_time_in_the_actions_payload_never_equals_an_integer_one():
    p = parts()
    p.vt_m = p.vt_a = 1
    p.vt_act = 'x'
    inputs = assemble(p)
    refused(inputs)                                 # the control: a text valuation time that differs from 1
    p.vt_act = 1
    accepted(assemble(p))                           # the control: identical spellings pass
    p.vt_act = True
    refused(assemble(p))                            # native ep.at(k)==ap.at(k): true != 1


def test_b2_a_boolean_decision_id_never_equals_an_integer_one_across_f_s_the_binding_and_the_reference():
    p = parts()
    p.sid, p.fdec = True, 1
    refused(assemble(p))
    p.fdec = True
    accepted(assemble(p))                           # the control: true against true is equal, as in nlohmann
    p.fdec = 1
    p.sid = 1
    accepted(assemble(p))


def test_b2_the_finalization_payload_compares_to_the_finalization_row_type_strictly():
    p = parts()
    p.sid = p.fdec = 1
    p.fpdec = True
    refused(assemble(p))
    p.fpdec = 1
    accepted(assemble(p))


def test_b2_the_binding_and_the_reference_each_compare_to_s_type_strictly():
    for target in ('binding', 'reference'):
        p = parts()
        p.sid = p.fdec = 1
        inputs = assemble(p)
        holder = inputs['binding'] if target == 'binding' else inputs['binding']['replay_reference']
        holder['decision_id'] = True
        refused(reseal_binding(inputs))


def test_the_anchor_currency_pair_is_type_strict():
    p = parts()
    p.cur_m = p.cur_a = True
    inputs = assemble(p)
    inputs['anchor']['payload']['currency'] = 1
    refused(relink_anchor(inputs))                  # anchor 1 against the market's true
    inputs = assemble(p)
    inputs['anchor']['payload']['currency'] = True
    accepted(relink_anchor(inputs))                 # the control: true against true


def test_b3_the_applied_actions_source_id_and_the_candidates_are_capped_by_utf8_bytes():
    for identifier, ok in (('\u00c9' * 2048, True), ('\u00c9' * 2049, False), ('\u00c9' * 3011, False)):
        p = parts('split')
        p.act_d = identifier
        (accepted if ok else refused)(assemble(p))
    inputs = assemble(parts('split'))
    inputs['candidate_action_sources'] = ['\u00c9' * 2049]
    refused(inputs)


MIB = 1024 * 1024


def _spaced(row):
    return len(json.dumps(row, separators=(', ', ': '), ensure_ascii=False).encode('utf-8'))


def _compact(row):
    return len(json.dumps(row, separators=(',', ':'), ensure_ascii=False).encode('utf-8'))


def test_the_8_mib_cap_is_measured_with_compact_separators_like_native_dump():
    inputs = assemble(parts())
    row = inputs['input_market']
    row['note'] = ''
    assert _spaced(row) > _compact(row)
    row['note'] = 'x' * (8 * MIB - _compact(row))       # compact size exactly 8 MiB: accepted (spaced would be over)
    assert _compact(row) == 8 * MIB and _spaced(row) > 8 * MIB
    accepted(inputs)
    row['note'] += 'x'                                   # one byte over in compact spelling
    refused(inputs)


def test_the_2_mib_cap_of_the_loaded_rows_uses_the_jsonb_spelling():
    inputs = assemble(parts())
    row = inputs['actions_row']
    row['note'] = ''
    row['note'] = 'x' * (2 * MIB - _spaced(row))
    assert _spaced(row) == 2 * MIB
    accepted(inputs)
    row['note'] += 'x'
    refused(inputs)


class OctetCursor(Cursor):
    """Adds the exact PG-side size probe of the rows the native wrapper loads (M, S, actions row)."""

    def __init__(self, octets=(1000, 1000, 1000), **kwargs):
        super().__init__(**kwargs)
        self.octets = octets

    def execute(self, sql, args=None):
        if 'AS market_octets' in sql:
            self.log.append((sql, args))
            self._rows = [{'market_octets': self.octets[0], 'decision_octets': self.octets[1], 'actions_octets': self.octets[2]}]
        else:
            super().execute(sql, args)


def test_the_loader_measures_m_s_and_the_actions_row_with_pg_octet_length_and_refuses_an_oversize_one():
    inputs, finalization, accounting = loader_case(False)
    cursor = OctetCursor(binding=inputs['binding'], candidates=[ACT_D])
    evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
    sql, args = next(entry for entry in cursor.log if 'AS market_octets' in entry[0])
    for table in ('trading.qt_desk_market_sources', 'trading.qt_decisions', 'trading.qt_equity_desk_evidence_sources'):
        assert table in sql
    assert sql.count('octet_length(to_jsonb(') == 3 and '::text)' in sql
    assert args == (str(finalization['market_source_id']), str(finalization['decision_id']),
                    inputs['input_market']['payload']['actions_source_id'])
    assert accounting['equity_sources']['prior_binding'] == inputs['binding']
    for octets in ((2097153, 1, 1), (1, 2097153, 1), (1, 1, 2097153), (None, 1, 1), (1, None, 1), (1, 1, None)):
        inputs, finalization, accounting = loader_case(False)
        cursor = OctetCursor(octets=octets, binding=inputs['binding'], candidates=[ACT_D])
        evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
        assert accounting['equity_sources']['prior_binding'] is None, octets
        assert accounting['equity_sources']['action_candidates'] == [ACT_D]
    inputs, finalization, accounting = loader_case(False)
    cursor = OctetCursor(octets=(2097152, 2097152, 2097152), binding=inputs['binding'], candidates=[ACT_D])
    evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
    assert accounting['equity_sources']['prior_binding'] == inputs['binding']      # exactly 2 MiB is allowed
    cursor = OctetCursor(binding=None, candidates=[])
    inputs, finalization, accounting = loader_case(False)
    evidence.load_continuation_evidence(cursor, inputs['decision'], accounting, finalization)
    assert not any('AS market_octets' in sql for sql, _ in cursor.log)              # nothing to measure without a binding

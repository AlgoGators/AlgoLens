"""Shared native/API vectors for the equity day-2 continuation validator (lane N4 -> lane A1).

``contracts/qt-equity-prior-continuation-vectors-v1.json`` is consumed byte for byte from the native
tree (trade-ngin ``tests/contracts``); this test never rewrites or normalizes it.  Every case must
match the Python port exactly: every ``accepted`` case is accepted and every ``refused`` case is refused with
the single fixed error code.
"""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from algolens.infrastructure.portfolio import qt_equity_finalization_proof as proof

VECTORS = Path(__file__).resolve().parent / 'contracts' / 'qt-equity-prior-continuation-vectors-v1.json'
EXPECTED_CASE_COUNT = 114
DOCUMENT = json.loads(VECTORS.read_bytes().decode('utf-8'))
CASES = DOCUMENT['cases']


def test_the_vector_file_declares_and_holds_exactly_its_case_count():
    assert DOCUMENT['schema_version'] == 'qt-equity-prior-continuation-vectors/v1'
    assert type(DOCUMENT['case_count']) is int
    assert DOCUMENT['case_count'] == len(CASES) == EXPECTED_CASE_COUNT
    assert len({case['name'] for case in CASES}) == len(CASES)
    assert {case['expected'] for case in CASES} == {'accepted', 'refused'}
    assert DOCUMENT['error_code'] == proof.CONTINUATION_UNAVAILABLE == 'qt_equity_prior_continuation_unavailable'


def test_the_v3_cases_that_expose_the_lazy_namespace_rule_are_present():
    names = {case['name'] for case in CASES}
    assert {'accepted_no_action_m_quote_ids_without_namespace', 'accepted_split_m_quote_ids_without_namespace',
            'refused_new_symbol_m_quote_ids_without_namespace'} <= names


def test_every_case_carries_exactly_the_nine_validator_operands():
    for case in CASES:
        assert set(case['inputs']) == {'decision', 'prior_decision', 'finalization_market', 'input_market', 'finalization',
                                       'anchor', 'binding', 'actions_row', 'candidate_action_sources'}, case['name']


def test_the_positive_and_negative_mix_is_not_one_sided():
    counts = {kind: sum(case['expected'] == kind for case in CASES) for kind in ('accepted', 'refused')}
    assert counts == {'accepted': 17, 'refused': 97}


@pytest.mark.parametrize('case', CASES, ids=[case['name'] for case in CASES])
def test_the_python_port_matches_the_native_vector(case):
    inputs = deepcopy(case['inputs'])
    if case['expected'] == 'accepted':
        assert proof.validate_qt_equity_verified_prior_continuation(inputs) is None
        assert proof.qt_equity_prior_continuation_holds(deepcopy(case['inputs'])) is True
    else:
        with pytest.raises(ValueError) as caught:
            proof.validate_qt_equity_verified_prior_continuation(inputs)
        assert str(caught.value) == DOCUMENT['error_code']
        assert proof.qt_equity_prior_continuation_holds(deepcopy(case['inputs'])) is False
    assert inputs == case['inputs'], 'the validator must not mutate its operands'

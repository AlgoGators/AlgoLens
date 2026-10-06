"""N5 r2 (F1): the lifecycle refusal for a desk day awaiting finalization is a 409 that carries its reason."""
from algolens.adapters.http.portfolio import _incubation_error_body, _incubation_error_status
from algolens.application.portfolio.ports import IncubationError, OpenPositionsError


class _Pending(IncubationError):
    code = 'desk_finalization_pending'   # the code DeskFinalizationPendingError carries


def test_pending_desk_finalization_is_a_409_with_reason():
    error = _Pending('QT desk day(s) awaiting next-day finalization: BOOK_A 2026-09-22.')
    assert _incubation_error_status(error) == 409
    assert _incubation_error_body(error) == {
        'error': 'desk_finalization_pending',
        'reason': 'QT desk day(s) awaiting next-day finalization: BOOK_A 2026-09-22.'}


def test_the_real_error_class_carries_that_code():
    from algolens.application.portfolio import ports
    error = ports.DeskFinalizationPendingError('reason')
    assert isinstance(error, IncubationError) and error.code == 'desk_finalization_pending'
    assert _incubation_error_status(error) == 409


def test_existing_lifecycle_refusals_are_unchanged():
    assert _incubation_error_status(OpenPositionsError('x')) == 409
    assert _incubation_error_body(OpenPositionsError('x')) == {'error': 'open_positions'}
    assert _incubation_error_status(IncubationError('reason must be non-empty')) == 400
    assert _incubation_error_body(IncubationError('reason must be non-empty')) == {'error': 'reason must be non-empty'}

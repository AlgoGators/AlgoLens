"""First-day arithmetic is inherited balances plus incremental QT cash only."""
from copy import deepcopy
import pytest

from algolens.infrastructure.portfolio.qt_finalization_proof import _digest
from algolens.infrastructure.portfolio.qt_first_day_proof import verify_first_day_financials


def first_day():
    key = dict(portfolio_id='BOOK', strategy_id='ENGINE', strategy_name='owner', symbol='SYN',
               date='2026-10-06', portfolio_type='qt')
    stamp = '2026-10-06T00:00:00Z'
    source = dict(book_id='BOOK', source_day=key['date'], currency='USD', timestamp=stamp,
        accounting_source_id='market', previous_positions=[dict(key=key, quantity_exact='4', average_price_exact='100',
            daily_realized_pnl_exact='-1', daily_unrealized_pnl_exact='2.5')],
        previous_totals=[dict(strategy_id='ENGINE', equity_exact='1000', total_pnl_exact='20', daily_pnl_exact='1',
            daily_realized_pnl_exact='-1', daily_unrealized_pnl_exact='2.5',
            daily_transaction_costs_exact='0.5', total_transaction_costs_exact='12')])
    fill = dict(key=key, selected_quantity_exact='5', daily_realized_pnl_exact='-1', daily_unrealized_pnl_exact='2.5',
        actual_cash_cost_exact='2', accounting_source_id='market', currency='USD', last_update=stamp,
        execution_id='execution', observation_kind='executed')
    output = dict(input_digest=_digest(source), observation=dict(fills=[fill]),
        executions=[dict(key=key, exec_id='execution', side='BUY', quantity_exact='1', execution_time=stamp,
            commissions_fees_exact='2', implicit_price_impact_exact='0', slippage_market_impact_exact='0',
            total_transaction_costs_exact='2')],
        live_results=[dict(portfolio_id='BOOK', strategy_id='ENGINE', date=key['date'], portfolio_type='qt',
            current_portfolio_value_exact='998', total_pnl_exact='18', daily_pnl_exact='-1',
            daily_realized_pnl_exact='-1', daily_unrealized_pnl_exact='2.5',
            daily_transaction_costs_exact='2.5', total_transaction_costs_exact='14')])
    return dict(input_row=dict(payload=source, content_digest=_digest(source)), payload=output, content_digest=_digest(output))


def test_first_day_inherits_financials_without_double_charging():
    row = first_day()
    before = deepcopy(row)
    verify_first_day_financials(row)
    assert row == before


def test_native_independent_rounding_and_price_units_are_not_extra_cash():
    row = first_day()
    row['payload']['executions'][0].update(commissions_fees_exact='1.00000001',
        slippage_market_impact_exact='1', implicit_price_impact_exact='0.02')
    row['content_digest'] = _digest(row['payload'])
    verify_first_day_financials(row)


def test_genuinely_new_model_component_starts_with_zero_inherited_pnl():
    row = first_day()
    fill = deepcopy(row['payload']['observation']['fills'][0])
    fill['key']['symbol'] = 'NEW'
    fill.update(selected_quantity_exact='1', daily_realized_pnl_exact='0', daily_unrealized_pnl_exact='0',
                execution_id='new-execution')
    execution = deepcopy(row['payload']['executions'][0])
    execution.update(key=fill['key'], exec_id='new-execution')
    row['payload']['observation']['fills'].append(fill)
    row['payload']['executions'].append(execution)
    row['payload']['live_results'][0].update(current_portfolio_value_exact='996', total_pnl_exact='16',
        daily_pnl_exact='-3', daily_transaction_costs_exact='4.5', total_transaction_costs_exact='16')
    row['content_digest'] = _digest(row['payload'])
    verify_first_day_financials(row)
    fill['daily_realized_pnl_exact'] = '-1'
    row['content_digest'] = _digest(row['payload'])
    with pytest.raises(ValueError):
        verify_first_day_financials(row)


@pytest.mark.parametrize('field,value', [
    ('daily_pnl_exact', '-2'), ('daily_realized_pnl_exact', '0'), ('daily_unrealized_pnl_exact', '0'),
    ('daily_transaction_costs_exact', '2'), ('total_transaction_costs_exact', '2'),
    ('current_portfolio_value_exact', '997.5'), ('total_pnl_exact', '17.5'),
])
def test_first_day_rehashed_financial_resets_and_double_costs_rejected(field, value):
    row = first_day()
    row['payload']['live_results'][0][field] = value
    row['content_digest'] = _digest(row['payload'])
    with pytest.raises(ValueError):
        verify_first_day_financials(row)


@pytest.mark.parametrize('field,value', [
    ('side', 'SELL'), ('quantity_exact', '2'), ('total_transaction_costs_exact', '3'),
    ('exec_id', 'other'), ('commissions_fees_exact', '0'), ('execution_time', '2026-10-05T00:00:00Z'),
])
def test_first_day_rehashed_execution_must_close_exact_delta_and_cost(field, value):
    row = first_day()
    row['payload']['executions'][0][field] = value
    row['content_digest'] = _digest(row['payload'])
    with pytest.raises(ValueError):
        verify_first_day_financials(row)


def test_missing_opening_owner_and_duplicate_fills_are_rejected():
    for duplicate in (False, True):
        row = first_day()
        if duplicate:
            row['payload']['observation']['fills'] *= 2
        else:
            row['payload']['observation']['fills'] = []
        row['content_digest'] = _digest(row['payload'])
        with pytest.raises(ValueError):
            verify_first_day_financials(row)

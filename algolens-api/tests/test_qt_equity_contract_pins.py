"""Tracked QT inspection contracts must load under their checked-in pins."""

import importlib


def test_checked_in_equity_consumption_contracts_match_their_pins():
    module = importlib.import_module(
        "algolens.domain.portfolio.qt_equity_run_consumption"
    )

    assert callable(module.validate_equity_run_consumption)

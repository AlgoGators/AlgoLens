"""Compatibility alias for portfolio HTTP routes."""

import sys

from algolens.adapters.http import portfolio as _portfolio_module

sys.modules[__name__] = _portfolio_module

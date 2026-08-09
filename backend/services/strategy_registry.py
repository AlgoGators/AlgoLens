"""Compatibility alias for the strategy registry infrastructure module."""

import sys

from algolens.infrastructure.portfolio import strategy_registry as _registry_module

sys.modules[__name__] = _registry_module

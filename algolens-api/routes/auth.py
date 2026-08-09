"""Compatibility alias for auth HTTP routes."""

import sys

from algolens.adapters.http import auth as _auth_module

sys.modules[__name__] = _auth_module

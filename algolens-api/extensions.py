"""Shared Flask extension instances.

Kept in their own module so both app.py (which calls init_app) and the route
blueprints (which apply @limiter.limit decorators) can import them without a
circular import back through app.py.
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Rate limiter. No global default limits -- individual sensitive routes opt in
# with @limiter.limit(...). Keyed on the client IP (see ProxyFix in app.py, which
# makes request.remote_addr reflect the real client rather than the nginx proxy).
#
# NOTE: the default in-memory storage is per-process. Under multiple gunicorn
# workers each worker keeps its own counters, so the effective limit is roughly
# (configured limit x worker count). For strict cross-worker limits, point
# storage_uri at a shared backend (e.g. Redis) via RATELIMIT_STORAGE_URI.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
)

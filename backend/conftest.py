"""Make the backend package importable from tests.

Placed at the backend root (not in tests/) so it only handles sys.path setup and
does not collide with any fixture conftest under tests/. This lets
`from services import ...` and `import app` resolve when pytest is run from here.
"""

import os
import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

"""Compatibility entrypoint for legacy imports.

New deployments should import `algolens.infrastructure.config.app_factory` or use
`wsgi:app`. This module remains so existing tests and local commands that do
`import app` keep the same module-level `app` object.
"""

import os

from algolens.infrastructure.config.app_factory import create_app
from extensions import limiter

app = create_app()

ENV = app.config["ALGOLENS_ENV"]
DEBUG = app.config["ALGOLENS_DEBUG"]
IS_PRODUCTION = app.config["ALGOLENS_IS_PRODUCTION"]


if __name__ == "__main__":
    # NEVER use debug=True in production - it exposes remote code execution vulnerability
    port = int(os.getenv("PORT", 5000))
    app.run(debug=DEBUG, port=port, host="0.0.0.0")

"""Deployment entrypoint for the AlgoLens Flask backend."""

import os

from algolens.infrastructure.config.app_factory import create_app
from extensions import limiter

app = create_app()

ENV = app.config["ALGOLENS_ENV"]
DEBUG = app.config["ALGOLENS_DEBUG"]
IS_PRODUCTION = app.config["ALGOLENS_IS_PRODUCTION"]


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(debug=DEBUG, port=port, host="0.0.0.0")

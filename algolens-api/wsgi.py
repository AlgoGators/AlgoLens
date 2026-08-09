"""WSGI entrypoint for gunicorn."""

from algolens.infrastructure.config.app_factory import create_app

app = create_app()

"""Test-runner-only ownership of logs created by Flask app factories."""
from contextlib import contextmanager
from hashlib import sha256
import logging.handlers
from pathlib import Path


_ROTATING_HANDLER = logging.handlers.RotatingFileHandler


@contextmanager
def isolated_api_logs(directory):
    """Redirect real rotating handlers; restore and close them even on failure."""
    directory = Path(directory).resolve(strict=True)
    previous = logging.handlers.RotatingFileHandler
    handlers = []

    class OwnedRotatingHandler(_ROTATING_HANDLER):
        def __init__(self, filename, *args, **kwargs):
            name = Path(filename).name
            identity = sha256(str(filename).encode('utf-8')).hexdigest()[:16]
            super().__init__(directory / (identity + '-' + name), *args, **kwargs)
            handlers.append(self)

    logging.handlers.RotatingFileHandler = OwnedRotatingHandler
    try:
        yield
    finally:
        logging.handlers.RotatingFileHandler = previous
        for handler in handlers:
            handler.close()

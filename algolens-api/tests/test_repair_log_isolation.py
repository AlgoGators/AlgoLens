"""The repair runner must never append to existing application evidence."""
import logging
import logging.handlers

import pytest

from repair_log_isolation import isolated_api_logs


@pytest.mark.parametrize('raise_inside', [False, True])
def test_rotating_logs_are_owned_and_handlers_restored(tmp_path, monkeypatch, raise_inside):
    monkeypatch.chdir(tmp_path)
    existing = tmp_path / 'logs' / 'algolens.log'
    existing.parent.mkdir()
    existing.write_bytes(b'prior application evidence\n')
    owned = tmp_path / 'owned-run-logs'
    owned.mkdir()
    original = logging.handlers.RotatingFileHandler
    handler = None
    try:
        with isolated_api_logs(owned):
            handler = logging.handlers.RotatingFileHandler('logs/algolens.log')
            handler.emit(logging.LogRecord('synthetic-test', logging.INFO, __file__, 1,
                                           'synthetic startup', (), None))
            if raise_inside:
                raise RuntimeError('synthetic failure')
    except RuntimeError as error:
        assert raise_inside and str(error) == 'synthetic failure'
    finally:
        if handler is not None:
            handler.close()
    assert existing.read_bytes() == b'prior application evidence\n'
    assert [path.read_text() for path in owned.glob('*.log')] == ['synthetic startup\n']
    assert logging.handlers.RotatingFileHandler is original

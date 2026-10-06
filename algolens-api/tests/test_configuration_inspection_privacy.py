"""Synthetic logging sentinels never reach shared DB or role diagnostics."""

import importlib.util
import logging
from pathlib import Path
import socket

import dotenv
import psycopg2
import pytest

from algolens.application.configuration_inspection import ConfigurationInspectionService
from tests.test_incubation_routes import _set_jwt_cookie


SOURCE = Path(__file__).parents[1] / "algolens" / "infrastructure" / "db" / "postgres.py"
URL = "/portfolio/strategies/trend/configuration?portfolio_id=BOOK"
SENTINELS = {
    "DB_HOST": "host-private-sentinel.example",
    "DB_PORT": "5432-private-sentinel",
    "DB_NAME": "database-private-sentinel",
    "DB_USER": "user-private-sentinel",
    "DB_PASSWORD": "password-private-sentinel",
}


def _isolated_module(monkeypatch):
    # Patch dotenv before executing the module body: no real dotenv is read.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    for key, value in SENTINELS.items():
        monkeypatch.setenv(key, value)
    spec = importlib.util.spec_from_file_location("algolens_db_postgres_privacy_probe", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_no_private_log(caplog, *extra):
    rendered = caplog.text
    for sentinel in (*SENTINELS.values(), *extra):
        assert sentinel not in rendered
    assert "Traceback" not in rendered


def test_import_and_successful_connection_keep_identity_out_of_logs(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    marker = object()
    monkeypatch.setattr(socket, "gethostbyname", lambda host: "ip-private-sentinel")
    calls = []

    def connect(**kwargs):
        calls.append(kwargs)
        return marker

    monkeypatch.setattr(psycopg2, "connect", connect)
    module = _isolated_module(monkeypatch)
    assert module.get_db_connection() is marker
    assert calls == [{"host": SENTINELS["DB_HOST"], "port": SENTINELS["DB_PORT"],
                      "user": SENTINELS["DB_USER"], "password": SENTINELS["DB_PASSWORD"],
                      "dbname": SENTINELS["DB_NAME"],
                      "cursor_factory": module.RealDictCursor, "connect_timeout": 10}]
    _assert_no_private_log(caplog, "ip-private-sentinel")
    assert "DB_PASSWORD set" not in caplog.text


def test_dns_and_connection_errors_keep_raw_details_out_of_logs(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(socket, "gethostbyname",
                        lambda host: (_ for _ in ()).throw(socket.gaierror("dns-private-sentinel")))

    def connect(**kwargs):
        raise psycopg2.OperationalError("connection-private-sentinel")

    monkeypatch.setattr(psycopg2, "connect", connect)
    module = _isolated_module(monkeypatch)
    with pytest.raises(psycopg2.OperationalError, match="connection-private-sentinel"):
        module.get_db_connection()
    _assert_no_private_log(caplog, "dns-private-sentinel", "connection-private-sentinel")


def test_missing_connection_settings_keep_exception_but_log_one_fixed_event(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    module = _isolated_module(monkeypatch)
    external_calls = []
    monkeypatch.setattr(socket, "gethostbyname",
                        lambda *args: external_calls.append(("dns", args)))
    monkeypatch.setattr(psycopg2, "connect",
                        lambda **kwargs: external_calls.append(("connect", kwargs)))
    cases = [
        (("DB_HOST",), "Missing required database environment variables: DB_HOST"),
        (("DB_USER",), "Missing required database environment variables: DB_USER"),
        (("DB_PASSWORD",), "Missing required database environment variables: DB_PASSWORD"),
        (("DB_NAME",), "Missing required database environment variables: DB_NAME"),
        (("DB_HOST", "DB_PASSWORD"),
         "Missing required database environment variables: DB_HOST, DB_PASSWORD"),
        (("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME"),
         "Missing required database environment variables: DB_HOST, DB_USER, DB_PASSWORD, DB_NAME"),
    ]
    emitted = []
    for missing, expected_error in cases:
        for key, value in SENTINELS.items():
            monkeypatch.setenv(key, value)
        for key in missing:
            monkeypatch.delenv(key)
        caplog.clear()
        with pytest.raises(ValueError) as failure:
            module.get_db_connection()
        assert str(failure.value) == expected_error
        assert external_calls == []
        errors = [record for record in caplog.records
                  if record.name == module.logger.name and record.levelno == logging.ERROR]
        assert len(errors) == 1
        assert errors[0].args == ()
        assert errors[0].exc_info is None
        emitted.append(errors[0].getMessage())
        _assert_no_private_log(caplog)
        for key in SENTINELS:
            assert key not in caplog.text
        assert "password" not in caplog.text.lower()
    assert len(set(emitted)) == 1


def test_role_lookup_failure_logs_fixed_event_and_preserves_authorization(
    client, monkeypatch, caplog
):
    import algolens.adapters.http.configuration_inspection as http

    class Reader:
        def read(self, _registry_id, portfolio_id, _read_at):
            return "unavailable", "not_published", portfolio_id

    monkeypatch.setattr(http, "create_configuration_inspection_service",
                        lambda: ConfigurationInspectionService(Reader()))
    _set_jwt_cookie(client, role="admin", identity="7")
    client.current_users.error = RuntimeError("role-private-sentinel")
    caplog.set_level(logging.ERROR)
    failed = client.get(URL)
    assert failed.status_code == 503
    assert "role-private-sentinel" not in failed.get_data(as_text=True)
    assert "role-private-sentinel" not in caplog.text
    assert "Traceback" not in caplog.text
    errors = [record for record in caplog.records
              if record.getMessage().startswith("Authorization lookup failed")]
    assert len(errors) == 1
    assert errors[0].exc_info is None
    assert errors[0].args == ()

    client.current_users.error = None
    healthy = client.get(URL)
    assert healthy.status_code == 200
    assert healthy.json["reason"] == "not_published"

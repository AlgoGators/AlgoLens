"""Synthetic v2 publication through the real PostgreSQL reader and Flask GET.

These envelopes combine accepted fixture children with the v1 synthetic outer
fixture. They are not output from the C++ publication writer.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json

import psycopg2
from psycopg2.extras import RealDictCursor
import pytest

from algolens.application.configuration_inspection import ConfigurationInspectionService
from algolens.infrastructure.portfolio.configuration_inspection import PostgresConfigurationInspectionReader
from tests.integration.conftest import require_test_dsn
from tests.integration.test_configuration_inspection_read import _connect, _exec, database
from tests.test_configuration_inspection_v2 import (
    _boundary_publication,
    _compact,
    _raw_short_exponent,
    publication,
)
from tests.test_incubation_routes import _set_jwt_cookie


URL = "/portfolio/strategies/trend/configuration?portfolio_id=book"
READ_AT = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
PARENT_PRIVATE = "synthetic-private-sentinel"
OTHER_BOOK_PRIVATE = "synthetic-other-book-v2-private"


def _publish(value, *, run_date="2026-09-22", raw_child=None):
    if raw_child is None:
        parent = json.dumps({"old_key": PARENT_PRIVATE, "config_inspection": value})
    else:
        parent = (json.dumps({"old_key": PARENT_PRIVATE})[:-1]
                  + ',"config_inspection":' + raw_child + "}")
    _exec("UPDATE trading.live_run_metadata SET portfolio_config=%s::jsonb "
          "WHERE strategy_id='LIVE_TREND' AND portfolio_id='BOOK' AND date=%s",
          (parent, run_date))


def _get(client, monkeypatch, *, authenticate=True, connection_factory=_connect):
    import algolens.adapters.http.configuration_inspection as http

    service = ConfigurationInspectionService(
        PostgresConfigurationInspectionReader(connection_factory), clock=lambda: READ_AT)
    monkeypatch.setattr(http, "create_configuration_inspection_service", lambda: service)
    if authenticate:
        _set_jwt_cookie(client, role="admin", identity="7")
    return client.get(URL)


def _assert_private_and_scoped(response):
    body = response.json
    assert body["api_version"] == 1
    assert body["scope"] == {"registry_id": "trend", "portfolio_id": "BOOK"}
    assert body["read_at"] == "2026-09-24T12:00:00Z"
    assert "no-store" in response.headers["Cache-Control"]
    text = response.get_data(as_text=True)
    assert PARENT_PRIVATE not in text
    assert OTHER_BOOK_PRIVATE not in text


@pytest.mark.parametrize("control_mode", ["controlled", "uncontrolled"])
@pytest.mark.parametrize("early_status", ["available", "unavailable"])
@pytest.mark.parametrize("case,child_status,child_reason", [
    ("complete", "complete", "none"),
    ("nested_partial", "partial", "nonfatal_error"),
    ("unavailable_capacity_exceeded", "unavailable", "capacity_exceeded"),
])
def test_v2_independent_early_capture_and_consumption_survive_sql_http(
    database, client, monkeypatch, control_mode, early_status, case,
    child_status, child_reason,
):
    # Catches a reader/service that drops v2, conflates early capture with
    # consumption coverage, selects QT/another book, or leaks parent metadata.
    fixture_name = ("controlled" if control_mode == "controlled" else "ordinary") if case == "complete" else case
    value = publication(fixture_name)
    if case == "nested_partial" and control_mode == "controlled":
        # The shared partial child records an ordinary dispatch; this local
        # controlled-run variant retains its ordinary phase and nonfatal error.
        for node in value["consumption"]["nodes"]:
            if node["consumer"] == "setup.selector":
                node["meta"]["mode"] = "controlled"
    if control_mode == "uncontrolled":
        value["identity"].update(control_mode="uncontrolled", runtime_attempt_id=None)
        _exec("DELETE FROM trading.runtime_attempts")
        _exec("DELETE FROM trading.runtime_intents")
    if early_status == "unavailable":
        value.update(status="unavailable", reason="capture_failed",
                     supplied=None, selected_trend=None)
    expected_selector_modes = ([] if case == "unavailable_capacity_exceeded" else
                               ["controlled" if control_mode == "controlled" else "ordinary"])
    assert [node["meta"]["mode"] for node in value["consumption"]["nodes"]
            if node["consumer"] == "setup.selector"] == expected_selector_modes
    _publish(value)

    other = publication("ordinary")
    other["identity"].update(portfolio_id="OTHER", control_mode="uncontrolled",
                             runtime_attempt_id=None,
                             producer_version="synthetic.other_book")
    _exec("UPDATE trading.live_run_metadata SET portfolio_config=%s::jsonb "
          "WHERE strategy_id='LIVE_TREND' AND portfolio_id='OTHER'",
          (json.dumps({"config_inspection": other,
                       "old_key": OTHER_BOOK_PRIVATE}),))

    response = _get(client, monkeypatch)
    assert response.status_code == 200
    _assert_private_and_scoped(response)
    body = response.json
    assert set(body) == {"api_version", "scope", "read_at", "status", "reason", "publication"}
    assert (body["status"], body["reason"]) == (
        ("available", "none") if early_status == "available"
        else ("unavailable", "capture_failed"))
    assert body["publication"] == value
    assert body["publication"]["publication_schema_version"] == 2
    assert body["publication"]["identity"]["portfolio_id"] == "BOOK"
    assert body["publication"]["identity"]["run_date"] == "2026-09-22"
    assert body["publication"]["identity"]["control_mode"] == control_mode
    assert body["publication"]["consumption"]["status"] == child_status
    assert body["publication"]["consumption"]["reason"] == child_reason
    assert [node["meta"]["mode"] for node in body["publication"]["consumption"]["nodes"]
            if node["consumer"] == "setup.selector"] == expected_selector_modes


@pytest.mark.parametrize("early_unavailable", [False, True])
def test_malformed_newest_v2_child_refuses_without_older_fallback(
    database, client, monkeypatch, early_unavailable,
):
    # Catches latest-row fallback or skipping child validation after a failed
    # early capture; the older 2026-09-22 publication remains valid.
    newest = publication("ordinary")
    newest["identity"].update(run_date="2026-09-23", control_mode="uncontrolled",
                              runtime_attempt_id=None)
    newest["captured_at"] = "2026-09-23T15:00:00Z"
    newest["publication_recorded_at"] = "2026-09-23T15:01:00Z"
    newest["consumption"]["reason"] = "synthetic-private-invalid-reason"
    if early_unavailable:
        newest.update(status="unavailable", reason="capture_failed",
                      supplied=None, selected_trend=None)
    _exec("INSERT INTO trading.live_run_metadata VALUES (%s,%s,%s,%s::jsonb)",
          ("LIVE_TREND", "BOOK", "2026-09-23",
           json.dumps({"old_key": PARENT_PRIVATE, "config_inspection": newest})))
    _exec("INSERT INTO trading.live_results VALUES (%s,%s,%s,%s)",
          ("LIVE_TREND", "BOOK", "system", "2026-09-23T16:00:00Z"))

    response = _get(client, monkeypatch)
    assert response.status_code == 200
    _assert_private_and_scoped(response)
    assert (response.json["status"], response.json["reason"],
            response.json["publication"]) == ("unavailable", "invalid_publication", None)
    assert "synthetic-private-invalid-reason" not in response.get_data(as_text=True)


@pytest.mark.parametrize("version", [1, 2])
def test_v1_v2_consumption_contamination_refuses_through_http(
    database, client, monkeypatch, version,
):
    # Catches version dispatch accepting the other version's child grammar.
    value = publication("ordinary")
    if version == 1:
        value["publication_schema_version"] = 1
    else:
        value["consumption"] = {"status": "not_collected"}
    _publish(value)
    response = _get(client, monkeypatch)
    assert response.status_code == 200
    _assert_private_and_scoped(response)
    assert (response.json["status"], response.json["reason"],
            response.json["publication"]) == ("unavailable", "invalid_publication", None)


@pytest.mark.parametrize("sidecar,reason", [
    ("attempt", "invalid_publication"),
    ("revision", "scope_changed"),
])
def test_controlled_sidecar_mismatch_refuses_v2_through_http(
    database, client, monkeypatch, sidecar, reason,
):
    # Catches an attempt fence or current registry revision check being bypassed.
    _publish(publication("controlled"))
    if sidecar == "attempt":
        _exec("UPDATE trading.runtime_attempts SET publication_id=%s",
              ("00000000-0000-4000-8000-000000000000",))
    else:
        _exec("UPDATE trading.strategy_registry SET runtime_revision=2 WHERE id='trend'")
    response = _get(client, monkeypatch)
    assert response.status_code == 200
    _assert_private_and_scoped(response)
    assert (response.json["status"], response.json["reason"],
            response.json["publication"]) == ("unavailable", reason, None)


@pytest.mark.parametrize("adjacent_raw_unit", [
    "1.25", "92233720368.54775806", "-92233720368.54775807",
])
def test_decimal8_strings_and_large_finite_number_survive_jsonb_http(
    database, client, monkeypatch, adjacent_raw_unit,
):
    # Catches Decimal8 rounding/coercion, raw-unit loss, or a uint53 bound
    # incorrectly applied to the catalog's ordinary binary64 number field.
    value = deepcopy(publication("rich"))
    for node in value["consumption"]["nodes"]:
        for read in node["reads"]:
            if read["field"] == "strategy.base_risk.trading_multiplier.symbol.value":
                read["value"] = 9007199254740994.0
            if read["field"] == "risk.capital":
                read["value"] = adjacent_raw_unit
    _publish(value)
    response = _get(client, monkeypatch)
    assert response.status_code == 200
    _assert_private_and_scoped(response)
    assert (response.json["status"], response.json["reason"]) == ("available", "none")
    assert response.json["publication"] == value
    reads = {read["field"]: read for node in response.json["publication"]["consumption"]["nodes"]
             for read in node["reads"]}
    assert reads["strategy.base_risk.risk_max_leverage"]["value"] == "92233720368.54775807"
    assert reads["portfolio.optimization.total_capital"]["value"] == "-92233720368.54775808"
    assert reads["risk.capital"]["value"] == adjacent_raw_unit
    assert reads["strategy.base_risk.trading_multiplier.symbol.value"] == {
        "field": "strategy.base_risk.trading_multiplier.symbol.value",
        "value_type": "number", "value": 9007199254740994.0,
        "origin": "runtime_effective", "symbol": "ES",
    }


def test_jsonb_child_text_cap_refuses_legal_compact_fit(
    database, client, monkeypatch,
):
    # Catches removing the SQL reserved-child cap or treating compact JSON
    # size as proof that PostgreSQL's expanded JSONB text fits transport.
    value = _boundary_publication(2_097_152)
    raw = _raw_short_exponent(value)
    assert len(_compact(value).encode("utf-8")) == 2_097_152
    assert len(raw.encode("utf-8")) == 2_097_151
    _publish(value, raw_child=raw)
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT octet_length((portfolio_config -> 'config_inspection')::text) "
                        "AS child_bytes FROM trading.live_run_metadata "
                        "WHERE strategy_id='LIVE_TREND' AND portfolio_id='BOOK'")
            child_bytes = cur.fetchone()["child_bytes"]
    print(f"SYNTHETIC_JSONB_CHILD_BYTES={child_bytes} COMPACT_BYTES=2097152 RAW_BYTES=2097151")
    assert child_bytes > 2_097_152

    fetched_metadata = []

    class ObservingCursor(RealDictCursor):
        def fetchone(self):
            row = super().fetchone()
            if row is not None and "child_bytes" in row and "child_text" in row:
                fetched_metadata.append((row["child_bytes"], row["child_text"]))
            return row

    def observing_connection():
        return psycopg2.connect(require_test_dsn(), cursor_factory=ObservingCursor)

    response = _get(client, monkeypatch, connection_factory=observing_connection)
    assert fetched_metadata == [(child_bytes, None)]
    assert response.status_code == 200
    _assert_private_and_scoped(response)
    assert (response.json["status"], response.json["reason"],
            response.json["publication"]) == ("unavailable", "invalid_publication", None)


def test_v2_publication_requires_authentication_and_current_internal_role(
    database, client, monkeypatch,
):
    # Catches a bypass of either JWT or current stored role at the real route.
    _publish(publication("ordinary"))
    response = _get(client, monkeypatch, authenticate=False)
    assert response.status_code == 401
    assert "consumption" not in response.get_data(as_text=True)
    _set_jwt_cookie(client, role="admin", identity="7",
                    current_role="subscriber_individual")
    denied = client.get(URL)
    assert denied.status_code == 403
    assert "no-store" in denied.headers["Cache-Control"]
    assert "consumption" not in denied.get_data(as_text=True)

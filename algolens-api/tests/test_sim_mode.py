"""GET /api/sim exists only with SIM_MODE=1 (the local simulator, sim/)."""

from datetime import datetime, timezone

from algolens.adapters.http.sim import sim_mode_enabled, sim_state
from algolens.infrastructure.config.app_factory import create_app


def test_sim_mode_flag():
    assert sim_mode_enabled({"SIM_MODE": "1"})
    assert not sim_mode_enabled({})
    assert not sim_mode_enabled({"SIM_MODE": "0"})
    assert not sim_mode_enabled({"SIM_MODE": "true"})


def test_sim_state_reports_utc_and_new_york():
    state = sim_state(datetime(2026, 10, 15, 13, 29, 5, tzinfo=timezone.utc))
    assert state == {
        "sim": True,
        "serverTime": "2026-10-15T13:29:05+00:00",
        "newYork": "2026-10-15T09:29:05-04:00",
    }


def test_route_absent_without_sim_mode(monkeypatch):
    monkeypatch.delenv("SIM_MODE", raising=False)
    app = create_app()
    assert app.test_client().get("/api/sim").status_code == 404


def test_route_present_with_sim_mode(monkeypatch):
    monkeypatch.setenv("SIM_MODE", "1")
    app = create_app()
    resp = app.test_client().get("/api/sim")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["sim"] is True
    datetime.fromisoformat(body["serverTime"])

"""The desk gRPC client against an in-process server."""

import time
from concurrent import futures
from datetime import date

import grpc
import pytest

from algogators import desk_pb2, desk_pb2_grpc
from algogators.versions import API_VERSIONS
from algolens.application.qt.ports import DeskRiskUnavailable
from algolens.infrastructure.qt.desk_client import DeskClient
from algolens.infrastructure.rpc import HEADER, reset_channels


class RecordingDesk(desk_pb2_grpc.DeskServiceServicer):
    def __init__(self, delay=0.0):
        self.requests = []
        self.headers = []
        self.delay = delay
        self.refuse = None
        self.risk = desk_pb2.DeskRisk(state=desk_pb2.DESK_RISK_STATE_MODEL, within_limits=True, m=1.0)

    def _reply(self, name, request, reply, context):
        time.sleep(self.delay)
        self.requests.append((name, request))
        self.headers.append(dict(context.invocation_metadata()).get(HEADER))
        if self.refuse:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, self.refuse)
        return reply

    def RunDesk(self, request, context):
        return self._reply(
            "RunDesk", request, desk_pb2.RunDeskReply(status=desk_pb2.COMMAND_STATUS_ACCEPTED), context
        )

    def RequestOverride(self, request, context):
        return self._reply(
            "RequestOverride", request, desk_pb2.CommandReply(status=desk_pb2.COMMAND_STATUS_ACCEPTED), context
        )

    def RecordDecision(self, request, context):
        return self._reply(
            "RecordDecision", request, desk_pb2.CommandReply(status=desk_pb2.COMMAND_STATUS_ACCEPTED), context
        )

    def Publish(self, request, context):
        return self._reply(
            "Publish", request, desk_pb2.CommandReply(status=desk_pb2.COMMAND_STATUS_REFUSED), context
        )

    def Rescind(self, request, context):
        return self._reply(
            "Rescind", request, desk_pb2.CommandReply(status=desk_pb2.COMMAND_STATUS_ACCEPTED), context
        )

    def GetDeskRisk(self, request, context):
        return self._reply("GetDeskRisk", request, self.risk, context)

    def CheckSettings(self, request, context):
        import json as _json

        overrides = _json.loads(request.overrides_json)
        ok = overrides.get("risk", {}).get("max_drawdown", 0) < 1
        reply = desk_pb2.SettingsCheck(ok=ok, error="" if ok else "max_drawdown must be below 1")
        return self._reply("CheckSettings", request, reply, context)

    def GetRunStatus(self, request, context):
        reply = desk_pb2.RunStatus(state=desk_pb2.RUN_STATE_REFUSED, message="risk_refusal: R over")
        reply.started_at.FromJsonString("2026-10-08T10:47:00Z")
        return self._reply("GetRunStatus", request, reply, context)


@pytest.fixture
def desk_server():
    servicer = RecordingDesk()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    desk_pb2_grpc.add_DeskServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield servicer, f"127.0.0.1:{port}"
    server.stop(None)
    reset_channels()


COMMAND = {
    "id": 41,
    "portfolio_id": "QT_CONSERVATIVE_PORTFOLIO",
    "date": date(2026, 10, 8),
    "requested_by": "desk@x.com",
    "reason": "why",
}


def test_each_rpc_carries_the_command_row(desk_server):
    servicer, address = desk_server
    agent = DeskClient(address)

    assert agent.run_desk(COMMAND) == "COMMAND_STATUS_ACCEPTED"
    assert agent.request_override(COMMAND) == "COMMAND_STATUS_ACCEPTED"
    decision = {**COMMAND, "id": 42, "requested_by": "vp@x.com", "payload": {"approved": True}}
    assert agent.record_decision(decision, "tok") == "COMMAND_STATUS_ACCEPTED"
    assert agent.publish(COMMAND) == "COMMAND_STATUS_REFUSED"
    assert agent.rescind({**COMMAND, "id": 43}) == "COMMAND_STATUS_ACCEPTED"

    by_name = dict(servicer.requests)
    run = by_name["RunDesk"]
    assert (run.portfolio_id, run.date, run.audit_id, run.requested_by) == (
        "QT_CONSERVATIVE_PORTFOLIO", "2026-10-08", 41, "desk@x.com")
    assert by_name["RequestOverride"].reason == "why"
    rd = by_name["RecordDecision"]
    assert (rd.audit_id, rd.approver, rd.approved, rd.token) == (42, "vp@x.com", True, "tok")
    pub = by_name["Publish"]
    assert (pub.portfolio_id, pub.date, pub.published_by) == (
        "QT_CONSERVATIVE_PORTFOLIO", "2026-10-08", "desk@x.com")
    rescind = by_name["Rescind"]
    assert (rescind.portfolio_id, rescind.date, rescind.audit_id) == (
        "QT_CONSERVATIVE_PORTFOLIO", "2026-10-08", 43)
    # Every call carried the version header, built from the vendored protos.
    assert servicer.headers == [f"common={API_VERSIONS['common']},desk={API_VERSIONS['desk']}"] * 5
    assert API_VERSIONS["desk"] == "1.7.0"


def test_version_refusal_is_logged_and_swallowed(desk_server, caplog):
    servicer, address = desk_server
    servicer.refuse = "API version mismatch for 'desk': client speaks desk=1.0.0, server speaks desk=2.0.0"
    outcome = DeskClient(address).run_desk(COMMAND)
    assert outcome == "not delivered (FAILED_PRECONDITION)"
    assert "API version mismatch" in caplog.text


def test_unreachable_engine_is_swallowed():
    agent = DeskClient("127.0.0.1:1", timeout=0.5)
    started = time.monotonic()
    outcome = agent.run_desk(COMMAND)
    assert outcome.startswith("not delivered")
    assert time.monotonic() - started < 5


def test_slow_engine_times_out_and_is_swallowed(desk_server):
    servicer, address = desk_server
    servicer.delay = 1.0
    outcome = DeskClient(address, timeout=0.2).publish(COMMAND)
    assert outcome == "not delivered (DEADLINE_EXCEEDED)"


def test_default_timeout_is_three_seconds():
    assert DeskClient("x:1").timeout == 3.0


# --- GetDeskRisk (C9): a read, not a command ------------------------------------


def test_get_desk_risk_maps_the_report(desk_server):
    servicer, address = desk_server
    servicer.risk = desk_pb2.DeskRisk(
        state=desk_pb2.DESK_RISK_STATE_DESK,
        audit_id=57,
        within_limits=False,
        approved_override=False,
        breaches=[desk_pb2.RiskBreach(term="L_g", detail="gross leverage bound")],
        m=0.8,
        binding_term="L_g",
        over_limit_after_rounding="R",
        over_limit_by_hold="",
        refused=False,
        symbols=[
            desk_pb2.SymbolRisk(symbol="ZC.v.0", asked=10, given=8, moved_by="overlay", category="risk"),
            desk_pb2.SymbolRisk(symbol="ZS.v.0", asked=-1, given=0, moved_by="sign_close", category="rule"),
        ],
        gross_leverage=2.4,
        margin_cushion=0.0,
        limits=[desk_pb2.RiskLimit(name="max_gross_leverage", value=2.0)],
        checks=[
            desk_pb2.RiskCheck(term="L_g", label="Gross leverage (L_g)", value=2.4, max=2.0,
                               unit="multiple", status=desk_pb2.RISK_CHECK_STATUS_BOUND,
                               detail="the overlay cut the positions to fit this limit"),
            desk_pb2.RiskCheck(term="R", label="Portfolio risk (R)", max=0.45, unit="percent",
                               status=desk_pb2.RISK_CHECK_STATUS_NOT_MEASURED),
        ],
        multipliers=[
            desk_pb2.RiskMultiplier(name="m", label="Risk overlay multiplier (m)", value=0.8,
                                    detail="gross leverage bound"),
            desk_pb2.RiskMultiplier(name="idm:TREND", label="IDM, TREND"),
        ],
        blocks_publish=True,
        blockers=[desk_pb2.RiskBreach(term="MARGIN", detail="margin over the fund cap")],
    )

    report = DeskClient(address).get_desk_risk("QT_CONSERVATIVE_PORTFOLIO", date(2026, 10, 8))

    name, request = servicer.requests[-1]
    assert (name, request.portfolio_id, request.date) == (
        "GetDeskRisk", "QT_CONSERVATIVE_PORTFOLIO", "2026-10-08")
    assert servicer.headers[-1] == f"common={API_VERSIONS['common']},desk={API_VERSIONS['desk']}"
    assert report == {
        "state": "desk",
        "auditId": 57,
        "withinLimits": False,
        "approvedOverride": False,
        "breaches": [{"term": "L_g", "detail": "gross leverage bound"}],
        "blocksPublish": True,
        "blockers": [{"term": "MARGIN", "detail": "margin over the fund cap"}],
        "m": pytest.approx(0.8),
        "bindingTerm": "L_g",
        "overLimitAfterRounding": "R",
        "overLimitByHold": "",
        "refused": False,
        "symbols": [
            {"symbol": "ZC.v.0", "asked": 10.0, "given": 8.0, "movedBy": "overlay", "category": "risk"},
            {"symbol": "ZS.v.0", "asked": -1.0, "given": 0.0, "movedBy": "sign_close", "category": "rule"},
        ],
        # Unset optional readings are None; a recorded 0.0 stays 0.0.
        "grossLeverage": pytest.approx(2.4),
        "netLeverage": None,
        "marginCushion": 0.0,
        "equityToMargin": None,
        "limits": [{"name": "max_gross_leverage", "value": 2.0}],
        "checks": [
            {"term": "L_g", "label": "Gross leverage (L_g)", "value": pytest.approx(2.4),
             "max": pytest.approx(2.0), "unit": "multiple", "status": "bound",
             "detail": "the overlay cut the positions to fit this limit"},
            # An unset reading is None (not measured), not 0.
            {"term": "R", "label": "Portfolio risk (R)", "value": None, "max": pytest.approx(0.45),
             "unit": "percent", "status": "not_measured", "detail": ""},
        ],
        "multipliers": [
            {"name": "m", "label": "Risk overlay multiplier (m)", "value": pytest.approx(0.8),
             "detail": "gross leverage bound"},
            {"name": "idm:TREND", "label": "IDM, TREND", "value": None, "detail": ""},
        ],
    }


@pytest.mark.parametrize(
    "state, name",
    [
        (desk_pb2.DESK_RISK_STATE_NO_BOOK, "no_book"),
        (desk_pb2.DESK_RISK_STATE_MODEL, "model"),
        (desk_pb2.DESK_RISK_STATE_OVERRIDE, "override"),
    ],
)
def test_get_desk_risk_names_each_state(desk_server, state, name):
    servicer, address = desk_server
    servicer.risk = desk_pb2.DeskRisk(state=state, within_limits=True)
    assert DeskClient(address).get_desk_risk("P", date(2026, 10, 8))["state"] == name


def test_get_desk_risk_raises_when_the_engine_refuses(desk_server):
    servicer, address = desk_server
    servicer.refuse = "API version mismatch"
    with pytest.raises(DeskRiskUnavailable) as exc:
        DeskClient(address).get_desk_risk("P", date(2026, 10, 8))
    assert exc.value.reason == "FAILED_PRECONDITION"


def test_get_desk_risk_raises_when_the_engine_is_unreachable():
    with pytest.raises(DeskRiskUnavailable) as exc:
        DeskClient("127.0.0.1:1", timeout=0.5).get_desk_risk("P", date(2026, 10, 8))
    assert exc.value.reason in ("UNAVAILABLE", "DEADLINE_EXCEEDED")


def test_get_desk_risk_maps_an_incomplete_book(desk_server):
    servicer, address = desk_server
    servicer.risk = desk_pb2.DeskRisk(
        state=desk_pb2.DESK_RISK_STATE_INCOMPLETE, blocks_publish=True,
        blockers=[desk_pb2.RiskBreach(term="incomplete", detail="save again")])
    report = DeskClient(address).get_desk_risk("QT_CONSERVATIVE_PORTFOLIO", date(2026, 10, 8))
    assert report["state"] == "incomplete" and report["blocksPublish"] is True


def test_get_run_status_maps_the_state_and_times(desk_server):
    # D-56: the desk page shows the model run's state from the engine, not an inference.
    servicer, address = desk_server
    status = DeskClient(address).get_run_status("P", date(2026, 10, 8))
    assert status == {"state": "refused", "startedAt": "2026-10-08T10:47:00+00:00",
                      "finishedAt": None, "message": "risk_refusal: R over"}
    name, request = servicer.requests[-1]
    assert (name, request.portfolio_id, request.date) == ("GetRunStatus", "P", "2026-10-08")


def test_get_run_status_raises_when_the_engine_is_unreachable():
    with pytest.raises(DeskRiskUnavailable):
        DeskClient("127.0.0.1:1", timeout=0.5).get_run_status("P", date(2026, 10, 8))


def test_check_settings_sends_the_overrides_and_returns_the_answer(desk_server):
    # D-17: the engine is asked before a settings version is saved.
    servicer, address = desk_server
    client = DeskClient(address)
    assert client.check_settings("P", {"risk": {"max_drawdown": 0.25}}) == (True, "")
    assert client.check_settings("P", {"risk": {"max_drawdown": 2}}) == (False, "max_drawdown must be below 1")
    name, request = servicer.requests[-1]
    assert name == "CheckSettings" and request.portfolio_id == "P"


def test_check_settings_raises_when_the_engine_is_unreachable():
    with pytest.raises(DeskRiskUnavailable):
        DeskClient("127.0.0.1:1", timeout=0.5).check_settings("P", {})

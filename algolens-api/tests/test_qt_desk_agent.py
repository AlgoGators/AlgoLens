"""The desk-agent gRPC client against an in-process server."""

import time
from concurrent import futures
from datetime import date

import grpc
import pytest

from algolens.infrastructure.qt.desk_agent import GrpcDeskAgent
from qt.v1 import desk_pb2, desk_pb2_grpc


class RecordingDesk(desk_pb2_grpc.DeskServiceServicer):
    def __init__(self, delay=0.0):
        self.requests = []
        self.delay = delay

    def _reply(self, name, request, reply):
        time.sleep(self.delay)
        self.requests.append((name, request))
        return reply

    def RunDesk(self, request, context):
        return self._reply(
            "RunDesk", request, desk_pb2.RunDeskReply(status=desk_pb2.COMMAND_STATUS_ACCEPTED)
        )

    def RequestOverride(self, request, context):
        return self._reply(
            "RequestOverride", request, desk_pb2.CommandReply(status=desk_pb2.COMMAND_STATUS_ACCEPTED)
        )

    def RecordDecision(self, request, context):
        return self._reply(
            "RecordDecision", request, desk_pb2.CommandReply(status=desk_pb2.COMMAND_STATUS_ACCEPTED)
        )

    def Publish(self, request, context):
        return self._reply(
            "Publish", request, desk_pb2.CommandReply(status=desk_pb2.COMMAND_STATUS_REFUSED)
        )


@pytest.fixture
def desk_server():
    servicer = RecordingDesk()
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    desk_pb2_grpc.add_DeskServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    yield servicer, f"127.0.0.1:{port}"
    server.stop(None)


COMMAND = {
    "id": 41,
    "portfolio_id": "QT_CONSERVATIVE_PORTFOLIO",
    "date": date(2026, 10, 8),
    "requested_by": "desk@x.com",
    "reason": "why",
}


def test_each_rpc_carries_the_command_row(desk_server):
    servicer, address = desk_server
    agent = GrpcDeskAgent(address)

    assert agent.run_desk(COMMAND) == "COMMAND_STATUS_ACCEPTED"
    assert agent.request_override(COMMAND) == "COMMAND_STATUS_ACCEPTED"
    decision = {**COMMAND, "id": 42, "requested_by": "vp@x.com", "payload": {"approved": True}}
    assert agent.record_decision(decision, "tok") == "COMMAND_STATUS_ACCEPTED"
    assert agent.publish(COMMAND) == "COMMAND_STATUS_REFUSED"

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


def test_unreachable_agent_is_swallowed():
    agent = GrpcDeskAgent("127.0.0.1:1", timeout=0.5)
    started = time.monotonic()
    outcome = agent.run_desk(COMMAND)
    assert outcome.startswith("not delivered")
    assert time.monotonic() - started < 5


def test_slow_agent_times_out_and_is_swallowed(desk_server):
    servicer, address = desk_server
    servicer.delay = 1.0
    outcome = GrpcDeskAgent(address, timeout=0.2).publish(COMMAND)
    assert outcome == "not delivered (DEADLINE_EXCEEDED)"


def test_default_timeout_is_three_seconds():
    assert GrpcDeskAgent("x:1").timeout == 3.0

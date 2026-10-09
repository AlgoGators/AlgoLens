"""gRPC client of the engine's desk service (proto/algogators/desk.proto).

Implements DeskAgentPort on the shared rpc layer (infrastructure/rpc): a cached channel per
address and the x-algogators-api-version header on every call.

The call is the fast path only (contract section 6): AlgoLens has already
written the trading.position_overrides row, the engine re-drives pending rows
on startup and every 60 s, so a failed or slow call is logged and swallowed.
It never fails the user's action. Timeout: 3 s (ENGINE_RPC_TIMEOUT_SECONDS).
"""

import logging

import grpc

from algogators import desk_pb2, desk_pb2_grpc
from algolens.infrastructure.rpc.settings import DEFAULT_TIMEOUT_SECONDS
from algolens.infrastructure.rpc import describe_rpc_error, get_channel, is_version_mismatch, status_name

logger = logging.getLogger(__name__)


def _day(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class DeskClient:
    def __init__(self, address, timeout=DEFAULT_TIMEOUT_SECONDS, channel_factory=None):
        self.address = address
        self.timeout = timeout
        # channel_factory(address) -> a channel that sends the version header. The default
        # returns the process-wide cached channel; it is never closed per call.
        self.channel_factory = channel_factory or get_channel

    def _call(self, method, request, audit_id):
        try:
            stub = desk_pb2_grpc.DeskServiceStub(self.channel_factory(self.address))
            reply = getattr(stub, method)(request, timeout=self.timeout)
            outcome = desk_pb2.CommandStatus.Name(reply.status)
            logger.info("[DESK] %s audit_id=%s -> %s", method, audit_id, outcome)
            return outcome
        except grpc.RpcError as exc:
            code = status_name(exc)
            if is_version_mismatch(exc):
                # A deploy bug, not an outage: this build speaks another major version of the
                # desk API. The row still stays pending and the engine's re-drive runs it.
                logger.error(
                    "[DESK] %s audit_id=%s refused by the engine: %s",
                    method,
                    audit_id,
                    describe_rpc_error(exc),
                )
            else:
                logger.warning(
                    "[DESK] %s audit_id=%s not delivered (%s); the row stays pending and "
                    "the engine re-drives it",
                    method,
                    audit_id,
                    code,
                )
            return f"not delivered ({code})"
        except Exception as exc:  # never fail the user's action on the fast path
            logger.error("[DESK] %s audit_id=%s failed: %s", method, audit_id, exc, exc_info=True)
            return "not delivered (error)"

    def run_desk(self, command):
        request = desk_pb2.RunDeskRequest(
            portfolio_id=command["portfolio_id"],
            date=_day(command["date"]),
            audit_id=int(command["id"]),
            requested_by=command["requested_by"],
        )
        return self._call("RunDesk", request, command["id"])

    def request_override(self, command):
        request = desk_pb2.OverrideRequest(
            portfolio_id=command["portfolio_id"],
            date=_day(command["date"]),
            audit_id=int(command["id"]),
            requested_by=command["requested_by"],
            reason=command.get("reason") or "",
        )
        return self._call("RequestOverride", request, command["id"])

    def record_decision(self, decision, token):
        # audit_id is the DECISION row's id (contract section 6: AlgoLens
        # inserts the row first and calls with its id); the request it decides
        # is the row's parent_id.
        request = desk_pb2.DecisionRequest(
            audit_id=int(decision["id"]),
            approver=decision["requested_by"],
            approved=bool((decision.get("payload") or {}).get("approved")),
            token=token,
        )
        return self._call("RecordDecision", request, decision["id"])

    def publish(self, command):
        # audit_id is left 0: the engine takes the newest pending publish row
        # for the portfolio and date (desk.proto PublishRequest).
        request = desk_pb2.PublishRequest(
            portfolio_id=command["portfolio_id"],
            date=_day(command["date"]),
            published_by=command["requested_by"],
        )
        return self._call("Publish", request, command["id"])

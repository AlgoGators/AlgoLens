"""gRPC client of the engine's desk service (proto/algogators/desk.proto).

Implements DeskAgentPort on the shared rpc layer (infrastructure/rpc): a cached channel per
address and the x-algogators-api-version header on every call.

The call is the fast path only (contract section 6): AlgoLens has already
written the trading.position_overrides row, the engine re-drives pending rows
on startup and every 60 s, so a failed or slow call is logged and swallowed.
It never fails the user's action. Timeout: 3 s (ENGINE_RPC_TIMEOUT_SECONDS).

GetDeskRisk (contract C9) is a read, not a command: there is no row to fall
back on, so a failed call raises DeskRiskUnavailable and the caller decides
(the desk state shows it; the approval gate refuses, failing closed).
"""

import logging

import grpc

from algogators import desk_pb2, desk_pb2_grpc
from algolens.application.qt.ports import DeskRiskUnavailable
from algolens.infrastructure.rpc.settings import DEFAULT_TIMEOUT_SECONDS
from algolens.infrastructure.rpc import describe_rpc_error, get_channel, is_version_mismatch, status_name

logger = logging.getLogger(__name__)


def _day(value):
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


# DeskRiskState -> the report's "state".
RISK_STATES = {
    desk_pb2.DESK_RISK_STATE_NO_BOOK: "no_book",
    desk_pb2.DESK_RISK_STATE_MODEL: "model",
    desk_pb2.DESK_RISK_STATE_DESK: "desk",
    desk_pb2.DESK_RISK_STATE_OVERRIDE: "override",
}


# RiskCheckStatus -> a check's "status" (desk.proto 1.4.0).
CHECK_STATUSES = {
    desk_pb2.RISK_CHECK_STATUS_WITHIN: "within",
    desk_pb2.RISK_CHECK_STATUS_BOUND: "bound",
    desk_pb2.RISK_CHECK_STATUS_OVER: "over",
    desk_pb2.RISK_CHECK_STATUS_NOT_MEASURED: "not_measured",
}


def _optional(message, field):
    return getattr(message, field) if message.HasField(field) else None


def risk_report(reply):
    """A DeskRisk message as the JSON-friendly report of DeskAgentPort.get_desk_risk."""
    return {
        "state": RISK_STATES.get(reply.state, "unspecified"),
        "auditId": int(reply.audit_id),
        "withinLimits": reply.within_limits,
        "approvedOverride": reply.approved_override,
        "breaches": [{"term": b.term, "detail": b.detail} for b in reply.breaches],
        "m": reply.m,
        "bindingTerm": reply.binding_term,
        "overLimitAfterRounding": reply.over_limit_after_rounding,
        "overLimitByHold": reply.over_limit_by_hold,
        "refused": reply.refused,
        "symbols": [
            {
                "symbol": s.symbol,
                "asked": s.asked,
                "given": s.given,
                "movedBy": s.moved_by,
                "category": s.category,
            }
            for s in reply.symbols
        ],
        "grossLeverage": _optional(reply, "gross_leverage"),
        "netLeverage": _optional(reply, "net_leverage"),
        "marginCushion": _optional(reply, "margin_cushion"),
        "equityToMargin": _optional(reply, "equity_to_margin"),
        "limits": [{"name": limit.name, "value": limit.value} for limit in reply.limits],
        # Every check with its reading and max, as trade-ngin labels and measures them.
        "checks": [
            {
                "term": c.term,
                "label": c.label,
                "value": _optional(c, "value"),
                "max": _optional(c, "max"),
                "unit": c.unit,
                "status": CHECK_STATUSES.get(c.status, "not_measured"),
                "detail": c.detail,
            }
            for c in reply.checks
        ],
        # The multipliers of the day's book (1.5.0): the overlay's m, the risk
        # scale, and each strategy's configured IDM and FDM.
        "multipliers": [
            {"name": x.name, "label": x.label, "value": _optional(x, "value"), "detail": x.detail}
            for x in reply.multipliers
        ],
    }


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
        # audit_id names the publish row (0 would take the newest pending one
        # for the portfolio and date; desk.proto PublishRequest).
        request = desk_pb2.PublishRequest(
            portfolio_id=command["portfolio_id"],
            date=_day(command["date"]),
            published_by=command["requested_by"],
            audit_id=int(command["id"]),
        )
        return self._call("Publish", request, command["id"])

    def rescind(self, command):
        # audit_id is required here (desk.proto 1.2.0 RescindRequest): the
        # engine runs exactly the 'rescind' row AlgoLens wrote.
        request = desk_pb2.RescindRequest(
            portfolio_id=command["portfolio_id"],
            date=_day(command["date"]),
            audit_id=int(command["id"]),
        )
        return self._call("Rescind", request, command["id"])

    def get_desk_risk(self, portfolio_id, day):
        request = desk_pb2.DeskRiskRequest(portfolio_id=portfolio_id, date=_day(day))
        try:
            stub = desk_pb2_grpc.DeskServiceStub(self.channel_factory(self.address))
            reply = stub.GetDeskRisk(request, timeout=self.timeout)
        except grpc.RpcError as exc:
            # The status name is the reason the desk sees; the details go to the log only.
            log = logger.error if is_version_mismatch(exc) else logger.warning
            log("[DESK] GetDeskRisk %s %s failed: %s", portfolio_id, _day(day), describe_rpc_error(exc))
            raise DeskRiskUnavailable(status_name(exc)) from exc
        except Exception as exc:
            logger.error(
                "[DESK] GetDeskRisk %s %s failed: %s", portfolio_id, _day(day), exc, exc_info=True
            )
            raise DeskRiskUnavailable("error") from exc
        return risk_report(reply)

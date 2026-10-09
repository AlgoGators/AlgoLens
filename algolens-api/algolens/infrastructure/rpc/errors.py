"""Turning a grpc.RpcError into something short and loggable.

The engine answers with standard status codes (trade-ngin docs/design/rpc.md):
INVALID_ARGUMENT     a caller bug (bad date, audit_id <= 0, empty reason)
UNAVAILABLE          the engine or its database is down; retry with the same audit_id
DEADLINE_EXCEEDED    the call took longer than its timeout
FAILED_PRECONDITION  version mismatch: this build speaks another major version of the API
"""

import grpc


def status_name(exc):
    code = exc.code() if hasattr(exc, "code") else None
    return code.name if isinstance(code, grpc.StatusCode) else "UNKNOWN"


def is_version_mismatch(exc):
    return status_name(exc) == grpc.StatusCode.FAILED_PRECONDITION.name


def describe_rpc_error(exc):
    details = exc.details() if hasattr(exc, "details") else None
    name = status_name(exc)
    return f"{name}: {details}" if details else name

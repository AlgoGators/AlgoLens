"""Shared gRPC client layer for the engine's APIs (trade-ngin docs/design/rpc.md).

Every client of an engine service (today: the QT desk, infrastructure/qt/desk_client.py) gets
its channel here, so they all share:

- one cached channel per address and process, with keepalive and reconnect settings
  (channels.py);
- the x-algogators-api-version header on every call, from the vendored protos' version
  headers via the generated algogators.versions (version_header.py);
- the address and default timeout from the environment (settings.py);
- helpers that turn a grpc.RpcError into a short, loggable outcome (errors.py).
"""

from algolens.infrastructure.rpc.channels import get_channel, reset_channels
from algolens.infrastructure.rpc.errors import describe_rpc_error, is_version_mismatch, status_name
from algolens.infrastructure.rpc.settings import RpcSettings, load_rpc_settings
from algolens.infrastructure.rpc.version_header import (
    HEADER,
    VersionHeaderInterceptor,
    header_value,
)

__all__ = [
    "HEADER",
    "RpcSettings",
    "VersionHeaderInterceptor",
    "describe_rpc_error",
    "get_channel",
    "header_value",
    "is_version_mismatch",
    "load_rpc_settings",
    "reset_channels",
    "status_name",
]

"""Where the engine's gRPC server is, and how long a call may take.

ENGINE_RPC_ADDR             host:port of the engine's gRPC server (trade-ngin `engine-rpc`).
                            Default engine-rpc:50051, on the private Docker network `qt`.
DESK_AGENT_ADDR             The name before the shared layer. Read when ENGINE_RPC_ADDR is
                            unset, for one release.
ENGINE_RPC_TIMEOUT_SECONDS  Default deadline of a call. Default 3 s.
"""

import os
from dataclasses import dataclass

DEFAULT_ENGINE_RPC_ADDR = "engine-rpc:50051"
DEFAULT_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class RpcSettings:
    engine_addr: str = DEFAULT_ENGINE_RPC_ADDR
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


def _timeout(raw):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def load_rpc_settings(environ=None):
    env = os.environ if environ is None else environ
    addr = (
        (env.get("ENGINE_RPC_ADDR") or "").strip()
        or (env.get("DESK_AGENT_ADDR") or "").strip()
        or DEFAULT_ENGINE_RPC_ADDR
    )
    raw_timeout = (env.get("ENGINE_RPC_TIMEOUT_SECONDS") or "").strip()
    timeout = _timeout(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
    return RpcSettings(engine_addr=addr, timeout_seconds=timeout)

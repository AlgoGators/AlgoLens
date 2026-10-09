"""QT desk settings from the environment.

QT_DESK_ENABLED   "true" turns on the desk UI and every desk write endpoint.
                  Default false (ruling 22: editing is not live before the
                  engine's desk run exists).
QT_APPROVERS      "vp=<email>,president=<email>": who may decide an override.
DESK_AGENT_ADDR   host:port of the engine's desk-agent gRPC server.
"""

import os
from dataclasses import dataclass, field

from algolens.domain.qt.approvers import parse_approvers

DEFAULT_DESK_AGENT_ADDR = "desk-agent:50051"
DESK_AGENT_TIMEOUT_SECONDS = 3.0


@dataclass(frozen=True)
class QtSettings:
    desk_enabled: bool = False
    approvers: dict = field(default_factory=dict)
    desk_agent_addr: str = DEFAULT_DESK_AGENT_ADDR


def _truthy(value):
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_qt_settings(environ=None):
    env = os.environ if environ is None else environ
    return QtSettings(
        desk_enabled=_truthy(env.get("QT_DESK_ENABLED")),
        approvers=parse_approvers(env.get("QT_APPROVERS", "")),
        desk_agent_addr=(env.get("DESK_AGENT_ADDR") or "").strip() or DEFAULT_DESK_AGENT_ADDR,
    )

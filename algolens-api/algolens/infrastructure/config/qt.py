"""QT desk settings from the environment.

QT_DESK_ENABLED   "true" turns on the desk UI and every desk write endpoint.
                  Default false (ruling 22: editing is not live before the
                  engine's desk run exists).
QT_APPROVERS      "vp=<email>,president=<email>": who may decide an override.

The engine's address (ENGINE_RPC_ADDR, falling back to DESK_AGENT_ADDR) is
read by the shared rpc layer: algolens.infrastructure.rpc.settings.
"""

import os
from dataclasses import dataclass, field

from algolens.domain.qt.approvers import parse_approvers


@dataclass(frozen=True)
class QtSettings:
    desk_enabled: bool = False
    approvers: dict = field(default_factory=dict)


def _truthy(value):
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def load_qt_settings(environ=None):
    env = os.environ if environ is None else environ
    return QtSettings(
        desk_enabled=_truthy(env.get("QT_DESK_ENABLED")),
        approvers=parse_approvers(env.get("QT_APPROVERS", "")),
    )

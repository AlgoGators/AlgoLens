"""Simulation mode: GET /api/sim, for the local simulator under sim/.

Registered only when SIM_MODE=1 (sim/docker-compose.sim.yml sets it). The
frontend asks this route once on load; a 404 (every real deployment) means no
banner. With SIM_MODE=1 it answers the server's clock, which in the simulator
is the moved sim clock, so the banner shows the time the desk rules use.

No login needed: the banner also shows on the login page. It reveals only the
server time.
"""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, jsonify

NEW_YORK = ZoneInfo("America/New_York")

sim_bp = Blueprint("sim", __name__)


def sim_mode_enabled(environ=None):
    env = os.environ if environ is None else environ
    return (env.get("SIM_MODE") or "").strip() == "1"


def sim_state(now):
    return {
        "sim": True,
        "serverTime": now.astimezone(timezone.utc).isoformat(),
        "newYork": now.astimezone(NEW_YORK).isoformat(),
    }


@sim_bp.route("", methods=["GET"])
def get_sim():
    return jsonify(sim_state(datetime.now(timezone.utc))), 200

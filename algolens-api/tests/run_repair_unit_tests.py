"""Offline repair runner: invoke under unshare --user --map-root-user --net."""
import os
from pathlib import Path
import socket
import sys

if sorted(name for _, name in socket.if_nameindex()) != ["lo"]:
    raise SystemExit("Refusing tests outside an isolated network namespace")
if any(line.strip() for line in Path("/proc/net/route").read_text().splitlines()[1:]):
    raise SystemExit("Refusing tests with network routes")

os.environ.clear()
os.environ.update(PATH="/usr/bin:/bin", FLASK_ENV="development",
                  JWT_SECRET_KEY="offline-repair-tests-only-secret-20260921",
                  PYTHON_DOTENV_DISABLED="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")

def denied(*args, **kwargs):
    raise RuntimeError("Network disabled for offline repair tests")

socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
socket.getaddrinfo = denied

import dotenv
dotenv.load_dotenv = lambda *args, **kwargs: False
dotenv.dotenv_values = lambda *args, **kwargs: {}
import pytest

os.chdir(Path(__file__).resolve().parents[1])
sys.path.insert(0, str(Path.cwd()))
raise SystemExit(pytest.main(sys.argv[1:]))

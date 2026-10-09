#!/usr/bin/env sh
# Regenerate the Python stubs of the engine's desk-agent contract.
#
#   proto/qt/v1/desk.proto  (vendored from trade-ngin; header names the commit)
#   -> qt/v1/desk_pb2.py, qt/v1/desk_pb2_grpc.py
#
# Needs grpcio-tools at the version pinned in requirements-dev.txt. CI runs
# this and fails when the committed stubs differ from what it generates.
set -eu
cd "$(dirname "$0")/.."
python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/qt/v1/desk.proto

#!/usr/bin/env bash
# Build the engine image the simulator runs (engine-rpc: the gRPC desk service and the C++
# engine) from a trade-ngin checkout. trade-ngin's Dockerfile is not changed: a copy of the
# checkout's HEAD is built with a patched Dockerfile that
#   1. compiles only the engine binaries the image runs (not the test and benchmark files), and
#   2. keeps a ccache in a BuildKit cache mount, so a rebuild recompiles only what changed.
# The first build takes about 12 minutes; later ones 30 s to 3 min.
#
#   bash sim/engine/build-engine.sh <trade-ngin checkout> [jobs]
#       -> trade-ngin:rpc-<sha8> and trade-ngin:sim (the simulator's default ENGINE_IMAGE)
#
# Get trade-ngin with:  git clone https://github.com/AlgoGators/trade-ngin.git
# and build its main branch (what production runs) unless you are testing an engine branch.
set -euo pipefail
export MSYS_NO_PATHCONV=1
SRC=${1:?usage: build-engine.sh <trade-ngin checkout> [jobs]}
JOBS=${2:-4}
[ -f "$SRC/Dockerfile" ] && [ -d "$SRC/services/rpc" ] || { echo "build-engine: $SRC is not a trade-ngin checkout" >&2; exit 1; }
SHA=$(git -C "$SRC" rev-parse --short=8 HEAD)
OUT=$(mktemp -d "${TMPDIR:-/tmp}/trade-ngin-build.XXXXXX")
trap 'rm -rf "$OUT"' EXIT
git -C "$SRC" archive HEAD | tar -x -C "$OUT"
# Windows python and docker.exe need a Windows path under Git Bash.
OUT_HOST=$(cygpath -m "$OUT" 2>/dev/null || echo "$OUT")
[ -z "$(git -C "$SRC" status --porcelain)" ] || echo "build-engine: note: uncommitted changes in $SRC are NOT built (HEAD $SHA is)"

PY=python3; command -v "$PY" >/dev/null 2>&1 || PY=python
"$PY" - "$OUT_HOST/Dockerfile" "$JOBS" <<'PYEOF'
import sys
path, jobs = sys.argv[1], sys.argv[2]
s = open(path, encoding="utf-8").read()
s = "# syntax=docker/dockerfile:1\n" + s
old = r'''RUN cmake -S /app -B /app/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
        -DNLopt_DIR=/usr/lib/x86_64-linux-gnu/cmake/nlopt && \
    cmake --build /app/build --config Release -j"$(nproc)"'''
new = rf'''RUN apt-get update && apt-get install -y --no-install-recommends ccache \
    && rm -rf /var/lib/apt/lists/*
ENV CCACHE_DIR=/ccache CCACHE_BASEDIR=/app CCACHE_COMPILERCHECK=content CCACHE_MAXSIZE=5G
RUN --mount=type=cache,id=trade-ngin-ccache,target=/ccache \
    cmake -S /app -B /app/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
        -DCMAKE_CXX_COMPILER_LAUNCHER=ccache -DCMAKE_C_COMPILER_LAUNCHER=ccache \
        -DNLopt_DIR=/usr/lib/x86_64-linux-gnu/cmake/nlopt && \
    cmake --build /app/build --config Release -j{jobs} --target \
        live_portfolio live_portfolio_conservative live_equity_mr \
        bt_portfolio bt_portfolio_conservative bt_equity_mr bt_equity_validation \
        bt_transaction_cost_report'''
if s.count(old) != 1:
    sys.exit("build-engine: trade-ngin's Dockerfile build step changed; build with "
             "`docker build -t trade-ngin:sim <checkout>` instead (slower) and tell the sim's maintainer")
open(path, "w", encoding="utf-8").write(s.replace(old, new))
PYEOF

echo "build-engine: building trade-ngin $SHA with $JOBS jobs (log: docker's output below)"
start=$(date +%s)
DOCKER_BUILDKIT=1 docker build -t "trade-ngin:rpc-$SHA" -t trade-ngin:sim "$OUT_HOST"
echo "build-engine: built trade-ngin:rpc-$SHA (also tagged trade-ngin:sim) in $(( $(date +%s) - start ))s"

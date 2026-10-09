#!/usr/bin/env sh
# Vendor the engine's gRPC contract from AlgoGators/trade-ngin, or check the vendored copy.
#
#   scripts/sync_protos.sh <trade-ngin commit>   fetch proto/algogators/*.proto and
#                                                services/rpc/gen_versions.py at that commit,
#                                                record it in proto/algogators/SOURCE, then run
#                                                scripts/gen_proto.sh
#   scripts/sync_protos.sh --check               fail unless every vendored file is
#                                                byte-identical to trade-ngin at the commit in
#                                                SOURCE, and the set of .proto files matches
#
# Uses the public GitHub API and raw.githubusercontent.com (curl). CI runs --check.
set -eu
cd "$(dirname "$0")/.."

REPO=AlgoGators/trade-ngin
SOURCE=proto/algogators/SOURCE

fetch() { # <commit> <path in trade-ngin> <dest>
    curl -fsSL --retry 3 "https://raw.githubusercontent.com/$REPO/$1/$2" -o "$3"
}

upstream_protos() { # <commit> -> the .proto file names under proto/algogators, sorted
    curl -fsSL --retry 3 ${GITHUB_TOKEN:+-H "Authorization: Bearer $GITHUB_TOKEN"} \
        "https://api.github.com/repos/$REPO/contents/proto/algogators?ref=$1" |
        python -c 'import json, sys; print("\n".join(sorted(e["name"] for e in json.load(sys.stdin) if e["name"].endswith(".proto"))))'
}

if [ "${1:-}" = "--check" ]; then
    commit=$(sed -n 's/^commit: *//p' "$SOURCE")
    [ -n "$commit" ] || { echo "no 'commit:' line in $SOURCE" >&2; exit 1; }
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT
    fail=0
    local_list=$(cd proto/algogators && ls *.proto | sort)
    remote_list=$(upstream_protos "$commit")
    if [ "$local_list" != "$remote_list" ]; then
        echo "proto set differs from $REPO@$commit: vendored [$local_list] upstream [$remote_list]" >&2
        fail=1
    fi
    for name in $remote_list; do
        fetch "$commit" "proto/algogators/$name" "$tmp/$name"
        if ! cmp -s "$tmp/$name" "proto/algogators/$name"; then
            echo "proto/algogators/$name differs from $REPO@$commit" >&2
            fail=1
        fi
    done
    fetch "$commit" services/rpc/gen_versions.py "$tmp/gen_versions.py"
    if ! cmp -s "$tmp/gen_versions.py" scripts/gen_versions.py; then
        echo "scripts/gen_versions.py differs from $REPO@$commit services/rpc/gen_versions.py" >&2
        fail=1
    fi
    [ "$fail" = 0 ] && echo "vendored protos match $REPO@$commit"
    exit "$fail"
fi

commit=${1:?usage: scripts/sync_protos.sh <trade-ngin commit> | --check}
list=$(upstream_protos "$commit")
[ -n "$list" ] || { echo "no .proto files at $REPO@$commit" >&2; exit 1; }
rm -f proto/algogators/*.proto
for name in $list; do
    fetch "$commit" "proto/algogators/$name" "proto/algogators/$name"
done
fetch "$commit" services/rpc/gen_versions.py scripts/gen_versions.py
printf 'repo: %s\ncommit: %s\n' "$REPO" "$commit" > "$SOURCE"
sh scripts/gen_proto.sh
echo "vendored $REPO@$commit; review and commit proto/algogators, scripts/gen_versions.py, algogators/"

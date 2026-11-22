#!/usr/bin/env bash
# Push to GitHub through the REST API, retrying through this host's flaky egress.
# (git push over smart-HTTPS POST is unusable here; see scripts/push_via_api.py.)
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
PY=/home/da/.local/share/uv/python/cpython-3.11.17-linux-x86_64-gnu/bin/python3.11
REPO="${GITHUB_REPO:-jssyxd/DodgysDD-iFVG}"
for i in $(seq 1 "${1:-30}"); do
    echo "--- attempt $i $(date -u +%H:%M:%S) ---"
    if $PY scripts/push_via_api.py --repo "$REPO" --branch "${GITHUB_BRANCH:-main}"; then
        echo "API PUSH OK"; exit 0
    fi
    sleep 15
done
echo "API PUSH FAILED"; exit 1

#!/usr/bin/env bash
# Push to GitHub, retrying through this host's intermittent TLS resets.
#
# `git push` over smart-HTTP needs one long-lived connection for the packfile
# upload; this host's egress drops long transfers ("Empty reply from server",
# "TLS: UNEXPECTED_EOF_WHILE_READING"). The pack here is small, so a patient
# retry succeeds as soon as a connection survives.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

LOCAL=$(git rev-parse HEAD)
BRANCH="${GITHUB_BRANCH:-main}"
ATTEMPTS="${1:-60}"

for i in $(seq 1 "$ATTEMPTS"); do
    if git push origin "HEAD:refs/heads/$BRANCH" >/tmp/push_attempt.log 2>&1; then
        REMOTE=$(git ls-remote origin "refs/heads/$BRANCH" 2>/dev/null | awk '{print $1}')
        if [ "$REMOTE" = "$LOCAL" ]; then
            echo "SYNCED after $i attempt(s): $LOCAL"
            exit 0
        fi
    fi
    sleep 15
done
echo "NOT SYNCED after $ATTEMPTS attempts"
tail -3 /tmp/push_attempt.log
exit 1

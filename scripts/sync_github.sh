#!/usr/bin/env bash
# Synchronise this repository with GitHub.
#
#   scripts/sync_github.sh              # commit local work (if any) and push
#   scripts/sync_github.sh --check      # report what would be pushed, push nothing
#   scripts/sync_github.sh --set-upstream <fork-or-branch>
#
# Credentials: read from the environment (GITHUB_TOKEN) or from ~/.git-credentials.
# The token is NEVER written into .git/config and never echoed.
#
# The pre-commit hook (scripts/pre-commit-secret-scan.sh) blocks any commit that
# would introduce a live credential, so a push cannot leak a key.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

REMOTE="${GITHUB_REMOTE:-origin}"
BRANCH="${GITHUB_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

if [ "$CHECK_ONLY" -eq 1 ]; then
    echo "--- branch: $BRANCH -> $REMOTE/$BRANCH"
    git fetch "$REMOTE" "$BRANCH" --quiet 2>/dev/null
    ahead=$(git rev-list --count "$REMOTE/$BRANCH..HEAD" 2>/dev/null || echo "?")
    behind=$(git rev-list --count "HEAD..$REMOTE/$BRANCH" 2>/dev/null || echo "?")
    echo "--- ahead: $ahead commit(s), behind: $behind commit(s)"
    echo "--- working tree:"
    git status --short
    echo "--- files that would be pushed:"
    git log --oneline "$REMOTE/$BRANCH..HEAD" 2>/dev/null || echo "  (none)"
    exit 0
fi

# ---- credential handling -------------------------------------------------
# Prefer an explicit token in the environment; otherwise fall back to whatever
# git already has configured for the remote.
if [ -n "${GITHUB_TOKEN:-}" ]; then
    askpass=$(mktemp)
    cat > "$askpass" <<EOF
#!/bin/sh
case "\$1" in
  *Username*) echo "${GITHUB_USERNAME:-x-access-token}" ;;
  *Password*) echo "$GITHUB_TOKEN" ;;
esac
EOF
    chmod 700 "$askpass"
    export GIT_ASKPASS="$askpass"
    export GIT_TERMINAL_PROMPT=0
    trap 'rm -f "$askpass"' EXIT
fi

# ---- commit ---------------------------------------------------------------
if [ -n "$(git status --porcelain)" ]; then
    MSG="${1:-chore: sync}"
    if [ "$MSG" = "chore: sync" ]; then
        MSG="chore: sync $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    fi
    git add -A || exit 1
    git -c user.email="${GIT_AUTHOR_EMAIL:-captain@local}" \
        -c user.name="${GIT_AUTHOR_NAME:-captain}" \
        commit -m "$MSG" || exit 1
    echo "committed: $MSG"
fi

# ---- push -----------------------------------------------------------------
if git push "$REMOTE" "HEAD:$BRANCH" 2>&1 | sed 's/^/  /'; then
    echo "synced -> $REMOTE/$BRANCH"
else
    echo "PUSH FAILED" >&2
    exit 1
fi

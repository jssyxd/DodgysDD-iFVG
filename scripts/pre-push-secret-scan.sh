#!/usr/bin/env bash
# Pre-push guard: scan the tree that is about to leave this machine.
#
# The pre-commit hook catches secrets at commit time. This is the second line of
# defence: it runs over the *pushed* commits, so a secret that entered history
# by any other route (a merge, a rebase, a --no-verify commit, an amended
# commit) is still caught before it reaches the remote.
#
# Install: cp scripts/pre-push-secret-scan.sh .git/hooks/pre-push
set -uo pipefail

REMOTE_REF="${1:-}"
URL="${2:-}"

# Only guard our own remote.
case "$URL" in
    *github.com/jssyxd/DodgysDD-iFVG*) ;;
    *) exit 0 ;;
esac

PATTERNS='ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{60,}|hf_[A-Za-z0-9]{34}|KGAT_[A-Za-z0-9]{32}|sk-[A-Za-z0-9]{32}|xoxb-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----'
KNOWN_FILE="$(dirname "$0")/known_tokens.txt"

scan_range() {
    git grep -nEI "$PATTERNS" "$1" -- . 2>/dev/null
    if [ -f "$KNOWN_FILE" ]; then
        while IFS= read -r tok; do
            [ -z "$tok" ] && continue
            git grep -nF "$tok" "$1" -- . 2>/dev/null
        done < "$KNOWN_FILE"
    fi
}

RANGE="HEAD"
if [ -n "$REMOTE_REF" ] && git rev-parse --verify "$REMOTE_REF" >/dev/null 2>&1; then
    RANGE="${REMOTE_REF}..HEAD"
fi

HITS=$(scan_range "$RANGE" | head -20)
if [ -n "$HITS" ]; then
    echo "PUSH BLOCKED — credentials found in the commits being pushed:"
    echo "$HITS" | sed 's/^/  /'
    echo
    echo "Rewrite the offending commits (git filter-repo / git rebase) before pushing."
    exit 1
fi

BAD=$(git ls-files | grep -iE 'apikey|api_key|环境\.txt|^\.env$' || true)
if [ -n "$BAD" ]; then
    echo "PUSH BLOCKED — secrets file is tracked:"
    echo "$BAD" | sed 's/^/  /'
    exit 1
fi

echo "pre-push: no credentials in $(git rev-list --count "$RANGE" 2>/dev/null || echo 0) outgoing commit(s)"
exit 0
